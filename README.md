<div align="center">

# RVizWeb

**面向 ROS 的浏览器可视化工作台**

在一个页面中查看三维点云、机器人位姿、实时曲线与视频，管理话题和任务配置。

后端 v2 原生 C++ 已补齐控制与恢复，并提供第四阶段本地部署和源码包，支持 ROS 1 / ROS 2 的点云、里程计、TF、激光、路径、Marker、栅格和动态数值曲线，以及目标/初始位姿发布和断线恢复。见 [构建与启动说明](./backend_v2/README.md)；本地 `./start.sh` 固定启动 v2，v1 仅保留代码；Docker 部署暂时搁置，仅支持本地启动。已完成 [ROS 2 地图性能与极限测试](./docs/ros2-v1-v2-map-benchmark.md)。

[中文](./README.md) | [English](./readme/README.en.md)

[![GitHub Stars](https://img.shields.io/github/stars/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/forks)
[![GitHub Issues](https://img.shields.io/github/issues/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/issues)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue?style=flat-square)](./LICENSE)

![ROS](https://img.shields.io/badge/ROS-22314E?style=flat-square)
![Vue 3](https://img.shields.io/badge/Vue-3-42B883?style=flat-square)
![Three.js](https://img.shields.io/badge/Three.js-WebGL-222222?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?style=flat-square)

[快速开始](#快速开始) · [功能特性](#功能特性) · [使用指南](./docs/usage.md) · [问题反馈](https://github.com/sheetung/rviz-web/issues)

<img src="./img/1.png" alt="RVizWeb 实机界面：三维点云、无人机位姿、Displays、视频浮窗与实时数据曲线" width="100%">

*三维场景、话题管理和实时数据在同一工作台中呈现。*

</div>

## 项目介绍

RVizWeb 是面向 ROS 的 Web 可视化工具，适用于机器人调试、无人机状态监控和算法演示。后端接入 ROS 网络，前端通过浏览器展示数据，查看端无需安装桌面可视化客户端。

项目采用 **Vue 3 + Three.js** 构建交互界面与三维场景，使用 **C++ roscpp / rclcpp** 接入 ROS1 / ROS2，**FastAPI** 管理配置与视频，通过 WebSocket 传输实时数据。交互沿用 RViz 风格的 Displays、Fixed Frame 和相机工具，并支持保存不同机器人与任务的 `.rvizweb` 配置。

> 已支持 ROS1 和 ROS2，每个后端实例固定运行一种 ROS 环境，不是 ROS1/ROS2 消息桥。自定义消息需安装并加载对应工作空间；ROS1 部署与验证边界见 [ROS1 指南](./docs/ros1-testing.md)。

## 目录

- [功能特性](#功能特性)
- [界面预览](#界面预览)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [项目结构](#项目结构)
- [开发与贡献](#开发与贡献)
- [文档与计划](#文档与计划)
- [交流与反馈](#交流与反馈)
- [致谢](#致谢)
- [许可证](#许可证)

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 三维可视化 | 显示点云、激光扫描、里程计、路径、Marker 与栅格地图；支持 TF 坐标变换 |
| Displays 管理 | 从 ROS 图发现话题，按话题或类型添加显示项，独立控制显隐与样式 |
| 点云与路径 | 点云支持 Points / Boxes、大小设置与稀疏显示；路径支持线宽和颜色设置 |
| 位姿与目标 | 展示无人机位姿与轨迹，预览目标点并按需发布 `PoseStamped` |
| 相机与交互 | Orbit 操作、选择、聚焦、视角预设、2D 位姿估计与 2D 目标工具 |
| 实时曲线 | 选择话题数值字段，叠加多条曲线，缩放时间窗口、暂停查看和回到实时 |
| 视频与记录 | RTSP 视频浮窗、PNG 截图与 WebM 三维画布录像 |
| 配置与布局 | 保存 Displays、坐标系、相机、布局与主题；支持配置校验、迁移与备份 |

### 支持的主要显示消息

| 消息类型（统一前端格式） | 用途 |
| --- | --- |
| `sensor_msgs/msg/PointCloud2` | 点云与体素显示 |
| `sensor_msgs/msg/LaserScan` | 激光扫描 |
| `nav_msgs/msg/Odometry` | 里程计与机器人位姿 |
| `nav_msgs/msg/Path` | 规划路径与轨迹 |
| `visualization_msgs/msg/Marker` | 单个可视化标记 |
| `visualization_msgs/msg/MarkerArray` | 多个可视化标记 |
| `nav_msgs/msg/OccupancyGrid` | 栅格地图 |

ROS1 原生 `package/Type` 由适配器转换为上述统一格式。自动订阅 `/tf` 与 `/tf_static`，将数据转换到选定的 Fixed Frame。找不到 TF 链时，对应 Display 会显示原因并隐藏无法正确定位的数据。地图文件设置入口目前暂时隐藏，OccupancyGrid 底层显示能力仍保留。

## 界面预览

<details>
<summary>展开查看另一张实机截图</summary>

![RVizWeb 界面预览](./img/2.png)

</details>

## 快速开始

ROS1 已提供独立适配器与部署配置，参见 [ROS1 部署与测试](docs/ros1-testing.md)。下面的默认示例使用 ROS2 Humble。每个后端实例只运行一种 ROS 环境，按 `ROS_WS_URL` 的版本后缀选择 `ROS1_SETUP_PATHS` 或 `ROS2_SETUP_PATHS`；这两个旧路径仅作为启动时的 ROS 版本选择值，网页数据统一走 `/ws/v2/ros`。

### 本地运行

安装和启动仅编译 `.env` 选中的 ROS 版本：`ROS_WS_URL=/ws/ros2` 只构建 ROS 2，`/ws/ros1` 只构建 ROS 1。只需安装所选版本的依赖，不要求同时安装两套 ROS。

下面以 ROS2 为例；ROS1 配置见随后说明。

| 依赖 | 要求 |
| --- | --- |
| ROS 2 | 已安装并能发现目标话题；默认 setup 路径为 `/opt/ros/humble/setup.bash` |
| Node.js / npm | 精确版本见 `.node-version` / `.npm-version`；安装脚本自动检查并安装到项目缓存 |
| Python | 3.10–3.12，仅用于管理服务，不要求导入 rospy/rclpy |
| C++ 构建依赖 | C++17、CMake、Boost.System、JsonCpp 和所选 ROS 的开发包，见 [原生依赖](backend_v2/README.md#构建) |
| uv | Python 环境管理；未安装时脚本会通过 curl 调用官方安装脚本 |
| FFmpeg | 用于 RTSP 转流；同步依赖时脚本会检查，缺失时尝试通过系统包管理器安装 |

```bash
git clone https://github.com/sheetung/rviz-web.git
cd rviz-web
cp .env.example .env
```

编辑 `.env`，设置 ROS 2 环境路径和与机器人一致的通信域：

```dotenv
ROS_WS_URL=/ws/ros2
ROS1_SETUP_PATHS="/opt/ros/noetic/setup.bash"
ROS2_SETUP_PATHS="/opt/ros/humble/setup.bash"
ROS_DOMAIN_ID=0
APP_HOST=127.0.0.1
APP_PORT=3000
```

如果使用自定义消息，将工作空间的 `install/setup.bash` 追加到 `ROS2_SETUP_PATHS`，多个路径以空格分隔。需要局域网访问时，将 `APP_HOST` 改为 `0.0.0.0`。

```bash
# 首次安装或依赖变化后执行；系统依赖安装可能需要 sudo
./start.sh sync

# 构建前端并启动服务
./start.sh local
```

浏览器打开 **http://localhost:3000/**；其他设备使用运行机器的局域网 IP。按 `Ctrl+C` 停止服务。

原生 ROS1 部署将 `.env` 改为以下配置，使用相同启动命令：

```dotenv
ROS_WS_URL=/ws/ros1
ROS1_SETUP_PATHS="/opt/ros/noetic/setup.bash"
ROS_MASTER_URI=http://192.168.1.10:11311
ROS_IP=192.168.1.100
APP_HOST=0.0.0.0
```

地址分别替换为 Master 和本机局域网 IP。C++ 后端使用对应 ROS 开发包；管理服务独立使用 Python 3.10–3.12，不要求与 ROS Python 版本一致。自动启动 ROS1 Master 和 Python 模拟数据脚本另需对应 Python ROS 依赖。

### Docker 状态

**Docker 部署暂时搁置，本版本仅支持本地部署，不提供 Docker 部署方法。** 仓库中的 Dockerfile / Compose 文件属于历史实现，尚未迁移到 v2，不能用于当前版本部署。

本地升级、源码发布包、配置兼容与回退步骤见 [第四阶段部署说明](docs/backend-v2-stage4.md)。

## 无人机雷达模拟

已有 local_data 测试数据时，运行 `./scripts/simulate-uav.sh` 可在真实点云地图中无限巡航，支持 /goal_pose 更新目标并实时生成雷达扫描、里程计和 TF。网页读取 `sim-uav-outdoor.rvizweb` 即可查看。[操作与参数说明](docs/uav-simulator.md)。

## 使用说明

1. **确认连接**：启动机器人或回放数据，确认后端环境执行 `ros2 topic list -t` 能看到目标话题。
2. **添加显示**：在 Displays 中选择 `Add`，按话题或显示类型添加数据源。
3. **设置坐标系**：在 `Global Options` 中选择 Fixed Frame，并按需要设置 odom 来源、无人机模型与轨迹。
4. **观察与交互**：调整点云样式、相机与曲线；目标点的“展示”用于预览，“发布”才会发送 ROS 消息。
5. **保存工作区**：在设置中保存 `.rvizweb`，下次恢复话题、视角、布局和主题。

### 常用命令

```bash
./start.sh                 # 默认本地模式
./start.sh dev             # 前端热更新开发模式
RVIZWEB_CONFIG=default.rvizweb ./start.sh local
```

默认配置位于 [`rvizweb_configs/default.rvizweb`](./rvizweb_configs/default.rvizweb)，只包含通用界面设置，不绑定具体机器人话题。为不同任务保存独立配置后，可用 `RVIZWEB_CONFIG` 指定已有文件。

### 配置与排障

- **话题不可见**：核对 `ROS_DOMAIN_ID` 和 `ROS2_SETUP_PATHS`，确认后端加载了正确的工作空间。
- **显示位置异常或没有对象**：检查 Fixed Frame 和 TF 链，并查看对应 Display 的状态信息。
- **RTSP 无法连接**：确认后端可运行 FFmpeg 并访问视频源。默认策略禁止私网等地址，受信任相机的访问策略需由维护者在 `backend/app/core/config.py` 中调整并重新部署。
- **更多说明**：参阅[完整使用指南](./docs/usage.md)，包含话题发现、配置字段、视频接口、日志、分离部署和常见问题。

## 项目结构

```text
rviz-web/
├── backend/             # FastAPI 配置与视频服务，保留 v1 代码
├── frontend/            # Vue 3、Three.js、Displays 与数据面板
├── docker/              # Nginx 与容器启动配置
├── docs/                # 使用指南与测试记录
├── img/                 # 项目截图
├── readme/              # README 多语言文档
├── rvizweb_configs/     # 可保存和复用的工作区配置
├── .env.example         # 环境变量示例
├── docker-compose.yml   # 历史文件，Docker 部署已搁置
├── install.sh           # 依赖安装与同步
├── start.sh             # 本地与开发启动入口
└── release.sh           # 前后端独立版本发布
```

## 开发与贡献

欢迎通过 [Issues](https://github.com/sheetung/rviz-web/issues) 报告问题或讨论功能，也欢迎提交 [Pull Request](https://github.com/sheetung/rviz-web/pulls) 改进代码与文档。

1. Fork 仓库并创建功能分支。
2. 使用 `./start.sh dev` 开发，保持 `.rvizweb` 配置兼容性。
3. 根据修改范围运行下列检查，补充必要的验证。
4. 提交 PR，说明问题、修改内容和验证结果；界面改动可附截图。

**前端检查**（在 `frontend/` 中执行）：

```bash
npm run lint:check
npm test
npm run build
```

**后端检查**（加载 ROS 2 环境后，在 `backend/` 中执行）：

```bash
uv run pytest -q
uv run flake8 app
uv run python -m compileall -q app
```

组件接入、系统消息、配置扩展和独立版本发布方式见[开发说明](./docs/usage.md#开发说明)与[验证及发布](./docs/usage.md#验证)。

## 文档与计划

| 文档 | 内容 |
| --- | --- |
| [使用与开发指南](./docs/usage.md) | 完整功能、配置、部署、排障与开发说明 |
| [English README](./readme/README.en.md) | 英文项目说明 |
| [更新日志](./CHANGELOG.md) | 版本变更记录 |
| [ROS 2 Bag 测试记录](./docs/ros2-bag-benchmark.md) | 数据回放测试与观测结果 |
| [ROS 2 / RTSP 测试记录](./docs/ros2-rtsp-benchmark.md) | 可视化与视频场景测试记录 |

后续计划：

- 完善 ROS1 / ROS2 实机网络及长时间多客户端验证；Docker 暂时搁置。
- 完善 TF 过去 / 未来外推错误状态与 Display 生命周期覆盖。
- 增加 WebSocket 重连和真实 ROS 2 图的自动化集成测试。
- 清理历史布局与示例组件，降低维护成本。

## 交流与反馈

- **问题与建议**：[GitHub Issues](https://github.com/sheetung/rviz-web/issues)，请附复现步骤、ROS1 / ROS2 发行版、运行方式及相关日志。
- **代码贡献**：[Pull Requests](https://github.com/sheetung/rviz-web/pulls)。
- **QQ 交流群**：965312424。

[![QQ Group](https://img.shields.io/badge/QQ群-965312424-green)](https://qm.qq.com/cgi-bin/qm/qr?k=en97YqjfYaLpebd9Nn8gbSvxVrGdIXy2&jump_from=webapi&authKey=41BmkEjbGeJ81jJNdv7Bf5EDlmW8EHZeH7/nktkXYdLGpZ3ISOS7Ur4MKWXC7xIx)

如果 RVizWeb 对你有帮助，欢迎点亮 Star，或 Fork 后参与改进。

## 致谢

感谢 **[lovelyyoshino/RVIZ-RQT-VISUAL](https://github.com/lovelyyoshino/RVIZ-RQT-VISUAL)** 提供项目基础与参考，原项目的版权声明保留在 [LICENSE](./LICENSE) 中。

也感谢本项目使用的开源工具与生态：ROS 2 / rclpy、Vue、Three.js、Element Plus、FastAPI、FFmpeg 与 uv，以及所有提交代码、报告问题和分享使用经验的贡献者。

## 许可证

本项目采用 **[BSD 3-Clause License](./LICENSE)**。完整许可条款与版权声明见 `LICENSE` 文件。
