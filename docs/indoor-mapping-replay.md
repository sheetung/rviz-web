# IndoorOffice1：准备累积地图回放

## 连续累积地图（优先使用）

`scripts/export_accumulating_map.py` 从原始 Mid360 扫描与已保存的 GLIM 雷达轨迹
生成约 5 Hz 完整地图快照，历史点保留、新扫描逐步加入，替代首版 9 次子地图更新。
按每个点的绝对时间做平移线性插值和旋转 SLERP，再以 10 cm 体素保留首个观测点。
这是离线轨迹驱动的累积展示，运动补偿是轨迹插值近似，不等同于 GLIM 内部 IMU
去畸变，也不复现在线回环修正。初始化之前、轨迹结束之后的点不外推。

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /home/ubt/Documents/rviz2-web/local_data/IndoorOffice1_accumulating_01/map_bag
```

网页保持 PointCloud2 `/mapping/map_points`、Fixed Frame `map`。只播放一个地图包，
不要与旧版同时发布同名话题。此版本只包含地图话题，不添加移动模型、TF 或 Odom。
每个消息都是当时完整地图；即使实时链路跳过中间快照，下一帧也会包含已有区域。

复现（需要系统 NumPy、SciPy 及已 source 的 Humble；不改后端依赖）：

```bash
PYTHONNOUSERSITE=1 python3 scripts/export_accumulating_map.py \
  local_data/IndoorOffice1_ros2_full \
  local_data/IndoorOffice1_glim_cpu_01/dump/traj_lidar.txt \
  local_data/IndoorOffice1_accumulating_new
```

输出目录必须不存在，保留旧版地图。默认 `--hz 5 --voxel 0.1`，单帧点数据超过
8 MiB 则终止并要求增大体素，不静默截断地图。

本次生成并原生读回验证：630 个包含有效点的扫描、315 个地图快照，覆盖 62.80 秒。
初始化前 30 个无轨迹覆盖的扫描跳过；边界扫描仅保留轨迹覆盖内的点。
更新间隔中位数 0.2000 秒，最大约 0.3001 秒；边界的部分扫描可能产生很短间隔。
最终 393362 点，XYZ 数据约 4.50 MiB。逐帧验证有限数值、严格递增时间戳、
消息尺寸，并逐字节确认前一帧点数据完整保留为后一帧前缀。尚未完成浏览器实测。

## 已完成（2026-09-15）

原始数据只读，不修改既有点云测试副本。新增完整 ROS2 Humble bag：

```text
local_data/IndoorOffice1_ros2_full/
  metadata.yaml
  IndoorOffice1_ros2_full_0.db3
  mapping_audit.json
```

约 4.5 GiB，目录已被 Git 忽略。转换使用 Humble 原生 rosbag2 写入器，保留录包时间、
消息 header 时间、点云字段和 IMU/位姿数据；仅按标准消息定义移除 ROS1 Header.seq。
随后用 ROS2 原生读取器读完全部记录，并成功反序列化每个话题的首条消息。

| 话题 | 条数 |
| --- | ---: |
| `/avia/livox/lidar` | 662 |
| `/avia/livox/imu` | 13461 |
| `/mid360/livox/lidar` | 660 |
| `/mid360/livox/imu` | 13212 |
| `/ouster/points` | 661 |
| `/ouster/imu` | 8257 |
| `/vrpn_client_node/unitree_b1/pose` | 7664 |
| 合计 | 44577 |

原始记录约 66.20 秒；各话题 header 时间未观察到倒序。

## 时间与标定检查

- 动捕位姿 frame_id 是 `world`，Mid360 是 `mid360_frame`。
- Mid360 与动捕的 header 时间范围重叠；点云到最近动捕样本的时间差中位数
  3.66 ms、最大 70.42 ms。需要按 header 时间插值，并对缺口设置拒绝条件；
  这不等于已经验证传感器同步精度。
- Avia header 从约 759 秒开始，Ouster 从约 1651168498 秒开始，动捕/Mid360
  从约 1743002278 秒开始，不能直接用三者 header 时间互相匹配。
- Mid360 点云 header 比录包时间约早 75505.53 秒。直接按 bag 到达顺序搭配
  位姿或把录包 `/clock` 当消息采集时间，均可能引入错误。
- 本地标定说明只有 PTP 和逐点时间字段描述，没有动捕刚体到 Mid360 的数值外参。
  动捕 PoseStamped 不是现成的雷达 TF。

因此先选 Mid360。若使用动捕直接拼接，必须
先取得/标定刚体到雷达外参；不能静默假设刚体坐标系就是雷达坐标系。

## 下一阶段：独立 GLIM ROS2 建图

按 [TIERS 官方处理流程](https://github.com/TIERS/multi_modal_lidar_dataset/blob/main/docs/pipelines/README.md)，
改为先用 Mid360 点云与内置 IMU 运行 SLAM，动捕只用于后续评估。
这条路线不要求动捕到雷达外参才能启动，但仍需要确认雷达与 IMU 的外参。
SLAM 输出的 `map` 是算法建立的坐标系，不等同于动捕 `world`。

选择 GLIM 的 ROS2 CPU 路线：当前机器没有 NVIDIA GPU；运行环境放在被 Git 忽略的
`local_data/glim_runtime/`，不向后端 Python 依赖、系统软件源或 `.env` 添加配置。
安装依据为 [GLIM 官方说明](https://koide3.github.io/glim/installation.html)。

已对完整转换包做实测：

| 检查 | 结果 | GLIM 配置含义 |
| --- | --- | --- |
| 前 200 条 Mid360 IMU 加速度模长 | 中位数 1.001425，范围 0.984600–1.018231 | 输入为 g，`acc_scale=9.80665` |
| 前三帧逐点 `timestamp` | FLOAT64，约 1.743002278e18 | 绝对纳秒，`perpoint_relative_time=false`、`perpoint_time_scale=1e-9` |
| 前三帧逐点时间跨度 | 99.959 / 99.927 / 100.114 ms | 非瞬时扫描，需要运动畸变校正 |

显式设置上述逐点时间参数时应关闭 `autoconf_perpoint_times`；配置项含义见
[GLIM 传感器配置](https://github.com/koide3/glim/blob/master/config/config_sensors.json)。
不要沿用其默认 Ouster `T_lidar_imu`，也不要把数据中的绝对纳秒当相对秒。

### 首轮地图结果（2026-09-15）

下载问题已解决。官方 PPA Release 签名、公钥指纹
`A0DAE9CF75CFEF37A509FCD3C2C44E47B79E8F3A`、Packages 哈希及五个 GLIM
软件包 SHA256 已校验；软件包只解压到 `local_data/glim_runtime/root`。
额外运行库 libmetis5/libglfw3 通过 Ubuntu 软件源下载后解压，没有系统安装。

首轮使用 [FAST-LIO 官方 Mid360 参考外参](https://github.com/hku-mars/FAST_LIO/blob/main/config/mid360.yaml)。
FAST-LIO 定义为雷达到 IMU，GLIM 需要其逆变换：
`T_lidar_imu = [0.011, 0.02329, -0.04412, 0, 0, 0, 1]`。
这是传感器参考配置，不是数据集专用标定结果；没有将动捕坐标当雷达坐标。

GLIM 1.2.2 CPU、passthrough submapping、pose-graph global mapping、无 GUI 扩展，
在 localhost、ROS Domain 87 离线读包。日志起止约 12.5 秒（含初始化与保存，
不是网页端到端性能指标），处理约 66 秒数据，正常退出并保存：

- 629 个轨迹位姿，覆盖初始化后的 62.80 秒；初始化约需前 3 秒数据。
- 9 个子地图，累计轨迹长度 30.67 m，相邻位姿最大平移 0.133 m。
- 合并导出 189966 个 XYZ 点，点数据 2279592 字节（约 2.17 MiB）。
- 输出按 8 cm 体素去重；上游子地图本身已经降采样，8 cm 不代表测量精度。
- 预览能辨认墙面和室内轮廓；尚未做标定后 MoCap 精度评估。当前设置的
  回环候选最小行程为 50 m，不能把本次结果称为已验证回环优化的地图。

产物（均被 Git 忽略）：

```text
local_data/IndoorOffice1_glim_cpu_01/  # 实际配置、日志、GLIM dump 与轨迹
local_data/IndoorOffice1_map_01/
  map.ply                            # 最终地图，二进制 XYZ PLY
  preview.png                        # 高度着色俯视图与轨迹，不是相机 RGB
  summary.json                       # 点数、范围、轨迹与快照统计
  map_bag/                           # 9 个累积快照 + 629 个 PoseStamped
```

导出使用 GLIM 保存的 `T_world_origin` 把已配准子地图变换到 `map`，没有对原始
扫描简单叠加。二进制格式依据
[gtsam_points 官方保存实现](https://github.com/koide3/gtsam_points/blob/master/src/gtsam_points/types/point_cloud.cpp)。
每个快照是完整地图，按子地图结束时间记录；这是最终优化子地图的离线累积展示，
不是逐扫描实时建图或真实回环事件的复现。首个快照需等待约 9 秒，之后约 4–9 秒更新。

原生 ROS2 读取器已读完导出 bag，核验全部 638 条消息的类型、时间、`map` 坐标系、
点数据长度及有限数值；地图点数从 22999 单调增长到 189966。
另有 4 个纯数据回归测试通过，覆盖变换、纳秒时间戳、体素去重和非法数据。

### 直接在网页查看

先连接网页、添加 PointCloud2 Display，话题选择 `/mapping/map_points`，
Fixed Frame 设为 `map`，然后回放（播放器的 ROS Domain 必须与后端一致，不必用测试的 87）：

```bash
source /opt/ros/humble/setup.bash
ros2 bag play local_data/IndoorOffice1_map_01/map_bag
```

位姿话题是 `/mapping/lidar_pose`。若播放结束后才订阅，重新播放即可。
当前验证到导出 bag；尚未宣称浏览器实测通过。下一步可改为更高频地图输出，
让累积过程连续，并测量网页传输/渲染延迟。

复现（输出目录必须不存在；先 source Humble）：

```bash
python3 scripts/run_indoor_mapping.py local_data/IndoorOffice1_ros2_full local_data/IndoorOffice1_glim_cpu_new
python3 scripts/export_glim_map.py local_data/IndoorOffice1_glim_cpu_new/dump local_data/IndoorOffice1_map_new
python3 -m unittest discover -s scripts -p 'test_export_glim_map.py'
```

## 前端通过什么显示“累积”

当前 `Scene3D.vue` 按话题更新几何体，使用新帧覆盖顶点缓冲；不是扫描历史累积器。
最小验证链路可以是：

```text
Mid360 扫描 + 内置 IMU + 雷达–IMU 外参
  → 独立 GLIM ROS2：运动估计、扫描配准、建图
  → 地图输出工具：统一 map 坐标、去重/降采样
  → /mapping/map_points（PointCloud2，每帧是当前完整地图）
  → 网页 PointCloud2 Display（Fixed Frame 与地图 header.frame_id 一致）
```

`/mapping/map_points` 已在导出地图 bag 中提供，播放时才会发布。原始动捕世界系叫
`world`；如果输出使用 `map`，必须明确两者的关系，不能把未变换的雷达扫描改个
frame_id 就冒充世界坐标。

完整地图快照能直接利用当前前端，“替换一帧”仍会看到逐渐扩大的地图；无需先增加
前端无限历史缓存。快照原型应低频更新并做体素去重，遵守后端单帧大小限制。
更大地图再考虑分块、版本和补传，不直接套用实时扫描的最新帧合并策略传增量。
此数据处理不属于公共 ROS 适配层，也不要求先接入 ROS1 在线运行时。

## 当前可以回放什么

```bash
source /opt/ros/humble/setup.bash
ros2 bag play local_data/IndoorOffice1_ros2_full
```

播放器与后端使用相同 Domain。此时看到的是扫描、IMU、动捕位姿，不是累积地图。
只查看 Mid360 扫描时可以把 Fixed Frame 设为 `mid360_frame`；没有正确 TF 时不要
把它设成 `world` 并期待自动配准。

转换工具为 `scripts/prepare_mapping_bag.py`，不修改后端依赖；需要先 source Humble，
再在含 rosbags 的临时工具环境运行。示例（目标必须不存在，避免覆盖）：

```bash
uv run --no-project --python backend/.venv/bin/python --with rosbags \
  python scripts/prepare_mapping_bag.py \
  /home/ubt/Documents/multi_modal_lidar_dataset/dataset/indoor/IndoorOffice1/IndoorOffice1_dataset.bag \
  local_data/IndoorOffice1_ros2_full_new
```
