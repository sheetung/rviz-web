# ROS1 部署与回去测试步骤

2026-09-15：ROS1 原生适配、版本入口与配置更名已实现。
这是独立 ROS1 实例，不是 ROS1/ROS2 消息桥。

## 推荐部署：独立 ROS1 容器

本项目后端要求 Python 3.10–3.12。新增 `Dockerfile.ros1` 使用 Ubuntu 22.04
软件源的 ROS1 1.15 系列与 Python 3.10，**不是官方 Noetic/Focal Python 3.8 镜像**。
本机已用同类包验证 ROS1 原生收发；现有 Noetic ROS 网络是首要外部接入测试目标。
不要仅把 Python 3.8 的 Noetic setup 路径填入当前后端，就假设依赖一定兼容。

项目 `.env` 填写实际网络地址，例如：

```dotenv
ROS_MASTER_URI=http://192.168.1.10:11311
ROS_IP=192.168.1.100
ROS_WS_URL=/ws/ros1
```

`ROS_IP` 是运行 RVizWeb 容器的宿主机局域网地址，不是 Master 地址，除非两者同机。
先在设备上启动 roscore/现有 ROS1 系统，再执行：

```bash
cd /home/ubt/Documents/rviz2-web
docker compose -f docker-compose.ros1.yml up --build -d
docker compose -f docker-compose.ros1.yml logs -f
```

浏览器访问 `http://192.168.1.100:3000`。ROS1 Compose 使用 Linux host 网络，
不自动启动 Master；不要与默认 ROS2 Compose 同机同时启动，它们都占用 3000/8000。
Compose 根据 ROS_IP 设置默认浏览器 Origin；用 DNS、HTTPS 或其他 UI 地址访问时，
在 Compose override 中显式设置 `CORS_ORIGINS`，不要设无限制来源或开放到公网。
Master 和节点须双向可达，TCPROS 会使用动态端口，不只是开放 11311。

当前机器没有 Docker，镜像及 Compose 尚未实机构建/运行验证；上面是交付的部署路径，
遇到构建问题保留完整日志。ROS1 软件栈的维护期限和安全风险也需由部署方评估。

## 原生启动

如果机器已经有能被后端 Python 导入的 ROS1 包，可不用容器：

```dotenv
ROS1_SETUP_PATHS="/你的ROS1环境/setup.bash /你的同版本工作空间/devel/setup.bash"
ROS_MASTER_URI=http://192.168.1.10:11311
ROS_IP=192.168.1.100
ROS_WS_URL=/ws/ros1
APP_HOST=0.0.0.0
```

原生安装脚本在 ROS1 模式下使用 `uv sync --frozen --no-dev --extra ros1`，
自动安装锁定的 `rospkg` 及其依赖，并在同步后检查 `rospy` 和消息导入。
已有环境缺包时运行 `./start.sh sync`；仅依赖 `--system-site-packages` 不能保证
uv 管理的 Python 能访问系统 Python 的 ROS 辅助包。

setup 文件必须由可信部署提供，导出 ROS_VERSION=1 及正确 Python/消息搜索路径。
Ubuntu 22.04 原生 ROS1 包部署可参考 `docker/ros1-setup.bash`，先自行安装
Dockerfile.ros1 列出的 ROS1 包；该文件本身不安装依赖。
官方 Noetic 安装可填写 `/opt/ros/noetic/setup.bash`，但仍必须通过以下解释器检查：

```bash
# 在干净终端中加载你选定的 ROS1 环境后
backend/.venv/bin/python -c 'import rospy, roslib.message; from sensor_msgs.msg import PointCloud2'
./start.sh sync
./start.sh
```

后端不能用 Python 3.8 运行，且 ROS1 原生 Python 扩展、自定义消息必须与后端解释器兼容。
无法满足时用独立容器，不降级整个 Web 后端。不要在 source 了 Humble 的终端叠加 Noetic。
启动脚本会拒绝缺失 setup、混合 ROS_VERSION/ROS_DISTRO，以及 `.env` 手填 ROS_VERSION。
`ROS1_SETUP_PATHS` 与 `ROS2_SETUP_PATHS` 分别配置两套环境，取代 `ROS_SETUP_PATHS`。
默认 `ROS_WS_URL=/ws/ros2`；原生 ROS1 启动时改为 `/ws/ros1`，并配置 `ROS1_SETUP_PATHS`。
ROS1 容器内默认使用 `/app/ros1-setup.bash`，前端和启动环境均默认选择 ROS1。

自定义消息需把对应工作空间部署到 ROS1 运行环境并 source；不要向容器挂载另一 Python/
系统版本编译的二进制扩展并假设可用。未知消息类型会明确报错。

## 本机 Master 自动启动

原生 `start.sh` 会在构建前检查 `ROS_MASTER_URI`，不可达时明确报错。
本机测试可配置 `ROS1_AUTOSTART_MASTER=true`，并使用回环地址（例如
`http://127.0.0.1:11311`）。脚本会复用已有 Master，或启动一个本机 Master；
只关闭自己启动的 Master。该模式不启动机器人驱动或传感器，也不启动 rosout。
远程机器人保持 `false` 并填写实际 Master 地址。ROS2 不执行这项检查。
ROS1 Master 的 `defusedxml` 依赖由 `ros1` 依赖组安装。

## WS 与 API 选择

- `/ws`：连接本实例的 ROS 版本。
- `/ws/ros1`、`/ws/ros2`：指定版本；版本不匹配返回 `middleware_mismatch` 并关闭。
- 指定 `ROS_WS_URL=ws://host:3000/ws/ros1` 时，ROS、配置、视频 API 同步使用
  `http://host:3000/ros1/api/v1/…`，不能再把 `VITE_BACKEND_PUBLIC_URL` 指向另一实例。
- `ROS_WS_URL` 在前端构建时注入，改动后重新构建/启动；留空为同源代理。
- 当前本地后端固定监听回环 8000，不从 WS URL 推导绑定地址或端口。
- 同端口双实例代理参考 `docker/nginx-dual.example.conf`，两个后端需分别部署并监听
  示例中的 18081/18082；示例不会自动启动两个实例。
- HTTPS 页面需使用 wss。URL 指向 RVizWeb 后端，不是任意 rosbridge_server。

## 验收顺序

1. `curl http://192.168.1.100:3000/health` 应显示 `middleware: ros1`，Master 不可达时为 503。
2. 浏览器连接，刷新话题/节点列表，与 ROS1 `rostopic list`、`rosnode list` 对照。
3. 回放 **原始 ROS1 bag**，不是本项目转换后的 ROS2 bag；查看 PointCloud2 和 Image。
4. 有 Odom、TF 的数据选择正确 Fixed Frame、Follow Frame、Odom Topic，检查模型与轨迹。
   原始雷达 bag 未必带 Odom/TF；ROS1 适配器不会凭空创建定位或累积地图。
5. 打开第二个浏览器，确认 `/tf_static`、latched 地图/消息也能显示；关闭一个不影响另一个。
6. 只在隔离测试话题验证 advertise/publish；真实 `/cmd_vel` 等可能控制设备，先确保设备安全。
7. 断开/重连浏览器，检查订阅恢复；停止全部浏览器后不残留会话 Publisher/Subscriber。
8. 错连 `/ws/ros2` 应明确提示版本错误，而不是持续重连或偷偷接入 ROS2。
9. ROS Master 重启后需重启 RVizWeb，重新注册节点；当前健康状态能报告断连，但
   **不承诺 rospy 在 Master 清空注册表后自动恢复全部注册**。

## 已执行验证与限制

- 后端 115 项单测通过，包含版本选择、错误路由、setup 混用、ROS1 标量/时间转换、
  大端及带行填充 PointCloud2；前端 18 个测试文件通过，生产构建通过。
- 原生 ROS1 Master 11391 + Web 后端 18081（localhost）：工厂选择、图查询、
  二进制点云、Twist 发布、服务类型探测、共享 latched/静态 TF、断线清理、版本路由通过。
- 原始 OutdoorRoad_cut0 ROS1 bag 抽取 120 帧 Mid360，约 8 倍输入速度，通过
  原生 rospy/TCPROS → Adapter → WebSocket，两次验证分别收到 19 / 18 个按最新帧策略输出的二进制快照。
  这是短时链路正确性验证，不是 LAN 延迟或满负载性能报告。
- ROS2 独立 Domain 88 原生点云收发、转换、取消订阅通过。
- 未执行目标设备 LAN 浏览器验收、Docker 构建、长时多客户端压力测试及真实自定义
  工作空间兼容验证。现有标准消息转化支持不代表每个 ROS1 驱动都已实测。
- ROS1 频率目前只报告已订阅话题的观测值，未主动订阅全图采样；ROS1 Domain 为 null。
  service 调用、action、参数写入不在当前范围。

可复现实测脚本 `scripts/check_ros1_runtime.py [原始ROS1.bag]`，需要 rospy、rosmaster、
标准消息、后端依赖；可选 bag 验证另需 rosbags。使用独立测试端口，不连接实际机器人。
测试脚本故意覆盖自身进程的 Master/ROS_IP，不修改用户配置。

## 无雷达模拟点云

终端一运行 `./start.sh`；终端二在项目根目录运行：

```bash
./scripts/demo-pointcloud.sh
```

脚本按 `.env` 加载 ROS1 环境，默认每秒 5 帧同步发布：

- `/demo/points`：`sensor_msgs/PointCloud2`，坐标系为 `demo_lidar`。
- `/demo/odom`：`nav_msgs/Odometry`，父坐标系 `map`、子坐标系 `demo_lidar`。
- `/tf`：`map → demo_lidar`，与 odom 和点云使用相同时间戳和位姿。

雷达在半径 2 米的圆形轨迹上以 0.4 m/s 移动，场景包含固定的地面、四根立柱和球体。
点云按传感器位姿转换到局部坐标，模拟 360° 水平视角、32 个垂直通道（-30° 到 15°），
量程默认为 8 米，每束保留最近的表面采样点。这是采样近似模拟，不是物理级光线追踪。

在页面将 Fixed Frame 设为 `map`，添加 PointCloud2 显示项并选择 `/demo/points`；
在 Global Options 中选择 odom 话题 `/demo/odom`，可启用模型和轨迹查看运动。
`map` 视角下固定场景不应跟着雷达整体移动，但扫描到的点会变化；
将 Fixed Frame 改为 `demo_lidar` 可观察雷达自身视角下的环境运动。
按 Ctrl+C 停止发布；可用 `--rate 10 --duration 30 --range 6` 调整频率、运行时间和量程。
