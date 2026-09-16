> 历史记录：旧 Python ROS 后端、旧验证入口及 Docker 文件已从当前源码移除。历史实现见 Git；当前目录与命令以 [原生后端说明](../backend/README.md) 为准。

# 后端 v2 第二阶段验收

日期：2026-09-16。C++ 版本 `2.0.0-dev.2`，协议版本仍为 2。本地入口固定 v2，v1 只保留代码和对照测试。

## 交付

| 能力 | 实现 |
| --- | --- |
| TF | 动态消息合并各 child_frame_id；保留原始时间戳供前端 TF 缓冲使用 |
| 静态 TF | 后端常驻 `/tf_static`，合并不同发布者的边；断开所有网页或发布者退出后仍可恢复 |
| LaserScan、Path、OccupancyGrid | 保留标准字段，使用 JSON 数组，ROS1 时间统一为 sec / nanosec |
| Marker / MarkerArray | 原始 msg 保留；额外 display_snapshot 发送 DELETEALL + 当前有效对象，避免网络队列合并帧丢失增删操作；保留剩余 lifetime |
| 动态曲线 | ROS2 动态加载已安装消息包的 C++ introspection；ROS1 从 ShapeShifter 消息定义解码；支持嵌套值、变长数组、bool、UTF-8 |
| 点云 | 继续使用原有 RVPC 字节通道，未修改编码与分片策略 |

前端沿用现有显示组件，恢复 TF 订阅；修复 LaserScan 的零起始角度与 null 距离处理，以及动态数组统计字段无法生成曲线的问题。

## 验证结果

- ROS2 Humble、ROS1 roscpp 1.15.14 均实际编译并运行，使用隔离 ROS 域 / Master。
- 两套适配器均通过显示测试：动态与静态 TF、LaserScan 含 Inf/NaN、Path、持久和普通栅格、两个 Marker ID、MarkerArray、动态数值数组。
- 静态 TF 从两个发布者合并，发布者全部退出后新 WebSocket 仍恢复两条边。
- ROS2 自定义测试包 `rvizweb_test_interfaces/Telemetry` 验证嵌套向量、float 数组、bool 序列和中文字符串；ROS1 同结构使用未安装的自定义类型实际发布并解码。
- v1/v2 对照同一发布器：LaserScan、Path、两种栅格、MarkerArray、数值数组的解码后数值一致。v1 部分数组是 Python array 字符串，比较时明确规范化；压缩图像的 v1 传输附加字段不计入 ROS 字段比较。
- 原第一阶段 smoke 在 ROS1 / ROS2 均通过：点云精确 bytes、intensity、padding、帧名、时间戳、里程计、确认、退订、双客户端隔离、重连和 Origin 拒绝。
- CTest：每种构建 2 项通过，覆盖队列、二进制、TF replay、Marker ADD / DELETE / DELETEALL 以及自定义 ROS1 定义与截断输入。
- 后端：129 项测试及 26 项子测试通过（在允许本机通信的隔离环境运行）。
- 前端：22 个测试文件、lint、生产构建通过。Chromium 实际连接两种 ROS，固定坐标系设为 static_a（消息为 map），五种显示状态均正常，动态数组平均值持续为 13.583333333333334，无页面或 console error。

浏览器截图：[ROS2](validation/backend-v2-stage2-ros2.png)、[ROS1](validation/backend-v2-stage2-ros1.png)。浏览器使用软件渲染，此处验证功能，不作为 GPU 性能指标。

## 复现

请使用隔离 ROS 环境，不向运行中的机器人图发布测试数据。发布器会创建 `/tf`、`/tf_static` 和 `/v2_test/*`。

ROS2 示例，在同样 source 的三个终端设置 `ROS_DOMAIN_ID=192 ROS_LOCALHOST_ONLY=1`：

```bash
# 终端 1
backend/build/ros2/rvizweb_native --port 18392
# 终端 2：请让服务先启动，静态数据在发布器启动后 2 秒只发布一次
backend/build/ros2/display_fixture
# 终端 3
backend/management/.venv/bin/python backend/tests/display_smoke.py \
  --middleware ros2 --url ws://127.0.0.1:18392/ws/v2/ros \
  --output /tmp/stage2-ros2-events.json
# 停止发布器后验证缓存
backend/management/.venv/bin/python backend/tests/display_smoke.py \
  --middleware ros2 --url ws://127.0.0.1:18392/ws/v2/ros --replay-only
```

ROS1 使用独立 Master、相应 ROS1 二进制和 `--middleware ros1`。

ROS2 自定义包只用于测试，正常构建无需它：

```bash
source /opt/ros/humble/setup.bash
cmake -S backend/tests/interfaces -B /tmp/rviz-stage2-interfaces-build \
  -DCMAKE_INSTALL_PREFIX=/tmp/rviz-stage2-interfaces \
  -DPython3_EXECUTABLE=/usr/bin/python3 -DPYTHON_EXECUTABLE=/usr/bin/python3
cmake --build /tmp/rviz-stage2-interfaces-build --parallel 2
cmake --install /tmp/rviz-stage2-interfaces-build
source /tmp/rviz-stage2-interfaces/share/rvizweb_test_interfaces/local_setup.bash
export ROS_DOMAIN_ID=193 ROS_LOCALHOST_ONLY=1
# 在同样环境另一个终端启动原生服务，端口 18394
backend/management/.venv/bin/python backend/tests/custom_smoke.py
```

`compare_v1.py --reference <display_smoke生成的JSON> --url <隔离v1的ws地址>` 比较字段。v1 仅用测试入口运行，不恢复产品切换配置。

`browser_display.cjs <网页URL> <截图路径>` 验证浏览器。设置 `PLAYWRIGHT_MODULE` 和 `CHROMIUM_PATH`；Vite preview 的 `ROS_V2_PROXY_TARGET` 指向隔离原生服务。测试仅在浏览器拦截配置请求，不修改用户 `.rvizweb` 文件。

## 边界

- 控制发布和完整控制恢复属于第三阶段；容器和发布包尚未迁移。
- 自动 QoS 基于订阅建立时发现的发布者；需要明确历史数据语义时可在协议中指定 reliability / durability。`/tf_static` 固定 reliable / transient_local，普通采样默认 best_effort。
- 普通 ROS 订阅按客户端独立创建，静态 TF 共享。ROS1 Master 同步发现超时隔离仍未完成。
- JSON 显示帧、序列化输入上限各 16 MiB，100 万字段值、32 层嵌套。TF 缓存最多 1024 边 / 8 MiB；Marker 缓存最多 2048 项 / 8 MiB。达到转换限制会记录日志并跳过消息。
- 栅格目前使用 JSON，不包含本阶段专用二进制编码；未重跑地图极限基准，不能用第一阶段报告替代第二阶段性能验收。
