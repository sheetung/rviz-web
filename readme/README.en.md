<div align="center">

# RVizWeb

**A browser-based visualization workspace for ROS**

View 3D point clouds, robot poses, live charts, and video in one place, with topic management and reusable task configurations.

[中文](../README.md) | [English](./README.en.md)

[![GitHub Stars](https://img.shields.io/github/stars/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/forks)
[![GitHub Issues](https://img.shields.io/github/issues/sheetung/rviz-web?style=flat-square)](https://github.com/sheetung/rviz-web/issues)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue?style=flat-square)](../LICENSE)

![ROS](https://img.shields.io/badge/ROS-22314E?style=flat-square)
![Vue 3](https://img.shields.io/badge/Vue-3-42B883?style=flat-square)
![Three.js](https://img.shields.io/badge/Three.js-WebGL-222222?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?style=flat-square)

[Quick Start](#quick-start) · [Features](#features) · [User Guide (Chinese)](../docs/usage.md) · [Report an Issue](https://github.com/sheetung/rviz-web/issues)

<img src="../img/1.png" alt="RVizWeb in use: 3D point clouds, UAV pose, Displays, a video overlay, and live data charts" width="100%">

*3D scenes, topic management, and live data in a single workspace.*

</div>

## Introduction

RVizWeb is a web visualization tool for ROS, designed for robot debugging, UAV monitoring, and algorithm demonstrations. The backend connects to the ROS network and the frontend displays data in a browser, so viewers do not need to install a desktop visualization client.

The project uses **Vue 3 + Three.js** for its interface and 3D scenes, and **FastAPI + rclpy** to read and publish ROS messages, with real-time data transported over WebSocket. It provides RViz-style Displays, Fixed Frame settings, and camera tools, along with `.rvizweb` configurations for different robots and tasks.

> The current backend uses rclpy, and ROS 1 adaptation is on the roadmap. The deployment instructions below describe the existing implementation; custom messages require the corresponding workspace to be installed and sourced.

## Contents

- [Features](#features)
- [Preview](#preview)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Development and Contributing](#development-and-contributing)
- [Documentation and Roadmap](#documentation-and-roadmap)
- [Community and Feedback](#community-and-feedback)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## Features

| Feature | Description |
| --- | --- |
| 3D visualization | Point clouds, laser scans, odometry, paths, markers, and occupancy grids, with TF transforms |
| Displays management | Discover topics from the ROS graph, add displays by topic or type, and control visibility and styling independently |
| Point clouds and paths | Points / Boxes rendering, size controls, and sparse point display; configurable path width and color |
| Pose and targets | UAV pose and trajectory display, target previews, and explicit `PoseStamped` publishing |
| Camera and interaction | Orbit controls, selection, focus, view presets, 2D pose estimation, and 2D goal tools |
| Live charts | Select numeric topic fields, overlay curves, zoom the time window, pause the view, and return to live data |
| Video and capture | RTSP video overlays, PNG screenshots, and WebM recording of the 3D canvas |
| Configuration and layout | Save Displays, frames, camera, layout, and theme, with configuration validation, migration, and backups |

### Main Supported Display Messages

| Message type (current backend) | Purpose |
| --- | --- |
| `sensor_msgs/msg/PointCloud2` | Point clouds and voxels |
| `sensor_msgs/msg/LaserScan` | Laser scans |
| `nav_msgs/msg/Odometry` | Odometry and robot pose |
| `nav_msgs/msg/Path` | Planned paths and trajectories |
| `visualization_msgs/msg/Marker` | Individual visualization markers |
| `visualization_msgs/msg/MarkerArray` | Multiple visualization markers |
| `nav_msgs/msg/OccupancyGrid` | Occupancy grids |

The application automatically subscribes to `/tf` and `/tf_static` to transform data into the selected Fixed Frame. If a TF chain is unavailable, the corresponding Display reports the reason and hides data that cannot be placed correctly. The map file settings entry is temporarily hidden; the underlying OccupancyGrid rendering support remains available.

## Preview

<details>
<summary>Show another screenshot of the application</summary>

![RVizWeb interface preview](../img/2.png)

</details>

## Quick Start

ROS1 has a dedicated adapter and deployment configuration; see the [ROS1 deployment and testing guide (Chinese)](../docs/ros1-testing.md). The defaults below use ROS2 Humble. Each backend runs one ROS runtime selected by `ROS_SETUP_PATHS`; `/ws/ros1` and `/ws/ros2` validate the selected backend version.

### Option 1: Run Locally

Prepare a working ROS 2 environment and the following dependencies:

| Dependency | Requirement |
| --- | --- |
| ROS 2 | Installed and able to discover the target topics; the default setup path is `/opt/ros/humble/setup.bash` |
| Node.js | `^20.19.0` or `>=22.12.0`, matching the current frontend build dependencies |
| Python | 3.10–3.12, with ROS 2's `rclpy` importable |
| uv | Python environment management; if missing, the script uses curl to run the official installer |
| FFmpeg | RTSP transcoding; dependency synchronization checks for it and attempts installation through the system package manager if missing |

```bash
git clone https://github.com/sheetung/rviz-web.git
cd rviz-web
cp .env.example .env
```

Edit `.env` to set the ROS 2 environment path and match the robot's communication domain:

```dotenv
ROS_SETUP_PATHS="/opt/ros/humble/setup.bash"
ROS_DOMAIN_ID=0
APP_HOST=127.0.0.1
APP_PORT=3000
```

For custom messages, append the workspace's `install/setup.bash` to `ROS_SETUP_PATHS`, separating paths with spaces. Set `APP_HOST` to `0.0.0.0` for LAN access.

```bash
# Run on first installation or after dependency changes; system packages may require sudo
./start.sh sync

# Build the frontend and start the services
./start.sh local
```

Open **http://localhost:3000/** in your browser. From another device, use the host machine's LAN IP address. Press `Ctrl+C` to stop the services.

### Option 2: Docker Compose

For Linux hosts with Docker Engine and Compose installed. After cloning the repository and preparing `.env`, run:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

Open **http://localhost:3000/**. The container uses host networking to join the ROS 2 DDS network, and `rvizweb_configs/` is mounted for persistent configuration storage.

- The container uses ROS 2 Humble. Install or build custom messages in the `Dockerfile`.
- Compose uses `network_mode: host`; DDS discovery on Docker Desktop requires separate configuration and verification.
- Nginx inside the container listens on port `3000`; the local startup variables `APP_HOST` / `APP_PORT` do not control the container's listening address.
- Stop with `docker compose down`. After updating the code, run the build-and-start command again.

> **Access scope:** The application does not provide login authentication. Use a trusted LAN, VPN, or firewall, and do not expose service ports directly to the public Internet. ROS publishing is allowed only on `/goal_pose`, `/initialpose`, and `/cmd_vel` by default; explicitly add other topics to the publish allowlist in `.env`.

## Usage

1. **Check connectivity:** Start the robot or replay data, and confirm that `ros2 topic list -t` in the backend environment lists the target topics.
2. **Add displays:** Select `Add` in Displays and choose a data source by topic or display type.
3. **Set the frame:** Select a Fixed Frame in `Global Options`, then configure the odometry source, UAV model, and trajectory as needed.
4. **Inspect and interact:** Adjust point cloud styles, camera, and charts. For targets, `Show` previews the point; `Publish` sends a ROS message.
5. **Save the workspace:** Save a `.rvizweb` file in settings to restore topics, view, layout, and theme later.

### Common Commands

```bash
./start.sh                 # Default local mode
./start.sh dev             # Frontend development with hot reload
RVIZWEB_CONFIG=default.rvizweb ./start.sh local
```

The default configuration, [`rvizweb_configs/default.rvizweb`](../rvizweb_configs/default.rvizweb), contains generic interface settings without robot-specific topics. Save separate configurations for different tasks, then use `RVIZWEB_CONFIG` to select an existing file.

### Configuration and Troubleshooting

- **Topics are missing:** Check `ROS_DOMAIN_ID` and `ROS_SETUP_PATHS`, and confirm that the backend sourced the correct workspace.
- **Objects are misplaced or missing:** Check the Fixed Frame, TF chain, and status of the corresponding Display.
- **RTSP connection fails:** Confirm that the backend can run FFmpeg and reach the video source. The default policy blocks private networks and other restricted addresses; maintainers must adjust the policy for trusted cameras in `backend/app/core/config.py` and redeploy.
- **More details:** See the [complete user guide (Chinese)](../docs/usage.md) for topic discovery, configuration fields, video endpoints, logging, separate deployment, and FAQs.

## Project Structure

```text
rviz-web/
├── backend/             # FastAPI, rclpy, configuration and video services
├── frontend/            # Vue 3, Three.js, Displays and data panels
├── docker/              # Nginx and container startup configuration
├── docs/                # User guide and test records
├── img/                 # Project screenshots
├── readme/              # README translations
├── rvizweb_configs/     # Reusable workspace configurations
├── .env.example         # Environment variable template
├── docker-compose.yml   # Docker Compose deployment
├── install.sh           # Dependency installation and synchronization
├── start.sh             # Local and development startup
└── release.sh           # Independent frontend/backend releases
```

## Development and Contributing

Use [Issues](https://github.com/sheetung/rviz-web/issues) to report bugs or discuss features, and submit [Pull Requests](https://github.com/sheetung/rviz-web/pulls) to improve the code and documentation.

1. Fork the repository and create a feature branch.
2. Develop with `./start.sh dev`, preserving `.rvizweb` configuration compatibility.
3. Run the relevant checks below and add verification appropriate to your changes.
4. Submit a PR describing the problem, changes, and validation results. Include screenshots for interface changes when helpful.

**Frontend checks** (run inside `frontend/`):

```bash
npm run lint:check
npm test
npm run build
```

**Backend checks** (source the ROS 2 environment, then run inside `backend/`):

```bash
uv run pytest -q
uv run flake8 app
uv run python -m compileall -q app
```

For component integration, system messages, configuration extensions, and independent releases, see [development notes](../docs/usage.md#开发说明) and [verification and releases](../docs/usage.md#验证) in the Chinese guide.

## Documentation and Roadmap

| Document | Contents |
| --- | --- |
| [User and developer guide (Chinese)](../docs/usage.md) | Full feature, configuration, deployment, troubleshooting, and development details |
| [Chinese README](../README.md) | Chinese project overview |
| [Changelog](../CHANGELOG.md) | Version history |
| [ROS 2 Bag test records](../docs/ros2-bag-benchmark.md) | Replay tests and observations |
| [ROS 2 / RTSP test records](../docs/ros2-rtsp-benchmark.md) | Visualization and video scenario test records |

Planned work:

- Add ROS 1 adaptation to support more ROS environments.
- Improve TF past/future extrapolation error states and Display lifecycle coverage.
- Add automated integration tests for WebSocket reconnection and real ROS 2 graphs.
- Remove legacy layouts and example components to reduce maintenance effort.

## Community and Feedback

- **Bugs and suggestions:** [GitHub Issues](https://github.com/sheetung/rviz-web/issues). Include reproduction steps, ROS 2 version, deployment method, and relevant logs.
- **Code contributions:** [Pull Requests](https://github.com/sheetung/rviz-web/pulls).
- **QQ group:** 965312424.

[![QQ Group](https://img.shields.io/badge/QQ_Group-965312424-green)](https://qm.qq.com/cgi-bin/qm/qr?k=en97YqjfYaLpebd9Nn8gbSvxVrGdIXy2&jump_from=webapi&authKey=41BmkEjbGeJ81jJNdv7Bf5EDlmW8EHZeH7/nktkXYdLGpZ3ISOS7Ur4MKWXC7xIx)

If RVizWeb helps your work, consider giving it a Star or Forking the repository to contribute.

## Acknowledgements

Thanks to **[lovelyyoshino/RVIZ-RQT-VISUAL](https://github.com/lovelyyoshino/RVIZ-RQT-VISUAL)** for the project foundation and reference. The original copyright notice is preserved in [LICENSE](../LICENSE).

We also thank the open-source tools and communities used by this project: ROS 2 / rclpy, Vue, Three.js, Element Plus, FastAPI, FFmpeg, and uv, along with everyone who contributes code, reports issues, and shares their experience.

## License

This project is licensed under the **[BSD 3-Clause License](../LICENSE)**. See `LICENSE` for the full terms and copyright notice.
