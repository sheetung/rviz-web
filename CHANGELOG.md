# Changelog

本项目遵循语义化版本控制。前端和后端独立定版与发布；`v1.3.0` 及之前的条目为历史统一版本。

## [Unreleased]

### Added

- 室外累积地图回放新增雷达 Odometry 与 `map → mapping_lidar` TF，支持网页 Follow Frame 和位置轨迹展示，不修改原始地图消息。

- 完成 OutdoorRoad_cut0 室外累积地图生成：约 78.7 m 轨迹、311 个完整快照、约 31.5 万点；转换工具支持指定 GNSS 参考话题，补充室外回放说明。

- 新增逐扫描离线累积地图导出：按 GLIM 轨迹插值配准原始 Mid360 点云，约 5 Hz 输出完整地图快照，保留历史点，不依赖前端历史缓存。

- 新增独立 IndoorOffice1 GLIM CPU 建图与导出工具，生成 PLY、轨迹及累积地图 ROS2 回放包；不向后端引入 SLAM 依赖。
- 完成首轮 9 子地图、约 19 万点地图导出与原生 ROS2 读取验证，补充坐标变换、时间戳和体素去重测试及回放说明。

### Fixed

- ROS2 消息转换结束后校验订阅实例，丢弃已取消或属于旧订阅的帧，修复并发断订阅 KeyError。
- 本地、Docker 与程序入口显式使用 `websockets` 传输，避免默认 SansIO 发送缓冲积压绕过应用超时。
- ROS2 spin 不再阻塞 HTTP/WebSocket 事件循环等待 DDS 数据；正常 ROS context 关闭不再记录 fatal 异常。

### Changed

- 界面副标题由 `ROS2 Workbench` 改为 `ROS Workbench`，品牌展示不绑定 ROS 版本；实际中间件支持范围不变。

- 完成 ROS2 适配边界分离：新增 RosGateway、RosApplication，ROS2 代码集中到 services/ros2/，公共层不再直接加载 ROS 依赖。
- 会话所有权、系统状态和 WebSocket 转发归公共层；关闭时先释放 ROS 资源再移除连接状态，补充假适配器边界回归测试。

- 后端新增 `RosService` 应用契约，当前 rclpy 实现明确为 `Ros2Service`，FastAPI 路由不再直接依赖具体 ROS2 类。
- ROS 消息类型统一规范为 `package/msg/Type`，边界可接收并转换 ROS1 `package/Type`；消息转换器解除对完整 ROS 服务的反向依赖。
- 新增简洁的 Docker Compose 部署，使用 Linux host 网络接入 ROS2 DDS，并加入配置持久化、健康检查、自动重启和日志轮转。
- Docker 构建支持应用标题和启动配置名，Nginx 访问及错误日志统一输出到容器日志，并缩小构建上下文。
- 前端和后端改为独立版本，分别使用 `frontend-v*` 和 `backend-v*` Git 标签；移除根目录统一 `VERSION` 文件。
- 新增 `LOG_ENABLED` 启动日志开关，默认关闭；启用后每次启动创建一个按时间命名的目录，分别写入 `start.log`、`backend.log` 和 `frontend.log`，不覆盖历史日志。
- 本地部署统一使用 `APP_HOST` 和 `APP_PORT` 作为浏览器入口，API 与 WebSocket 默认通过同源代理访问；`ROS_WS_URL` 仅用于需要直连的分离部署。
- `.env.example` 只保留部署地址、ROS Domain、启动配置和 ROS 话题权限等用户参数。
- 缓存、限流、消息大小、点云转发、配置备份和 RTSP 转码等高级项改为代码内置的系统参数，不再接受 `.env` 覆盖。
- ROS 发布仍受 `ROS_PUBLISH_TOPIC_ALLOWLIST` 话题边界保护，但不再限制消息类型；当前 ROS2 环境可解析的消息类型均可使用。
- FFmpeg 可执行程序固定从 `PATH` 中查找 `ffmpeg`，前端控制台调试输出默认关闭且不再由环境变量开启。

### Removed

- 移除 `BACKEND_PORT`、`FRONTEND_PORT`、`FRONTEND_HOST`、`FRONTEND_PUBLIC_HOST` 和 `VITE_ROS_WS_URL` 等旧部署变量，不提供兼容迁移。
- 移除 `ROS_PUBLISH_TYPE_ALLOWLIST`、`VITE_DEBUG`、`FFMPEG_PATH` 以及 ROS、WebSocket、配置备份和 RTSP 的高级环境变量。

## [1.3.0] - 2026-07-25

### Added

- PointCloud2 Display 增加独立的稀疏显示选项，可配置每 2–32 个点保留 1 个点，并随 `.rvizweb` 保存。
- 增加 PointCloud2 二进制 WebSocket 帧、前端 Worker 解码和 GPU 高度着色材质。
- `.rvizweb` 读取时可自动迁移旧字段、清理废弃布局字段并在写回前备份；未知旧字段保存在 `extensions.legacy`。
- Global Options 增加 Odom、无人机模型、轨迹显示和轨迹长度设置。

### Changed

- PointCloud2 在后端紧凑为 XYZ 字段并保留全部点，高带宽 Topic 使用最新帧投递和可配置限频；浏览器只处理最新可用点云帧。
- 点云几何体、实例矩阵和材质改为复用更新，场景统计降低到每秒采样，减轻主线程和 GPU 压力。
- Displays 的 Global Options 与每个显示项可独立展开或收起；删除独立“3D控制”面板，位姿面板改为只读展示。
- 工具栏移除低频按钮，将配置视角重置归入视角预设，并将 `R` 改为刷新点云；坐标轴开关同时控制 XYZ 标签。
- 移动端话题选择不再弹出软键盘，图表 Dock 与右侧面板使用一致的拖拽反馈。
- 产品名称由 RViz2 Web 统一为 RVizWeb，README 中的 ROS2 支持范围保持不变。

### Fixed

- 对 Odom 驱动的无人机模型增加位置和姿态阻尼，降低高频位姿抖动。
- 修复全局轨迹开关和长度设置未作用于实际轨迹线，以及切换 Odom 后残留旧轨迹的问题。
- 修复点云刷新需要重建订阅、场景统计逐帧遍历，以及坐标轴关闭后 XYZ 标签仍显示的问题。
- 修复加载或保存旧配置时废弃 controller 布局字段继续传播的问题。

## [1.2.0] - 2026-07-22

### Added

- 增加 `VITE_ROS_WS_URL`，支持配置浏览器使用的完整 WebSocket 地址。
- 数据图表支持 PX4 等自定义 ROS 消息，并可从首条消息动态发现数值字段。
- 增加 WebSocket、Publisher 所有权、Marker 状态、自动重连和图表字段回归测试。

### Changed

- ROS 高频消息按 Topic 合并为最新帧，WebSocket 客户端使用相互隔离的有界发送队列。
- ROS 图查询增加短时缓存，消息转换和 JSON 序列化移出主事件循环。
- Marker 的 TF 刷新改为原位更新，避免重建对象和重置 lifetime。
- 前后端默认绑定回环地址；应用不再提供登录或配置写入 Token 鉴权，局域网和公网访问边界由防火墙、VPN 或可信反向代理负责。
- 重写 Docker 多阶段构建、Nginx 同源代理、启动脚本和依赖锁定流程。

### Fixed

- 修复 REST 并发发布共用 owner 时 Publisher 被提前销毁的问题。
- 修复 Marker 在 TF 延迟到达后无法恢复显示，以及 MarkerArray lifetime 被重复重置的问题。
- 修复后端短暂离线后前端可能永久停止自动重连的问题。
- 修复 PX4 消息中的 NaN/Infinity 导致浏览器拒绝整条 WebSocket JSON 消息的问题。
- 修复未测量 Topic 被误报为“无数据”，以及图表 Y 轴小范围刻度显示相同的问题。
- 调整 Odom 面板连接状态位置并移除重复的话题状态行。

## [1.1.5] - 2026-07-18

### Fixed

- 修复位姿控制器的话题发现结果可能覆盖 `.rvizweb` 中 odom 话题的异步初始化竞争。
- 修复 odom、激光、点云和地图切换话题后旧订阅未正确清理的问题。
- 修复加载空话题配置时遗留上一份配置状态，以及点云话题未恢复的问题。
- 修复 Displays 面板自行应用默认配置可能与启动配置异步加载竞争的问题。

## [1.1.1] - 2026-07-14

### Added

- 增加可配置 RTSP 视频连接入口，视频地址和窗口布局可随 `.rvizweb` 配置保存。
- WebSocket 协议增加系统状态查询，CPU、内存和温度复用前端现有实时连接。

### Changed

- WebSocket 地址跟随后端配置端口，避免修改 `BACKEND_PORT` 后仍连接前端端口。
- RTSP 输入框使用通用本机占位地址，不再包含部署设备地址。
- 前端系统消息统一使用同一通知服务、显示时长和去重规则。

### Fixed

- 修复统一通知服务后遗漏 Message 样式，导致读取话题等通知不可见的问题。
- 修复目标发布链路读取到过期 WebSocket 连接状态的问题。

## [1.1.0] - 2026-07-14

### Added

- PointCloud2 Display 支持按话题选择 `Points` 或 `Boxes` 渲染方式。
- `Points` 与 `Boxes` 分别提供独立的 `Point Size` 和 `Box Size` 配置，并随 `.rvizweb` 配置保存和恢复。
- `Boxes` 使用 `InstancedMesh` 批量渲染真实三维体素，并保留逐实例高度颜色映射。

### Changed

- 同一话题的点云样式调整直接作用于当前对象，不再反复退订和重新订阅。
- 体素颜色改为不受场景灯光衰减的原色显示，使视觉效果更接近 RViz。
- 点云聚焦支持实例化体素的完整边界框以及 Fixed Frame 变换。

### Fixed

- 修复 Boxes 实例颜色被缺失的普通顶点颜色通道压黑的问题。
- 修复坐标轴文字透明 Sprite 写入深度缓冲，导致视角变化时出现方形空白的问题。

## [1.0.2] - 2026-07-13

### Fixed

- 修复 WebSocket JSON 整数无法赋值给 ROS2 浮点字段，导致目标点、初始位姿、Pose 和 Twist 的整数坐标被静默保留为 0 的问题。
- 统一期望目标表单的数据源，确保配置默认值、展示值和发布值一致。
- 增加跨消息类型的整数转浮点回归测试。

## [1.0.1] - 修复前端打开时主题渲染错误
## [1.0.0] - 2026-07-12

### Added

- ROS2 话题发现、订阅、取消订阅和消息发布。
- PointCloud2、LaserScan、Odometry、Path、Marker 与 MarkerArray 三维显示。
- `/tf`、`/tf_static`、Fixed Frame、TF 历史插值和 Follow Frame。
- RViz 风格 Displays、2D 目标、相机工具、PNG 截图和 WebM 录像。
- `.rvizweb` 配置保存、读取、校验、原子写入和备份。
- uv 后端依赖管理、前后端健康检查及统一启动脚本。

### Fixed

- 修复隐藏 Display 被后续 TF 更新重新创建的问题。
- 修复目标发布读取旧 ROS 连接状态的问题。
- 修复点云、MarkerArray 与相机视角相关的显示和交互问题。
