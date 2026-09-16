# ROS1 本地部署与测试

当前使用 C++ roscpp 后端，FastAPI 仅管理配置与视频。Docker 部署暂时搁置，不提供 Docker 部署方法。

## 环境与启动

需要 C++17、CMake、Boost.System、JsonCpp 和 ROS1 开发包（roscpp、sensor_msgs、nav_msgs、geometry_msgs、tf2_msgs、visualization_msgs、topic_tools）。管理服务使用独立的 Python 3.10–3.12，不要求安装 rospy。不要在已经 source ROS2 的终端叠加 ROS1。

在项目 .env 中设置：

```dotenv
ROS_WS_URL=/ws/ros1
ROS1_SETUP_PATHS="/opt/ros/noetic/setup.bash"
ROS_MASTER_URI=http://192.168.1.10:11311
ROS_IP=192.168.1.100
ROS1_AUTOSTART_MASTER=false
APP_HOST=0.0.0.0
```

替换为实际安装路径与网络地址。ROS_IP 是运行 RVizWeb 的机器地址；Master 和各节点必须双向可达，TCPROS 使用动态端口。

```bash
./start.sh sync
./start.sh
python3 scripts/check-deployment.py --url http://127.0.0.1:3000 --middleware ros1
```

网页统一连接 `/ws/v2/ros`，C++ API 使用 `/api/v2/ros/*`；`ROS_WS_URL=/ws/ros1` 只用于启动环境选择。配置和视频继续使用管理服务，不提供 v1 切换。

## Master 与可选 Python 工具

默认连接已有 Master，不自动启动。若设置 `ROS1_AUTOSTART_MASTER=true`，仅允许回环地址，且管理 Python 必须能导入 `rosmaster.master`；脚本只关闭自己启动的 Master。此功能及下方 Python 模拟数据脚本需要额外的兼容 ROS Python 包，不是 C++ 后端的运行前提。

Noetic 默认 Python 3.8 不能运行管理服务；可以独立使用 Python 3.10–3.12 运行管理服务。C++ ROS1 开发库必须与当前系统兼容。

## 验收与边界

- [第二阶段](backend-v2-stage2.md)：点云、里程计、TF、激光、路径、Marker、栅格、动态字段。
- [第三阶段](backend-v2-stage3.md)：实际模拟接收器检查控制消息、资源释放和浏览器重连。
- [第四阶段](backend-v2-stage4.md)：本地启动、配置兼容和源码包。

先检查话题发现与坐标系，再用隔离测试话题验证控制；不要把“提交到 ROS”当作机器人执行确认。ROS1 Master 重启后的注册恢复、真实跨机器网络和长时间压力仍未完成验收。旧 `scripts/check_ros1_runtime.py` 用于保留的 v1 代码对照，不作为 v2 验收入口。

## 无雷达模拟点云

终端一运行 `./start.sh`；终端二在项目根目录运行：

```bash
./scripts/demo-pointcloud.sh
```

该脚本另需在管理 Python 中安装 rospy 和标准消息包。脚本按 `.env` 加载 ROS1 环境，默认每秒 5 帧同步发布：

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
