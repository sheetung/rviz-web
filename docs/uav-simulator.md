# 真实点云地图中的无人机模拟器

使用 local_data 中的累积地图与对应 GLIM 轨迹，生成持续运动的四旋翼无人机、局部雷达扫描和里程计。默认无限运行，Ctrl+C 停止。它不回放历史时间戳，每次巡航与目标变更都实时生成新消息。

## 启动

网页服务使用原来的启动方式：

```bash
./start.sh
```

另一个终端运行模拟器：

```bash
./scripts/simulate-uav.sh
```

默认室外道路。首次运行会创建 `rvizweb_configs/sim-uav-outdoor.rvizweb`；网页打开“设置”，在“读取配置”中选中该文件并点击“读取”。场景已配置地图、扫描、无人机模型、路线、尾迹、里程计和跟随相机。原来的默认配置及同名已有配置均不会覆盖。

室内场景：

```bash
./scripts/simulate-uav.sh --scene indoor --height 0.4 --speed 1
```

先停止旧模拟器，再切换场景；读取 `sim-uav-indoor.rvizweb`。同一个 ROS 域/Master 内只允许一个本项目模拟器。

脚本跟随 .env 中选择的 ROS 版本和通信域。模拟脚本另需对应 ROS Python 包与 numpy；C++ 网页后端本身不因此增加 rospy/rclpy 依赖。ROS 2 Humble 已完成实测；ROS 1 兼容发送路径本轮尚未实测。

## 目标交互

模拟器订阅 **/goal_pose**（geometry_msgs/PoseStamped，ROS2 名称为 geometry_msgs/msg/PoseStamped）。

- 在网页“位姿 / 目标”面板输入 X、Y、Z，点击“发布”。
- 无人机从当前状态平滑转向新目标；途中再次发布会更新目标。
- 到达后悬停，雷达、IMU、里程计和 TF 继续更新。
- frame_id 使用 `sim_map`；也接受 `map` 作为同一数据集坐标的别名，不执行跨坐标系变换。
- Z 是地图坐标，不是距地高度；2D 目标工具可能发送 Z=0，需要指定飞行高度时使用 XYZ 面板。
- 非有限值、非法四元数、地图包围盒之外的目标会被拒绝，原因输出到终端和 /sim/uav/status。
- 不订阅 /cmd_vel，不向任何机器人控制话题发布命令。机器人与模拟器同域时，其他节点也可能订阅 /goal_pose；独立仿真建议让网页与模拟器使用同一个专用 ROS_DOMAIN_ID。

ROS2 目标示例（需 source 同一环境并设置相同 ROS_DOMAIN_ID）：

```bash
ros2 topic pub --once /goal_pose geometry_msgs/msg/PoseStamped \
  "{header: {frame_id: sim_map}, pose: {position: {x: 3.0, y: 5.0, z: 1.5}, orientation: {w: 1.0}}}"
```

恢复巡航（自动加载 .env 的 ROS 环境）：

```bash
./scripts/simulate-uav.sh --resume
```

停止当前域内的模拟器：

```bash
./scripts/simulate-uav.sh --stop
```

也可以直接向 /sim/uav/resume 或 /sim/uav/stop 发布 std_msgs/msg/Empty。

恢复时先平滑返回离开路线的位置，再继续无限往返；末端会减速、悬停转向，不会从终点瞬移回起点。ROS1 也可使用上述脚本命令。

## 数据与话题

默认使用匹配的一对文件：

- 室外：OutdoorRoad_cut0_accumulating_01/map.ply + OutdoorRoad_cut0_glim_cpu_01/dump/traj_lidar.txt
- 室内：IndoorOffice1_accumulating_01/map.ply + IndoorOffice1_glim_cpu_01/dump/traj_lidar.txt

以上路径均位于 local_data。不会修改源地图或录包。

| 话题 | 内容 |
| --- | --- |
| /sim/uav/map | 完整真实地图；保留最新快照，每 5 秒重发 |
| /sim/uav/points | 传感器局部坐标 XYZ + 合成距离强度，默认 10 Hz |
| /sim/uav/odom | 无人机位姿及机体系速度，目标 30 Hz |
| /sim/uav/imu | 姿态、角速度与包含重力的比力，目标 30 Hz |
| /tf、/tf_static | sim_map → sim_uav/base_link → sim_uav/lidar |
| /sim/uav/route、/sim/uav/trail | 巡航路线及最近最多 600 个轨迹点 |
| /sim/uav/markers | 四旋翼机体、旋翼、雷达和目标标记 |
| /sim/uav/speed、/sim/uav/height | 可添加到数值曲线的速度、地图 Z 坐标 |
| /sim/uav/status | JSON 文本：模式、目标反馈、扫描点数和计算耗时 |

扫描采用 360° 水平视野、上下各 45°、900×48 个角度格，每格保留最近地图采样点；默认 30 米量程、1 厘米距离噪声。扫描和 odometry 使用对应的同一时刻位姿；雷达在机体上方 0.18 米。

## 参数与边界

```bash
./scripts/simulate-uav.sh --scene outdoor --speed 2 --height 1.2 --range 30 --rate 10
# 有限时长验收；正常不传 duration，默认一直运行
./scripts/simulate-uav.sh --duration 60 --noise 0
```

height 是相对录制时雷达轨迹的高度偏移，不是地形跟随高度；speed 是巡航峰值速度参数，目标转换为平滑位置轨迹，不是飞控速度约束。增加量程、扫描频率会提高 CPU 消耗。扫描在单独工作线程计算，同时最多一帧计算，不会堆积任务；尾迹和控制请求队列也有固定上限。

这是**运动学与传感器可视化模拟**：不是飞行动力学、避障规划或在线 SLAM。地图采样有稀疏区域，角度格遮挡是近似；目标航线可能穿过障碍物。IMU 和强度为合成值，不能当作原始雷达/IMU 的精确物理模型。ROS header 使用当前 ROS 时钟，不主动发布 /clock。

核心测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest scripts/simulation/test_scene.py -q
```

## 本轮验证

- 6 项核心测试通过，包括一万次循环后的边界连续性、目标重规划与悬停、恢复巡航和雷达最近点选择。
- 在隔离 ROS2 Domain 196 中，通过原生 v2 发布目标，实际验证到达悬停与恢复巡航；悬停期间扫描没有中断。
- 无噪声扫描经对应里程计/雷达偏移变换后，与源地图点的误差小于 0.1 毫米。
- 室外场景 315,397 地图点，单帧扫描约 18,000 点；短时验收里程计约 28.5 Hz，扫描约 10 Hz。频率取决于机器负载，不是硬实时承诺。

浏览器实际配置加载与显示已通过，无页面异常。[室外场景截图](validation/uav-simulator-outdoor.png)。
