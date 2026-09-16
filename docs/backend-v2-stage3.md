# 后端 v2 第三阶段：控制与恢复

版本：`2.0.0-dev.3`。验证日期：2026-09-16。

## 已交付

- ROS 1 / ROS 2 原生发布 `PoseStamped`、`PoseWithCovarianceStamped`、`Twist`。
- 网页目标面板和场景目标工具接入原生发布；工具栏新增紧凑的“位姿”按钮，拖动设置初始位置与朝向。
- 发布中阻止同话题重复提交；成功提示“已提交到 ROS”。前端省略时间戳时由后端填写 ROS 时钟，兼容模拟时间。
- 自动重连和手动重连恢复订阅及 QoS；旧连接迟到的响应不能完成新连接的请求。握手与心跳超时会关闭失效连接。
- 断线释放会话的订阅、发布者和待提交命令；各客户端独立管理资源。

## 发布协议与确认

新增 `topics.advertise`、`topics.unadvertise`、`topics.publish`。发布可以自动创建发布者，参数为 `topic`、`type`、`msg`；消息类型采用 `geometry_msgs/msg/...` 格式，两种 ROS 一致。

成功响应示例：

```json
{"version":2,"id":"goal-1","ok":true,"result":{"topic":"/goal_pose","status":"submitted","execution":"unknown"}}
```

`submitted` 只确认本地 ROS 发布调用已完成，不确认机器人接收或执行。连接中断或响应超时后，前端报告结果未知，**不会自动重发**。ROS 1 发布者不锁存；ROS 2 使用 reliable / volatile / depth 1。

目标与初始位姿首次发布最多异步等待 1.5 秒发现订阅者；等待期间网络事件循环仍可响应心跳。超时返回 `no_subscribers`，不提交命令。Twist 不等待发现，可先 advertise；没有订阅者时立即拒绝，避免延迟发送过期速度。

同一连接保留最近 256 条已受理发布请求的回执；重复 ID、相同内容返回原回执，不再发布；重复 ID、不同内容返回 `request_id_conflict`。这不是跨连接、永久的去重保证。前端重连仅恢复订阅，不恢复发布请求。

## 校验与资源边界

- 发布白名单：`ROS_PUBLISH_TOPIC_ALLOWLIST`，默认 `/goal_pose,/initialpose,/cmd_vel`，逗号分隔并支持通配符；自定义目标话题需加入白名单。
- 校验绝对话题名、有限数值、单位四元数、非空 frame、时间戳、36 项协方差及非负对角线。
- 每会话最多 16 个发布者、8 条待提交命令，同一话题最多 1 条待提交命令。
- unadvertise 取消该会话对应话题的待提交命令；断线取消所有尚未提交命令。已提交到 ROS 的命令不能撤回。
- `session.stats` 返回发布者数、待提交命令数与连接数，便于检查资源释放。

## 验收

所有控制测试均使用隔离 ROS 图和模拟订阅者，没有向真实机器人发布控制。

| 项目 | ROS 1 | ROS 2 |
| --- | --- | --- |
| 原生构建与 protocol / display / control 单测 | 通过 | 通过 |
| 目标、初始位姿、速度的实际消息字段与时间戳 | 通过 | 通过 |
| 白名单、非法参数、重复请求、非阻塞等待与取消 | 通过 | 通过 |
| 客户端隔离、断线取消、发布者资源释放 | 通过 | 通过 |
| 浏览器点击目标发布、拖动初始位姿 | 通过 | 通过 |
| 后端重启与手动重连后显示恢复，控制不重放 | 通过 | 通过 |

前端 23 个测试文件全部通过，ESLint 和生产构建通过。点云 / Odometry 与第二阶段显示协议另做回归。

测试源：

- `backend/tests/control_test.cpp`：消息校验单测。
- `backend/tests/control_fixture.cpp`：模拟接收器，JSONL 输出收到的消息及发布者数量。
- `backend/tests/control_smoke.py`：实际 ROS 发布、回执、取消与资源验收。
- `backend/tests/browser_control.cjs`：真实 Chromium UI、服务重启和手动重连。
- `frontend/tests/connectionRecovery.test.js`：丢失回执、迟到响应、订阅竞态、握手与心跳超时。

运行协议测试时，先在隔离 ROS_DOMAIN_ID（ROS 2）或独立 ROS_MASTER_URI（ROS 1）启动原生服务和 control_fixture，并设置发布白名单为 `/v3_test/*,/goal_pose,/initialpose`：

```bash
# 将 URL、middleware、日志及标志路径替换为隔离测试实例。
backend/management/.venv/bin/python backend/tests/control_smoke.py \
  --url ws://127.0.0.1:18412/ws/v2/ros --middleware ros2 \
  --capture /tmp/control-receiver.jsonl --late-flag /tmp/control-late
```

fixture 的第一个参数是 late-flag 路径，标准输出重定向到 capture 文件。浏览器测试还需要 display_fixture、代理到测试原生端口的 Vite preview，以及环境变量 `CONTROL_CAPTURE`、`NATIVE_BINARY`、`NATIVE_PORT`、`PLAYWRIGHT_MODULE` 和 `CHROMIUM_PATH`。浏览器脚本自行启动、停止和重启该原生进程。

浏览器截图：[ROS 1](validation/backend-v2-stage3-ros1.png)、[ROS 2](validation/backend-v2-stage3-ros2.png)。

## 尚未覆盖

ROS1 Master 故障恢复、真实跨机器网络、小时级稳定性，以及控制与极限点云负载混合时的延迟仍需后续验证。已有点云性能报告对应第一阶段基线，本阶段没有重跑全量性能基准。容器与发布包迁移留在第四阶段。
