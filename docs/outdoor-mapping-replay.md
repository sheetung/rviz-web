# OutdoorRoad_cut0：室外累积地图

## 带视角跟踪的回放（推荐）

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /home/ubt/Documents/rviz2-web/local_data/OutdoorRoad_cut0_tracking_01
```

网页 Global Options：Fixed Frame `map`，Follow Frame `mapping_lidar`，
Odom Topic `/mapping/odom`。需要时勾选模型和轨迹显示。Follow Frame 负责跟随平移，
不是自动跟随航向。开始播放后 TF 帧会出现在选择器中。

此包保留 311 个累积地图消息，并按原始轨迹时间加入 629 个 Odometry 和 629 个
`map → mapping_lidar` TF（约 10 Hz）。只播放此包，不与旧回放同时发布同名话题。
它表示雷达位姿，模型只作为位置示意，不是经过外参标定的底盘位姿。
Odometry 用于可视化位置；twist 和 covariance 未估计，默认零不能解释为零速度或零误差。

复现：

```bash
python3 scripts/add_mapping_tracking.py \
  local_data/OutdoorRoad_cut0_accumulating_01/map_bag \
  local_data/OutdoorRoad_cut0_glim_cpu_01/dump/traj_lidar.txt \
  local_data/OutdoorRoad_cut0_tracking_new
```

脚本拒绝覆盖输出、拒绝已有跟踪话题的输入，保留原始地图序列。

## 输入与建图

- 原始文件：`/home/ubt/Documents/multi_modal_lidar_dataset/dataset/outdoor/OutdoorRoad-cut0/OutdoorRoad_cut0.bag`。
- 已按数据集校验文件通过 SHA256：`f12e1a37429533e158ff28c1bd0b9062a134a5ecfeeda044244b98c52862acf6`。
- 完整 ROS2 转换：`local_data/OutdoorRoad_cut0_ros2_full`，7 个话题、43460 条记录，
  原生 ROS2 逐条反序列化验证通过，原始数据保持只读。
- Mid360：660 帧点云、13200 条 IMU；前 200 条加速度模长中位数 1.003267，
  输入单位为 g。逐点时间为绝对纳秒，前三帧跨度约 100 ms，与室内配置相符。
- `/gnss_pose` 数值范围类似纬度/经度/高度，不当作米制轨迹直接拼图，也未用于 SLAM。

使用与室内相同的独立 GLIM CPU 运行环境及 Mid360 参考雷达–IMU 外参，
未新增系统或后端依赖。日志、实际配置与原始 GLIM dump 保存在
`local_data/OutdoorRoad_cut0_glim_cpu_01/`。

GLIM 正常完成，轨迹 629 个位姿，覆盖初始化后的 62.80 秒，累计行程 78.69 m；
XYZ 轨迹跨度约 14.65 / 69.61 / 0.61 m，相邻位姿最大平移 0.163 m。
这些是轨迹数值检查，不是 GNSS 定位精度评估或地图无重影保证。

## 累积地图回放

已生成 311 个地图快照，最终 315397 点，XYZ 数据约 3.61 MiB。
原生读包验证通过：时间严格递增、数值有限、点数据大小在限制内，
每帧完整保留前一帧的所有点。尚未做浏览器实测或 GNSS 精度评估。
最终地图和预览位于同目录的 `map.ply`、`preview.png`。

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /home/ubt/Documents/rviz2-web/local_data/OutdoorRoad_cut0_accumulating_01/map_bag
```

播放器与后端的 ROS Domain 保持一致；先停止室内/旧地图回放，避免同名话题混流。
网页选择 PointCloud2 `/mapping/map_points`，Fixed Frame 为 `map`。

输出采用 20 cm 体素去重，目标约 5 Hz；历史点保留，每帧包含截至该时刻的完整地图。
逐点配准来自离线 GLIM 轨迹的平移插值与 SLERP，不是在线 SLAM，也不是 GLIM 内部
IMU 去畸变的精确复现。体素尺寸不是建图精度。当前不添加移动模型或 Odom。

复现（输出必须是新目录；先 source Humble，转换另需隔离工具环境中的 rosbags）：

```bash
python3 scripts/prepare_mapping_bag.py \
  /home/ubt/Documents/multi_modal_lidar_dataset/dataset/outdoor/OutdoorRoad-cut0/OutdoorRoad_cut0.bag \
  local_data/OutdoorRoad_cut0_ros2_new --pose-topic /gnss_pose
python3 scripts/run_indoor_mapping.py local_data/OutdoorRoad_cut0_ros2_new local_data/OutdoorRoad_cut0_glim_new
PYTHONNOUSERSITE=1 python3 scripts/export_accumulating_map.py \
  local_data/OutdoorRoad_cut0_ros2_new \
  local_data/OutdoorRoad_cut0_glim_new/dump/traj_lidar.txt \
  local_data/OutdoorRoad_cut0_accumulating_new --voxel 0.2
```

`run_indoor_mapping.py` 保留历史文件名，当前已用于这两段经过单位和时间检查的
Mid360 数据，不意味着可以对任意数据集直接套用配置。
