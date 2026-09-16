> 历史记录：旧 Python ROS 后端、旧验证入口及 Docker 文件已从当前源码移除。历史实现见 Git；当前目录与命令以 [原生后端说明](../backend/README.md) 为准。

# ROS1 适配实施方案

状态：核心适配已实现，2026-09-15。下文保留设计与验收要求；实际部署步骤、已执行测试及未验证边界见 [ROS1 测试指南](ros1-testing.md)。

已选择 Ubuntu 22.04 原生 ROS1 1.15 + Python 3.10 的运行路线，未采用跨 Python worker。适配器、版本路由、环境选择和部署文件已落地；Docker 构建、目标局域网及长时间测试仍待验证。

## 1. 目标与边界

- 首个目标为 ROS1 Noetic；不承诺 Python 2 / Melodic 等旧环境。
- 一个后端实例只接入一个 ROS 版本，不在进程内混用 rospy 与 rclpy。
- 前端通过后端地址选择数据源，不新增用户填写的 `ROS_VERSION` 开关。
- 保持现有浏览器协议、二进制 PointCloud2、权限和背压机制。
- 地图配准、累积、SLAM、地图存储不属于 ROS1 适配器。已有地图脚本仍是测试工具。
- 不做 ROS1↔ROS2 桥接、不做同一页面多源融合、不增加旧配置名兼容层。

当前已有 `RosAdapter` 契约、`RosApplication` 和 `RosGateway`；
`dependencies.py` 仍固定创建 `Ros2Adapter`，`main.py` 仅注册 `/ws`。
类型名称可以规范化，不代表 ROS1 消息结构已经适配。

## 2. 配置与启动选择

以下是实施后的目标示例，当前不能直接使用：

```dotenv
# 按顺序加载 ROS 安装及工作空间环境；不能混合 ROS1 / ROS2
ROS_SETUP_PATHS="/opt/ros/noetic/setup.bash"

# ROS1 网络配置
ROS_MASTER_URI=http://192.168.1.10:11311
ROS_IP=192.168.1.100

# 默认使用应用同源 /ws；也可选择明确版本的 RVizWeb 后端入口
ROS_WS_URL=
```

ROS2 示例使用 `ROS_SETUP_PATHS="/opt/ros/humble/setup.bash"` 与 `ROS_DOMAIN_ID=0`。
ROS1 网络参数仅用于 ROS1；ROS2 Domain 参数仅用于 ROS2。
`ROS_IP` 是运行 ROS1 节点所在机器可被对端访问的地址，不是浏览器地址。
ROS1 节点之间还需双向网络可达，不能把开放 Master 的 11311 端口当作网络配置完成。

启动流程：

1. `.env` 继续非执行解析，直接将 `ROS2_SETUP_PATHS` 更名为 `ROS_SETUP_PATHS`。
   同步示例、用户 `.env`、测试和文档；不读取旧名或静默回退。
2. 在受控子进程环境按顺序 source setup，检查每个文件存在、加载成功。
   防止继承另一套 ROS 的路径、PYTHONPATH、动态库和 ROS_DISTRO 污染。
3. 使用 setup 导出的 `ROS_VERSION`（1 或 2）选择适配器，**不允许 `.env` 手填该值**。
   逐个检查 overlay 与已选版本一致；不能只看最后一次 source 的值。
4. 缺失/混合环境、未知版本、选定解释器无法导入对应 ROS 包时明确报错。
   不默认猜 ROS2，不自动切换版本，不在收到 WS 请求时重新 source 环境。
5. 直接启动后端也必须执行等价校验；健康信息报告实际 middleware、就绪状态和原因。
   不返回网络密码等敏感配置。

`ROS_WS_URL` 是浏览器连接目标，不是本地后端监听配置。
当前 `start.sh` 会从它推导本地后端端口、绑定行为；实施时需解除此耦合，
内部监听沿用明确的本地部署默认值，不能因填写远端地址自动暴露本地监听。
前端构建目前会注入该变量，变更后需重建；首阶段不增加运行时版本切换 UI。

## 3. URL、HTTP 与版本校验

| 请求路径 | ROS1 实例 | ROS2 实例 |
| --- | --- | --- |
| `/ws` | 连接 ROS1 | 连接 ROS2 |
| `/ws/ros1` | 连接 ROS1 | 拒绝版本不匹配 |
| `/ws/ros2` | 拒绝版本不匹配 | 连接 ROS2 |
| 其他版本路径 | 拒绝 | 拒绝 |

路径只选择/校验后端，不动态改变实例版本。版本路径与默认路径共享 Gateway，
Origin 校验、权限、限流和清理行为一致；不是任意 rosbridge_server 地址。
连接时返回实际 middleware 和协议版本；错误版本以固定机器可读错误码
`middleware_mismatch` 告知并关闭（计划使用 WS 1008，不建立 ROS 订阅），
前端停止对此错误的无限重连。Origin 不合法仍在握手前拒绝，不为错误提示绕过安全检查。

**WS 与 ROS HTTP 查询必须选择同一个实例。** 当前 API URL 与 WS URL 分别配置，
仅增加两个 WS 路由会造成节点、话题列表和发布请求与 WS 数据源不一致。
目标由一个连接地址解析器给出整套端点，保留代理路径前缀：

| 外部 WS 入口 | 对应 ROS API 入口 |
| --- | --- |
| `ws(s)://host[:port]/ws` | `http(s)://host[:port]/api/v1/…` |
| `ws(s)://host[:port]/ws/ros1` | `http(s)://host[:port]/ros1/api/v1/…` |
| `ws(s)://host[:port]/ws/ros2` | `http(s)://host[:port]/ros2/api/v1/…` |

版本前缀 HTTP 路由同样校验实例版本；实现时复用现有路由，不复制业务代码。
默认 `/ws` 和 `/api/v1` 仍属同一实例；双实例代理的默认入口由部署明确指定。
配置存储、RTSP 等非 ROS API 也需明确实例归属，首阶段统一随选定后端，避免串会话。
现有 `VITE_BACKEND_PUBLIC_URL` 若与选定连接冲突应报错，不能静默读取另一实例；
在迁移步骤中消除重复配置来源，不增加另一套 ROS 版本开关。

同一 IP/端口需要两个版本时，以反向代理分流至两个独立实例：

```text
/ws/ros1       + /ros1/api/v1/* → ROS1 实例
/ws/ros2       + /ros2/api/v1/* → ROS2 实例
/ws           + /api/v1/*      → 部署指定的默认实例
```

Nginx、Vite dev/preview 的重写和 WebSocket Upgrade 均纳入测试。
URL 的 ws/wss、端口、子路径必须成套处理；HTTPS 页面不连接不安全的 ws。
切换数据源时清理旧 TF、话题目录、待处理帧和订阅，防止同名话题跨源污染。

## 4. 先验证运行环境，不直接假设 Noetic 可用

当前后端 `pyproject.toml` 要求 Python >=3.10,<3.13。
Noetic 官方目标平台为 Ubuntu 20.04、Python 3.8，支持周期列到 2025 年 5 月。
因此只改 setup 路径不构成兼容方案，旧 ROS 部署需承担维护与安全风险。
依据：[ROS REP-3](https://github.com/ros-infrastructure/rep/blob/master/rep-0003.rst#noetic-ninjemys-may-2020---may-2025)。

阶段 0 必须验证当前后端解释器、rospy、rosgraph、roslib、标准及自定义生成消息的
导入、序列化、TCPROS 收发和 TF。先评估独立 ROS1 镜像中的同进程适配方案，
给出可复现的依赖与构建方式；不通过随意修改系统 Python 或全局降级 FastAPI 解决。

若同进程方案不能可靠复现，形成单独决策说明，再采用 ROS1 worker 隔离方案：
现代 Python Web 后端 ↔ 本地有界二进制 IPC ↔ Noetic/rospy worker。
IPC 的关联 ID、所有者释放、背压、超时和重启恢复必须独立验收。
这不是默认同时实现两套方案；阶段 0 选定一种后再继续，不能静默扩展架构。
隔离模式下 setup 只作用于 worker，不把其 Python 路径灌入 Web 进程。

## 5. 后端实现边界

目标目录 `backend/management/app/services/ros1/`：

- `adapter.py`：实现现有 RosAdapter 契约，管理节点、订阅与发布资源。
- `message_types.py`：ROS1 名称解析、生成类加载；内部仍用 `package/msg/Type`。
- `message_converter.py`：ROS1 消息与公共 payload 双向转换。
- 图查询/频率统计模块按需要独立；公共层不能导入 rospy、rclpy 或 ROS 消息包。

复用 `RosApplication` 的会话所有权、发布白名单及 ConnectionManager 背压。
ROS1 回调在 ROS 线程中执行：通过线程安全入口投递 asyncio，不能直接访问
WebSocket，也不能对每个高频回调无界提交 task/future。
可替换点云在昂贵转换前合并为最新帧，控制请求保持顺序；转换后重检订阅代次，
取消/重订阅的旧回调不进入新会话。阻塞图查询离开事件循环并设置超时。

启动只初始化一次 ROS1 节点，信号管理归应用生命周期；关闭时禁止新回调，
取消订阅、释放 publisher、清理待处理消息并结束节点。异常恢复不依赖在同进程
重复 init_node；Master 断开后报告未就绪，按明确的重连或进程重启策略恢复。

## 6. 消息与语义验收范围

- 首批：PointCloud2、Image/CompressedImage、Odometry、PoseStamped、Path、
  Marker/MarkerArray、TFMessage；发布覆盖 PoseStamped、PoseWithCovarianceStamped、Twist。
- 精确转换 ROS1 secs/nsecs 与规范时间表示、Header.seq、嵌套消息、数组、字节和整数范围；
  发布反向转换须做字段/类型校验，不能只改消息类型字符串。
- PointCloud2 保持端序、offset、point_step、row_step 和行填充正确；沿用二进制链路，
  不先 Base64/JSON 放大数据。无效字段或超大消息要可诊断。
- 自定义消息必须在选定运行环境可解析；不支持时显式失败，不尝试假装 ROS2 结构兼容。
- `/tf_static` 和 latched 话题：验证首次订阅、共享订阅新增客户端、断线恢复都能获得
  保留状态。静态 TF 按坐标边合并，不能仅缓存最后一个 TFMessage 丢失其他发布者的边。
- 不把 ROS1 latch 等同于完整 DDS QoS；不支持能力用 capability/明确状态表示。
- 第一阶段只实现当前契约的图查询/发布订阅，不顺带扩展 service 调用、action 或参数写入。

## 7. 分阶段交付与验收

| 阶段 | 交付 | 通过条件 |
| --- | --- | --- |
| 0 运行环境 | ROS1 最小收发原型、解释器与依赖矩阵 | 真 ROS1 节点双向通信；选定同进程或隔离模式 |
| 1 配置与入口 | setup 更名、适配器工厂、版本 WS/HTTP 路由、代理 | 缺失/混用环境报错；错版本拒绝；API 与 WS 不串源 |
| 2 ROS1 核心 | 图发现、订阅发布、消息转换、资源清理 | 契约测试、标准/自定义消息与权限测试通过 |
| 3 显示与恢复 | 点云、Odom、TF 跟踪、latched 状态 | 浏览器实测，重连不缺静态 TF，不残留旧帧 |
| 4 性能与部署 | ROS1 原始 bag 压测、隔离镜像/Compose、说明 | 慢客户端不拖累正常客户端；ROS2 基线不退化 |

性能复用 ROS2 测试条件：1/多客户端、8 正常+2 停读、原速/加速回放，记录吞吐、
ping/pong P50/P95/P99、排队长度、RSS、取消订阅和关闭耗时，另测浏览器帧龄与跟踪。
同数据比较须说明转换和时间基准差异；不拿离线建图耗时当 Web 延迟。
流畅度优先，但不能用无限队列消耗内存来伪装完整收帧。

ROS1 验证使用原始 `.bag` + ROS1 播放器/发布节点；现有转换后的 ROS2 bag 验证
不算 ROS1 测试。每阶段保留 ROS2 契约回归、实际收发及测试报告。

## 8. 预计修改清单与完成定义

- 配置：`.env.example`、用户 `.env`、`backend/management/app/core/config.py`。
- 启动：`start.sh`、`docker/start-container.sh`，选定方案对应 Dockerfile/Compose。
- 后端：`services/dependencies.py`、新增 `services/ros1/`、`main.py` 与路由复用；
  仅有必要时扩展公共 capability/保留状态契约，不将 ROS1 特例散落到业务层。
- 前端：连接 URL/API 解析、连接元信息、版本错误提示、数据源缓存清理。
- 代理：`frontend/vite.config.js`、`docker/nginx.conf`。
- 测试与文档：启动/工厂/转换/并发/路由/前端单测，真实 ROS1 与 ROS2 报告，
  README、PROJECT_GUIDE、PROJECT_STATUS、CHANGELOG。

完成必须同时满足：真实 ROS1 收发与可视化通过，ROS2 回归通过，部署可复现，
`.env`/代理/文档一致，旧 `ROS2_SETUP_PATHS` 已移除，新能力未以“仅文档”冒充实现。
本方案阶段不改用户配置、不安装 ROS1、不提交或推送 Git。
