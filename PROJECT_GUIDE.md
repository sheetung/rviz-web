# RVizWeb 项目指南

## 项目定位

RVizWeb 是一个面向 ROS2 的浏览器可视化工具。前端使用 Vue 3、Three.js 和 Element Plus，后端使用 FastAPI 与 rclpy。浏览器通过 FastAPI 的 `/ws` WebSocket 与后端通信，后端直接加入 ROS2 图，不依赖独立的 rosbridge_server。

当前工程以本地开发运行方式为主。用户操作说明与界面功能介绍见 `README.md`，本文档重点说明工程结构、配置、启动和维护方式。

## 当前架构

```text
浏览器
  ├── HTTP /api/v1/*  ── FastAPI ── 配置文件与 ROS2 查询接口
  └── WebSocket /ws  ── RosbridgeService ── rclpy ── ROS2 图
```

- 前端：Vue 3、Vite、Three.js、Element Plus、Pinia。
- 后端：Python 3.10–3.12、FastAPI、Uvicorn、rclpy。
- Python 依赖：由 `backend/pyproject.toml`、`backend/uv.lock` 和 uv 管理。
- 前端依赖：由 `frontend/package.json`、`frontend/package-lock.json` 和 npm 管理。
- 可视化配置：保存在 `rvizweb_configs/*.rvizweb`。

## 环境要求

- ROS2 环境，当前启动脚本默认尝试加载 ROS2 Humble。
- Python 3.10–3.12。
- Node.js 20.19 或更高版本（Vite 8 要求）。
- npm、curl、`ss`、`setsid`。
- uv；如果系统中没有，`start.sh` 会通过 uv 官方安装脚本安装。

启动脚本会按 `.env` 中的 `ROS2_SETUP_PATHS` 顺序加载，例如：

```text
/opt/ros/humble/setup.bash
<your_workspace>/install/setup.bash
```

如果实际工作空间位于其他位置，需要修改 `start.sh` 的 `load_ros` 函数，或在启动脚本前自行加载正确的 ROS2 环境。

## 环境配置

项目根目录的 `.env` 是当前设备的运行配置，`.env.example` 是参考模板。首次部署可复制模板后按实际网络环境调整。

主要变量：

| 变量 | 用途 |
| --- | --- |
| `ROS_DOMAIN_ID` | ROS2 DDS 通信域；未设置该变量的 ROS2 设备默认使用 `0` |
| `BACKEND_HOST` | FastAPI 绑定地址 |
| `BACKEND_PORT` | FastAPI HTTP 与 `/ws` WebSocket 共用端口 |
| `FRONTEND_PORT` | Vite 开发服务器端口 |
| `FRONTEND_HOST` | Vite 实际绑定地址，默认 `127.0.0.1` |
| `FRONTEND_PUBLIC_HOST` | 仅用于启动完成后显示访问地址 |
| `VITE_APP_TITLE` | 浏览器标签页和页面左上角显示的应用标题 |
| `VITE_ROS_WS_URL` | 浏览器连接 ROS 后端的完整 WebSocket 地址；留空使用同源 `/ws` |
| `CHOKIDAR_USEPOLLING` | 开发模式使用轮询代替 inotify；正常模式不读取该变量 |
| `CHOKIDAR_INTERVAL` | 开发模式的文件轮询间隔，单位为毫秒 |
| `CORS_ORIGINS` | 允许访问后端 API 的前端来源，使用英文逗号分隔 |
| `ROS_SUBSCRIBE_TOPIC_ALLOWLIST` | WebSocket 可订阅 Topic glob |
| `ROS_PUBLISH_TOPIC_ALLOWLIST` | HTTP/WebSocket 可发布 Topic glob |
| `ROS_PUBLISH_TYPE_ALLOWLIST` | 可发布 ROS 消息类型 |
| `ROS_POINTCLOUD_MAX_HZ` | PointCloud2 转发到浏览器的最高频率；`0` 表示不限频 |
| `ROS_POINTCLOUD_XYZ_ONLY` | 只转发当前点云渲染需要的 XYZ 字段，减少 Base64/JSON 体积 |
| `CONFIG_MAX_BYTES` | 单个 `.rvizweb` 文件的最大字节数 |
| `CONFIG_NAME_MAX_LENGTH` | 配置文件名最大长度 |
| `VITE_DEBUG` | 是否输出前端调试日志 |

ROS 话题名不应放在 `.env` 中。Displays、Fixed Frame、odom 话题、目标话题和样式等用户状态属于 `.rvizweb` 配置。

应用层不提供登录鉴权。局域网部署应通过绑定地址、防火墙或 VPN 限制访问范围，不能将后端、前端或反向代理端口直接暴露到公网。

`VITE_ROS_WS_URL` 只控制浏览器的 WebSocket 目标，不替代 `BACKEND_HOST` 和
`BACKEND_PORT`；后两者仍用于控制 Uvicorn 的绑定地址和监听端口。

## 安装与启动

在项目根目录安装或同步依赖：

```bash
./start.sh sync
```

该命令会：

1. 创建带 `--system-site-packages` 的 `backend/.venv`，以便访问系统 ROS2 Python 包。
2. 使用 `uv sync --active` 同步后端依赖。
3. 使用 `npm ci` 安装前端锁定依赖。

正常使用模式启动前后端：

```bash
./start.sh local
```

不传参数时默认也是 `local`。该模式先执行 `npm run build`，然后通过 `vite preview` 提供静态构建结果，不启用源码监听。开发时需要热更新可执行：

```bash
./start.sh dev
```

脚本会读取 `.env`、加载 ROS2 环境、检查端口和依赖、启动两个进程并等待健康检查。日志写入：

```text
logs/backend.log
logs/frontend.log
```

默认加载 `rvizweb_configs/default.rvizweb`。临时指定其他配置：

```bash
RVIZWEB_CONFIG=default.rvizweb ./start.sh local
```

配置名必须以 `.rvizweb` 结尾且文件必须存在。按 `Ctrl+C` 后，脚本会清理前后端进程组。

`start.sh` 当前支持 `install`、`sync`、`local`、`dev` 和 `help`，不支持
`docker` 子命令。

## 访问入口

端口以 `.env` 为准。使用示例端口时：

- 前端：`http://localhost:3000/`
- 后端健康检查：`http://localhost:8000/health`
- OpenAPI 文档：`http://localhost:8000/docs`
- WebSocket：由前端同源 `/ws` 代理访问

Vite 会将 `/api` 和 `/ws` 请求代理到本地后端，因此日常使用通常只需访问前端地址。

前端代理会读取根目录 `.env` 的 `BACKEND_PORT`，正常模式和开发模式使用相同的 `/api`、`/ws` 后端目标。

## 核心功能与消息类型

当前 3D 场景主要处理：

- `sensor_msgs/msg/PointCloud2`
- `sensor_msgs/msg/LaserScan`
- `nav_msgs/msg/Odometry`
- `nav_msgs/msg/Path`
- `nav_msgs/msg/OccupancyGrid`
- `visualization_msgs/msg/Marker`
- `visualization_msgs/msg/MarkerArray`
- `geometry_msgs/msg/PoseWithCovarianceStamped`

后端消息桥还包含 Image、CompressedImage、CameraInfo、Twist、TF 等类型的转换或发布支持，但“后端能转换”不等同于“3D 场景对该类型有完整渲染器”。新增类型时应分别检查后端类型映射、WebSocket 序列化和前端渲染逻辑。

Fixed Frame 使用 `/tf` 和 `/tf_static`。动态 TF 每个子坐标系保留最近 10 秒、最多 200 个样本；显示消息带有效时间戳时，平移使用线性插值，旋转使用四元数球面插值。早于或晚于缓存范围的查询当前使用最邻近样本，尚未提供 RViz/tf2 等价的外推错误语义。

## `.rvizweb` 配置

- `default.rvizweb`：通用界面配置，不应绑定特定机器人话题。
- `backups/`：覆盖或删除前保存的备份。

配置保存使用同目录临时文件和原子替换，并校验文件名、大小、版本及严格结构。
备份受文件数和总字节数配额约束。RTSP 凭据和查询令牌不允许写入配置。

配置 API：

```text
GET    /api/v1/configs
GET    /api/v1/configs/{name}
POST   /api/v1/configs/{name}
DELETE /api/v1/configs/{name}
```

## 后端接口

主要 ROS2 查询接口位于 `/api/v1`：

- `/topics`、`/topics/frequencies`、`/topic-info`
- `/topics/publish`
- `/nodes`、`/status`

订阅和取消订阅必须通过 WebSocket 会话执行，REST 订阅端点保留为明确的
`405` 兼容提示，避免一个 HTTP 请求破坏其他客户端的共享订阅。

完整参数与响应模型应以运行时 `/docs` 为准。

## 目录结构

```text
RVIZ-RQT-VISUAL/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # configs、ros、viz API
│   │   ├── core/            # Pydantic 环境配置
│   │   ├── models/          # API 数据模型
│   │   ├── services/        # ROS2 与 WebSocket 服务
│   │   └── main.py          # FastAPI 入口
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── src/
│   │   ├── components/RViz/ # 3D 场景与 Displays
│   │   ├── components/panels/
│   │   ├── composables/     # WebSocket 与连接状态
│   │   ├── services/        # HTTP API 封装
│   │   └── utils/           # TF、调试与通用工具
│   ├── package.json
│   └── vite.config.js
├── rvizweb_configs/
├── .env
├── .env.example
├── Dockerfile
└── start.sh
```

## 开发与验证

前端检查：

```bash
cd frontend
npm test
npm run lint:check
npm run build
```

后端基础检查：

```bash
cd backend
uv run pytest -q
uv run flake8 app
uv run python -m compileall -q app
```

当前后端测试覆盖 `.rvizweb` 原子保存、备份、安全会话、路径校验、RTSP
地址策略、消息大小限制、WebSocket 慢客户端与 publisher 所有权，以及
`start.sh` 的基础命令行为。ROS2 订阅、TF 和发布链路仍需在真实 ROS2
环境中做集成验证。

## Docker 状态

仓库提供 Node 22 前端构建、uv 锁文件安装、Nginx 同源代理和安全响应头的
单容器 `Dockerfile`。`start.sh` 不负责容器构建，宿主机 ROS2/DDS 网络仍需按
实际中间件配置验证。

## 常见问题

### 前端看不到远端话题

先在运行后端的终端确认：

```bash
ros2 topic list -t
echo "${ROS_DOMAIN_ID:-0}"
echo "${ROS_LOCALHOST_ONLY:-0}"
```

远端设备需要使用相同 Domain ID，且网络多播、防火墙和 DDS 配置允许互相发现。

### 后端找不到 rclpy

重新执行 `./start.sh sync`，并确认脚本加载了正确的 ROS2 安装和工作空间。虚拟环境必须使用 `--system-site-packages` 创建。

### 端口已被占用

修改 `.env` 中的 `FRONTEND_PORT` 时，同时更新 `CORS_ORIGINS` 中对应的前端
来源。Vite 代理会直接读取 `BACKEND_PORT`，不需要再修改源码。

### 配置未按预期恢复

检查 `logs/backend.log`、浏览器控制台以及配置文件中的 `version`、`fixedFrame`、`displays` 等字段。读取失败时前端会保留当前状态，不会用损坏配置覆盖界面。
