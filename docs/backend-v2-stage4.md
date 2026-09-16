# 后端 v2 第四阶段：本地部署与源码包

范围：ROS 1 / ROS 2 本地部署、配置兼容、源码发布包和回退。**Docker 部署按当前要求搁置，不提供 Docker 部署方法**；历史 Dockerfile / Compose 文件未迁移到 v2，不属于本阶段交付。

## 本地部署

安装和启动仅编译 `.env` 选中的 ROS 版本：`ROS_WS_URL=/ws/ros2` 只构建 ROS 2，`/ws/ros1` 只构建 ROS 1。只需安装所选版本的依赖，不要求同时安装两套 ROS。

需要 Linux、C++17、CMake、Boost.System、JsonCpp、对应 ROS 的 C++ 开发包、Python 3.10–3.12、FFmpeg。Node / npm 版本由仓库固定，安装脚本负责检查。ROS 消息开发依赖见 [原生构建说明](../backend_v2/README.md#构建)。

```bash
cp .env.example .env    # 仅新安装；已有 .env 请保留
# 编辑 ROS1_SETUP_PATHS / ROS2_SETUP_PATHS、ROS_WS_URL 及网络参数
./start.sh sync
./start.sh
```

- ROS2：`ROS_WS_URL=/ws/ros2`，设置对应 setup 路径与 ROS_DOMAIN_ID。
- ROS1：`ROS_WS_URL=/ws/ros1`，设置 setup 路径、ROS_MASTER_URI 和本机 ROS_IP；默认连接已有 Master。
- FastAPI 不再要求导入 rospy/rclpy。自动启动 ROS1 Master 和 Python 演示脚本另需兼容的 ROS Python 包。
- 订阅自定义消息时，追加同版本工作空间 setup。ROS2 需要消息 C++ introspection 支持库。
- 网页默认 3000，内部管理服务 8000、原生服务 8082；用 APP_PORT、RVIZWEB_MANAGEMENT_PORT、RVIZWEB_NATIVE_PORT 调整。
- 日常启动只增量构建原生主程序，复用 CMake 配置；首次构建或 ROS 构建环境变化时重新配置。完整构建与测试使用 `./start.sh sync` 或 `backend_v2/scripts/build.sh`。
- 启动检查直接服务及网页代理链路；任一子服务退出会终止整组进程，Ctrl+C 同样清理。

```bash
python3 scripts/check-deployment.py --url http://127.0.0.1:3000 --middleware ros2
# ROS1 实例使用 --middleware ros1
```

该检查只读取页面和健康/能力接口，不发布控制。浏览器数据固定连接 `/ws/v2/ros`，配置和视频仍由 FastAPI 处理。

## 配置兼容与升级

`.rvizweb` 格式没有因后端切换而另起一套；继续使用现有配置加载、字段迁移、未知字段保留及备份机制。已有 TF、Displays、曲线、相机、布局和目标话题设置可沿用。

升级前停止当前进程，备份整个 `rvizweb_configs/` 和 `.env`。在新目录解压新版源码，将备份复制到新目录，运行 `./start.sh sync` 后启动。不要解压覆盖正在运行的目录，也不要用示例配置覆盖用户配置。备份中可能包含视频凭据，应只保存在本机受控目录。

`ROS_WS_URL` 保留为 ROS 环境选择值；旧 v1 选择项不再提供后端切换。自定义目标话题仍需加入 `ROS_PUBLISH_TOPIC_ALLOWLIST`。首次打开旧页面请刷新，避免旧前端继续请求历史 WebSocket 路径。

## 源码发布包

```bash
python3 scripts/package-source.py 2.0.0-dev.4
cd dist
sha256sum -c rvizweb-2.0.0-dev.4-source.tar.gz.sha256
tar -xzf rvizweb-2.0.0-dev.4-source.tar.gz
```

打包命令不修改 Git、不创建 tag、不推送。相同目标文件已存在时拒绝覆盖；可用 `--output /其他目录` 创建另一个包。

包内包含前后端源码、锁文件、启动与安装脚本、默认配置和文本说明；不包含本机 `.env`、用户配置、依赖缓存、编译产物、数据集或 Docker 部署文件。包中 `MANIFEST.json` 记录源码哈希、Git 提交及工作区是否有未提交改动；压缩包另有 SHA-256 校验文件。它是源码包，目标机器仍需安装依赖并编译，不是离线二进制安装包。文档引用的历史大附件需在仓库中查看。

## 回退

保留上一版完整目录及升级前配置备份。停止新版，将备份复制回上一版目录，按上一版要求准备依赖并启动。回退以完整版本目录为单位，不新增 V1/V2 配置开关；不会自动重放任何控制命令。

目前未创建正式 v2 发布 tag。包名中的版本是本次开发预览版本，前端和管理服务仍分别使用自己的组件版本。

## 验证记录

2026-09-16 验证通过：

- 后端完整回归 130 项 + 25 个子用例通过；之后新增的“只构建所选 ROS”回归也通过。
- 前端 24 个测试文件、ESLint、生产构建通过；修正首次主题配置加载仍请求旧 ROS 路径的问题。
- ROS 1 / ROS 2 分别从源码包解压目录构建，3 项原生单测均通过；每个目录只生成所选 ROS 的构建产物。
- 经网页同源代理验收点云原始字节、里程计、控制消息、回执去重、会话隔离与资源释放，两种 ROS 均通过。
- 真实 Chromium 连接原生服务、读取管理配置，无页面错误或失败 HTTP 请求。
- 分别终止原生子进程，启动器非零退出并清理全部三个服务端口。
- 源码包验证了哈希、可执行权限、敏感配置排除、拒绝符号链接与拒绝覆盖已有发布包。

部署测试复用了本机已安装的 Python / Node 依赖；ROS2 使用隔离 Domain 199，ROS1 使用独立 Master 11424。未向实际机器人发送控制，也未宣称完成空白机器联网安装验收。

Docker、跨机器网络、小时级稳定性和全量性能基准不属于本次已验证范围。
