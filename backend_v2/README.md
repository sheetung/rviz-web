# 原生 ROS 后端 v2 · 第四阶段（本地部署）

C++17 直接使用 roscpp / rclcpp，FastAPI 独立管理配置和视频。当前正式入口使用 v2，已补齐显示、控制发布和连接恢复；v1 仅保留代码。

## 已实现

- ROS 1 / ROS 2 分别构建，健康检查、能力发现、话题发现、订阅与退订。
- `sensor_msgs/msg/PointCloud2`：复用 RVPC 二进制封装，保留字段、原始字节、行填充、帧名和时间戳。
- `nav_msgs/msg/Odometry`：JSON，包含 pose、twist、协方差。
- 请求 ID、成功/失败确认、心跳、客户端订阅隔离；断线后由前端恢复订阅。
- 控制响应与数据使用独立有界队列。数据队列按话题保留最新帧；退订清除待发送数据。
- TF / 静态 TF、LaserScan、Path、Marker / MarkerArray、OccupancyGrid；复用现有 Three.js 显示。
- ROS2 使用 C++ introspection 动态解码已安装工作空间消息，ROS1 使用 ShapeShifter 与发布者消息定义动态解码；数值曲线支持嵌套字段和数组统计。
- `/tf_static` 常驻订阅并合并多个发布者的边；客户端重连可恢复快照。Marker 发送独立显示快照，保留原始消息字段用于曲线。
- 原生发布目标、初始位姿与 Twist，发布白名单、消息校验、会话内回执去重；确认仅表示提交到 ROS。
- 前端固定使用 v2；断线与手动重连恢复订阅，控制命令不重放，配置与视频继续使用管理服务。

网络使用 Boost.Beast，JSON 使用 JsonCpp。ROS 适配器和网络协议分离；每个进程只加载一种 ROS。

## 构建

需要 Linux、C++17 编译器、CMake、Boost（含 system）、JsonCpp，以及对应 ROS 的 C++ 客户端、sensor_msgs / nav_msgs / geometry_msgs / tf2_msgs / visualization_msgs。ROS1 额外需要 topic_tools；ROS2 需要 rosidl_typesupport_introspection_cpp。

Ubuntu 通用依赖：

```bash
sudo apt install build-essential cmake libboost-system-dev libjsoncpp-dev
```

在仓库根目录，选择一种 ROS 环境后构建（不要在同一个终端混合 source 两种 ROS）：

```bash
source /opt/ros/humble/setup.bash # ROS 2；ROS 1 可用 /opt/ros/noetic/setup.bash
backend_v2/scripts/build.sh
```

产物：`backend_v2/build/ros1/rvizweb_native` 或 `backend_v2/build/ros2/rvizweb_native`。
自定义 ROS 消息工作空间可在基础 ROS 环境之后 source。ROS2 自定义类型需要该工作空间提供的 C++ introspection 和序列化类型支持库；ROS1 可直接读取发布者提供的消息定义。

只编译协议测试，不依赖 ROS：

```bash
cmake -S backend_v2 -B /tmp/rviz-v2-protocol -DRVIZWEB_WITH_ROS=OFF
cmake --build /tmp/rviz-v2-protocol
ctest --test-dir /tmp/rviz-v2-protocol --output-on-failure
```

## 一键启动

安装和启动仅编译 `.env` 选中的 ROS 版本：`ROS_WS_URL=/ws/ros2` 只构建 ROS 2，`/ws/ros1` 只构建 ROS 1。只需安装所选版本的依赖，不要求同时安装两套 ROS。

运行 `./start.sh`（或 `./start.sh dev`）。日常启动只增量构建所选 ROS 的主程序；未修改源码时复用现有产物，ROS 构建环境变化时重新配置，不运行测试。直接运行 `backend_v2/scripts/build.sh` 或 `./start.sh sync` 仍执行完整构建与测试。脚本同时启动 FastAPI 管理服务和前端；退出时统一清理。需要先安装下述构建依赖。原生端口由 `RVIZWEB_NATIVE_PORT` 控制，默认 8082，管理端口默认 8000。


## 开发启动

先按主项目说明准备 `backend/.venv` 和前端依赖。三个终端分别运行：

```bash
# 1. 已 source 对应 ROS 环境；ROS 1 需要可访问的 ROS Master
backend_v2/build/ros2/rvizweb_native --host 127.0.0.1 --port 8082

# 2. FastAPI 管理服务；无需 source ROS
backend_v2/scripts/start-management.sh

# 3. Vue 开发入口
cd frontend
npm run dev
```

也可使用 `backend_v2/scripts/start-native.sh`，它复用根目录 `.env` 和 ROS 环境选择逻辑；请确保其中 `ROS_WS_URL` 指向所需 ROS 版本且已构建相应产物。

前端固定连接 v2，不再提供 v1 配置或 URL 切换。

可选设置：

| 配置 | 默认 | 用途 |
| --- | --- | --- |
| `ROS_V2_PROXY_TARGET` | `http://127.0.0.1:8082` | Vite 转发到原生服务 |
| `RVIZWEB_MANAGEMENT_PORT` | `8000` | 管理服务端口及 Vite 管理接口代理 |
| `VITE_ROS_V2_WS_URL` | `/ws/v2/ros` | 浏览器 v2 WebSocket 地址 |
| `ROS_SUBSCRIBE_TOPIC_ALLOWLIST` | `*` | 原生进程订阅权限；逗号分隔 glob，空值拒绝全部 |

直接运行二进制时，需要自行 export 配置；`start-native.sh` 会加载 `.env`。
原生服务默认仅监听本机。独立浏览器来源可显式添加 `--allow-origin http://host:port`。

本地启动自动配置 Vite 代理。`/ws/v2/ros` 与 `/api/v2/ros/*` 直接转发 C++，配置/视频仍转发 FastAPI。保留浏览器 Host 和 Origin；跨源访问需使用确切的来源配置。Docker 部署暂时搁置，不提供 Docker 部署方法。

## 协议

HTTP GET：

- `/api/v2/ros/health`：ROS 就绪状态和能力。
- `/api/v2/ros/capabilities`：协议版本、消息类型、限制和只读标志。
- `/api/v2/ros/topics`：`{"topics":[...]}`，包含 `supported` 标志。

WebSocket `/ws/v2/ros` 首条应用消息是 `{"version":2,"event":"hello","capabilities":{...}}`。

```json
{"version":2,"id":"subscribe-1","method":"topics.subscribe","params":{"topic":"/points","type":"sensor_msgs/msg/PointCloud2","reliability":"best_effort"}}
```

```json
{"version":2,"id":"subscribe-1","ok":true,"result":{"topic":"/points"}}
```

方法：`ping`、`capabilities`、`topics.list`、`topics.subscribe`、`topics.unsubscribe`、`session.stats`。退订 params 仅需 topic。失败返回同一 id、`ok:false` 和 `error.code/message`。

Odometry 数据为 `{"version":2,"event":"topic.message","topic":"/odom","type":"nav_msgs/msg/Odometry","msg":{...}}`。PointCloud2 为 RVPC 二进制帧，元数据携带 `version:2`，兼容现有前端解码器。

订阅类型统一采用 `package/msg/Type`。`reliability` 默认 `auto`，ROS2 可选 `best_effort` / `reliable`；`durability` 默认 `auto`，ROS2 可选 `volatile` / `transient_local`。auto 在订阅建立时查看当前发布者：全部持久时选择持久订阅；只有发布者全部可靠时才请求 reliable，否则保持 best_effort。普通非持久采样使用 best_effort / volatile。若发布者尚未被发现而需要历史数据，可明确指定 QoS 后重新订阅。

`/tf_static` 固定采用 reliable / transient_local、depth 100，并常驻缓存；不能请求 volatile。普通消息队列深度 1，TF / Marker 深度 100。ROS1 保留发布者 latching 语义，不接受 DDS reliability / durability 选项。

限制：单帧 16 MiB、单请求 64 KiB、每连接 32 个订阅、每秒 60 个请求、服务最多 16 个连接。控制队列最多 32 条 / 1 MiB，数据队列最多 8 个话题 / 32 MiB，另有一条正在发送的帧。发送超过 2 秒或控制队列满时关闭连接；`session.stats` 提供队列统计。

## 验证与测试数据

已在 Ubuntu 22.04 上验证 ROS 2 Humble 和 ROS 1 roscpp 1.15.14（Ubuntu ROS 包，独立 Master）。ROS 1 官方 Noetic 完整部署镜像仍需目标环境复验。

两种 ROS 的实际发布/订阅检查覆盖：话题发现、点云精确字节及额外 intensity 字段、行填充、时间戳、里程计值、确认响应、退订、重连、双客户端隔离和来源拒绝。协议单元测试覆盖队列替换、控制优先级、容量限制、退订竞态标志及二进制封装。

两种 ROS 均通过 Chromium 页面联调：实际显示两个测试点，位姿面板显示 `(1.250, -2.500, 3.000)`，无页面错误。管理服务回归为 129 项测试及 26 项子测试通过；前端 22 个测试文件、lint 和生产构建通过。

复现时在隔离 ROS 环境中，分别运行原生服务、`backend_v2/build/ros2/ros_fixture` 和：

```bash
backend/.venv/bin/python backend_v2/tests/smoke.py \
  --url ws://127.0.0.1:8082/ws/v2/ros --middleware ros2
```

ROS 1 改用 ros1 产物与 `--middleware ros1`。ROS 2 可用独立 `ROS_DOMAIN_ID` 和 `ROS_LOCALHOST_ONLY=1`；ROS 1 使用独立 Master。测试发布器仅向 `/v2_test/points`、`/v2_test/odom` 发布固定数据。浏览器添加前者为 PointCloud2、Odom Topic 选择后者，Fixed Frame 设为 `map`；应显示两个点，位姿为 `(1.250, -2.500, 3.000)`。

白名单验证：服务设置 `ROS_SUBSCRIBE_TOPIC_ALLOWLIST='/v2_test/*,/tf'`，smoke 命令追加 `--denied-topic /forbidden`；两种 ROS 均已验证拒绝订阅且不创建订阅资源。

## 第二阶段验证与边界

详见 [第二阶段验收记录](../docs/backend-v2-stage2.md)，含两套 ROS 的实时发布器、消息验证、浏览器测试及自定义消息测试说明。

第三阶段已实现目标/初始位姿/Twist 发布、本地提交确认与连接恢复，详见 [第三阶段验收记录](../docs/backend-v2-stage3.md)。第四阶段的本地部署、源码发布包与回退见 [部署说明](../docs/backend-v2-stage4.md)；Docker 已搁置。图像等动态消息可读取字段，但本阶段未增加专用图像二进制协议。OccupancyGrid 当前为标准 JSON 数组，点云仍为 RVPC。

动态消息限制：单条序列化输入 / 输出最多 16 MiB、最多 100 万字段值、嵌套深度 32；ROS1 消息定义最多 1 MiB。非有限浮点数传为 null。Marker 缓存每订阅最多 2048 项 / 8 MiB，TF 最多 1024 个子坐标系 / 8 MiB。达到转换限制的消息跳过并记录服务日志；尚无前端转换错误通知。

当前每个客户端独立创建普通 ROS 订阅；仅 `/tf_static` 共享常驻订阅。ROS1 话题发现仍同步访问 Master。ROS2 本机地图性能、压力及停读客户端测试见 [性能报告](../docs/ros2-v1-v2-map-benchmark.md)。第二阶段没有重跑完整极限基准，真实网络、ROS1 性能和小时级稳定性仍未验证。
