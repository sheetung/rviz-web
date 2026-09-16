# 第五阶段：共享数据处理、诊断与点云过滤

本阶段只修改原生后端、测试和配置说明；前端界面及独立无人机模拟器不变。保留 FastAPI 配置、系统状态和视频职责。

## 已实现

### 共享 ROS 订阅

相同 `topic + type + reliability + durability` 的客户端共用一次 ROS 订阅与编码，分发同一个不可变数据帧。每个客户端仍有独立有界发送队列；慢客户端不会把其他客户端的数据积压到自己的队列后面。

- 不同 QoS 请求分别订阅；`auto` 与显式 QoS 不合并。auto 仍在创建时解析，不自动跟随发布者 QoS 变化。
- 最后一个订阅者离开后释放普通 ROS 订阅及缓存。`/tf_static` 保持原有常驻缓存。
- 新加入者可立即获取共享流最近一次成功编码的快照，时间戳保留原值；它不代表新采样。全部快照缓存合计最多 64 MiB，超限流不缓存，新客户端等待下一条消息。
- 每个进程最多 64 个共享流。现有每客户端 32 个订阅、16 个连接和单帧 16 MiB 限制保留。
- 网络发送仍按客户端分别进行，不能把共享编码理解成网络带宽不随人数增长。

### 运行诊断

```bash
curl --noproxy '*' http://127.0.0.1:3000/api/v2/ros/metrics
```

也可直接访问原生端口 8082。WebSocket 新增 `streams.stats`，返回同样的流统计及点云处理配置；原有 `session.stats` 增加当前客户端的队列与发送统计。

| 字段 | 含义 |
| --- | --- |
| received / encoded / throttled | 交给共享流的 ROS 回调数、成功编码数、主动限频数 |
| received_hz_average | 该共享流创建以来的平均回调频率，不是源发布频率 |
| encoded_bytes / encoded_bytes_per_second_average | 编码产物累计字节及平均速率，计一次共享编码，不是全部客户端网络流量 |
| conversion_ms_average / conversion_ms_max | 转换、可选过滤与编码时间；不含被限频跳过的样本 |
| conversion_errors / last_error | 累计转换错误与最近错误原因 |
| last_received_age_ms | 距最近回调经过的单调时钟时间，不是跨机器端到端延迟 |
| clients / snapshot_cached | 共享流客户端数、是否保留快照 |
| session.stats.queue | 排队字节/消息数、替换/容量淘汰/超大帧计数、按话题丢帧及待发字节 |
| session.stats.sent | 当前订阅话题已完成 WebSocket 写入的帧数和字节数，不等同于浏览器已渲染 |

会话每话题计数在退订后移除；共享流统计在最后一个客户端离开后移除。正在写入的单帧不计入队列字节。

转换失败会产生 `topic.error` 事件，带 `topic`、`error.code`、`error.message`；区分 `conversion_limit` 与 `conversion_failed`。每共享流最多每秒发送一条错误事件，但计数保留全部失败。错误使用有界数据通道，可被更新的数据覆盖，不挤占控制确认队列。现有前端没有新增错误界面，可通过上述诊断接口查看。

### 可选点云处理

默认关闭，原始点云字节、字段、行填充、大小端和时间戳保持原样。需要时在 `.env` 中设置并重新启动：

```dotenv
RVIZWEB_POINTCLOUD_TOPICS=/sim/uav/points
RVIZWEB_POINTCLOUD_MAX_HZ=5
RVIZWEB_POINTCLOUD_VOXEL_SIZE=0.15
RVIZWEB_POINTCLOUD_CROP=-20,-20,-5,20,20,10
```

- TOPICS：逗号分隔的 glob 模式；默认 `*`。仅匹配的话题使用这些设置，建议明确指定扫描话题，避免无意改变完整地图。
- MAX_HZ：0 关闭限频，范围 0–200；采用单调时钟，转换前跳过过密样本，不创建待处理队列。
- VOXEL_SIZE：0 关闭体素过滤，范围 0–100，单位与点云坐标一致（通常米）。每个体素保留第一个原始点，**不是求质心**。
- CROP：空值关闭裁剪；六个值是 xmin,ymin,zmin,xmax,ymax,zmax，边界包含在内。坐标属于该点云消息 frame，不执行 TF 转换或动态跟随机器人。
- 过滤保留选中点的整条记录，包括 intensity、rgb 和自定义字段；输出变为 height=1 的非组织点云，移除行填充，保留消息头。无效 XYZ 点被过滤。
- 过滤要求唯一的标量 FLOAT32/FLOAT64 XYZ，支持大小端；过滤输入最多 100 万点且受原有帧限制。不支持的格式明确报错，不悄悄输出错误坐标。
- 配置作用于进程，不支持各浏览器单独选择过滤参数。修改环境需要重启。

## 验证

无 ROS 协议/算法测试：

```bash
cmake -S backend -B /tmp/rviz-stage5-test -DRVIZWEB_WITH_ROS=OFF
cmake --build /tmp/rviz-stage5-test -j2
ctest --test-dir /tmp/rviz-stage5-test --output-on-failure
```

新增测试覆盖共享帧、QoS 分离、快照、退订释放、回调/退订并发、错误限频与恢复、默认字节保真、大小端过滤、附加字段和主动限频。

真实 ROS2 验证（使用独立 Domain 197、localhost 和端口 18752，不读取用户 .env，不发布机器人控制）：

```bash
source /opt/ros/humble/setup.bash
backend/scripts/build.sh
backend/management/.venv/bin/python backend/tests/stage5_smoke.py --duration 180
# 小时级验收使用同一测试，延长时间：
backend/management/.venv/bin/python backend/tests/stage5_smoke.py --duration 3600
```

脚本启动并清理自己创建的进程，先验证原始协议、实际 DDS 订阅数量、坏消息恢复及过滤限频，再启动真实地图无人机场景、三个正常客户端和一个停读客户端。结果默认写入 `/tmp/rviz-stage5-results.json`。

## 边界

ROS1 和 ROS2 适配器均接入公共处理逻辑；本轮环境只有 ROS2 开发依赖，ROS1 新版本编译与实机回归尚待复验。小时级、跨机器弱网和完整极限性能对比不能以短时多客户端测试代替。

ROS1 Master 异步发现、每客户端自适应质量、Service/Action、参数管理、地图分块与图像专用传输不在本次实现范围。Docker 继续搁置。

## 本轮实测记录（ROS2 Humble）

- 无 ROS 构建与 ROS2 构建的 4 项原生测试均通过。
- ROS2 显示、动态字段、静态 TF 在发布者退出后的重放，以及控制接收、回执去重、取消与资源释放回归通过。
- 两个客户端订阅同一测试话题，ROS 图实际查询到 1 个 DDS 订阅；一个客户端退出后另一个仍能接收。
- 原有原始点云字节、里程计、来源限制和重连验证通过；坏点云产生结构化错误，随后有效点云恢复正常。
- 显式裁剪后保留完整 intensity 字段及原时间戳；2 Hz 限频产生主动跳帧计数。
- 180 秒真实室外地图测试：三个正常客户端各收到 1,778 帧，共享点云只编码 1,778 次，约 9.86 Hz；停读客户端退出后其余三个客户端继续接收。
- 原生服务 RSS 23.53–26.12 MiB；诊断连接 Ping P95 1.27 ms，最大 3.51 ms。这是本机协议响应时间，不是浏览器端到端显示延迟。
- 全部客户端断开后，共享流计数归零。

[三分钟原始结果](validation/backend-v2-stage5-ros2.json)。该测试是短时验收，不代表已通过小时级或跨机器弱网验收。

补充队列按话题统计后，最终版本再次完成 30 秒全流程回归，三个客户端各收到 290 帧，断开后无共享流残留。[最终版本回归结果](validation/backend-v2-stage5-final-ros2.json)。
