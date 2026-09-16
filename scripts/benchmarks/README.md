# ROS 2 地图性能基准

这些脚本只启动独立测试进程，不修改后端默认参数、用户地图或 `.env`。需要已安装 ROS 2 Humble、项目 Python 环境中的 `numpy / psutil / websockets`，以及 C++ 编译依赖。先按 `backend/README.md` 构建原生服务。

## 准备

在仓库根目录：

```bash
source /opt/ros/humble/setup.bash
cmake -S scripts/benchmarks -B /tmp/rviz-map-bench/build -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/rviz-map-bench/build -j2
python3 scripts/benchmarks/prepare_map.py local_data/IndoorOffice1_map_01/map.ply /tmp/rviz-map-bench/indoor.xyz
python3 scripts/benchmarks/prepare_map.py local_data/IndoorOffice1_accumulating_01/map.ply /tmp/rviz-map-bench/indoor_dense.xyz
python3 scripts/benchmarks/prepare_map.py local_data/OutdoorRoad_cut0_accumulating_01/map.ply /tmp/rviz-map-bench/outdoor.xyz
```

`prepare_map.py` 仅接受本项目导出的 binary little-endian XYZ PLY，并记录完整 XYZ 数据 SHA-256。地图只读，提取文件写入指定临时目录。

## 测试计划

JSON 数组中每项是一轮；进程在轮次之间重启。例：

```json
[
  {"name":"indoor-10hz","mode":"v2","map":"indoor","points":189966,"hz":10,"seconds":15}
]
```

- `mode`：仅支持 `v2` 原生服务。历史 Python 对比实现已移除，历史报告保留。
- `points`：小于地图点数时均匀抽取，大于原图时循环复制原有点，仅用于扩大数据量；不是新增测绘地图。
- `clients`：正常 WebSocket 客户端数，默认 1。
- `slow`：确认订阅后停止读取的客户端数，默认 0。
- `warmup`：预热秒数，默认 3；`seconds`：测量窗口，默认 15。
- `browser:true`：使用真实生产前端和 Chromium，替代协议接收客户端。

```bash
backend/management/.venv/bin/python scripts/benchmarks/run.py \
  --plan /path/to/plan.json --output /tmp/unique-benchmark-results \
  --native backend/build/ros2/rvizweb_native
```

默认隔离 Domain 为 191，后端端口 18191；可用 `--domain / --port` 指定。输出目录必须不存在，防止覆盖旧证据。测试源只发布 `/benchmark/map`，不包含运动控制。

## DDS 对照

不传 `--dds-profile` 时使用默认 Fast DDS 配置与 `ROS_LOCALHOST_ONLY=1`。
使用以下参数启用测试专用 SHM-only 配置：

```bash
--dds-profile scripts/benchmarks/fastdds-shm.xml
```

它将测试参与者的共享内存段设为 64 MiB，最大传输消息设为 20,000,000 B，禁用内置 UDP 传输；只适用于同机对照，不代表跨机器网络性能。XML 由 `FASTRTPS_DEFAULT_PROFILES_FILE` 仅传给测试子进程。配置依据：[Fast DDS 2.6 共享内存文档](https://fast-dds.docs.eprosima.com/en/2.6.x/fastdds/transport/shared_memory/shared_memory.html)。

## 浏览器

先 `cd frontend && npm run build`，确保构建时 `ROS_WS_URL=/ws/ros2`。额外准备 Playwright 和 Chromium：

```bash
export PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright
export CHROMIUM_PATH=/absolute/path/to/chrome
```

浏览器轮次自动启动 Vite preview（后端端口 +2），1440×900、DPR=1、SwiftShader 软件 WebGL。拦截配置及版本 HTTP 请求以使用测试配置；ROS WebSocket、点云 Worker、Three.js 绘制均真实运行。测试不写用户配置。

浏览器注入的统计代码记录 WS 到达、Worker 往返、POINTS 绘制调用、首次绘制新帧的消息年龄、长任务及渲染器名称，不写入产品源码。`draws` 表示提交绘制调用，不能视为 GPU 完成或物理屏幕呈现时间。CPU 包括 Chromium 子进程，软件渲染结果不能直接当作平板 GPU 上限。

## 指标与边界

- 源端逐帧记录发布完成时间与消息时间戳；独立原生 DDS 探针记录实际接收。
- 同机墙钟计算源时间戳到 WS 收到的消息年龄；ping 使用单调时钟测往返。
- 每个正常客户端校验点数、字段步长、完整原始数据长度，并对首帧校验 SHA-256。
- 吞吐仅统计完整 RVPC 应用帧，CPU 100% 表示一个 CPU 核，后端与发布器/探针/接收器分别统计。
- 每 0.5 秒在线程中采集 RSS/PSS/USS，避免阻塞协议接收循环。RSS 包含 DDS 缓冲和映射，不能等同于新增物理内存。
- 后端 RSS >1 GiB 或系统可用内存 <1 GiB 时停止本批测试，不以系统 OOM 为验收目标。
- 每轮保存资源采样、源/探针 CSV、WS 帧与 ping 时间、错误和退出码。所有子进程按 PID 组清理。
- “目标 Hz”不是实收 Hz；单轮短测峰值也不是长期稳定容量。默认限频、消息大小拒绝和传输丢帧应分别解释。

## 自动分片诊断

当前原生服务沿用 Beast 默认自动分片。以下命令只修改临时源码副本：

```bash
python3 scripts/benchmarks/make_variant.py /tmp/rviz-native-no-fragment
cmake -S /tmp/rviz-native-no-fragment -B /tmp/rviz-native-no-fragment-build -DROS_VERSION=2 -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/rviz-native-no-fragment-build -j2
ctest --test-dir /tmp/rviz-native-no-fragment-build --output-on-failure
```

用相同测试计划重跑，并将 `--native` 指向诊断产物。结果不能作为当前 v2 已发布性能。计划项添加 `count_fragments:true` 可记录首个点云消息的 WebSocket 分片数；该计数只用于低频诊断轮次。

浏览器项可添加 `gl:"auto"`，允许 Chromium 自动选择可用 GPU（同时允许软件回退）；以结果中的实际 renderer 字符串判定，不能由配置名推定已启用硬件加速。

## 汇总证据

```bash
python3 scripts/benchmarks/collect.py /tmp/rviz-map-bench docs/benchmarks/ros2-map-2026-09-15
MPLCONFIGDIR=/tmp/rviz-map-mpl python3 -s scripts/benchmarks/plot.py docs/benchmarks/ros2-map-2026-09-15/results.json
```

绘图需要相互兼容的 NumPy / Matplotlib；本机用系统 Python 的 `-s` 避开用户目录中不同版本的 NumPy。

汇总脚本从原始时间戳重算统一数据窗口，保留 CPU 实际采样时长；归档不会包含地图坐标数据。早期试验中取消正在接收的分片消息曾触发 Python websockets 的关闭期断言；原始错误保留，另列 `teardown_errors`，不混入测量期间错误。后续测试已改为先关闭连接再取消读取任务。
