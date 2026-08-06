# RVizWeb

> Current release: `v1.3.0`

![RVizWeb](img/1.png)

![RVizWeb](img/2.png)

[中文](./README.md)

RVizWeb is a browser-based visualization frontend for ROS2, supporting point clouds, odometry, paths, markers, and more. It provides UAV pose display, desired target input, real-time data charts, and RViz-style Displays management. The project consists of a Vue 3 + Three.js frontend and a FastAPI + rclpy backend.

## Features

- RViz-style Displays:
  - Read topics from the current ROS2 graph and add display items.
  - Toggle visibility with an eye icon.
  - Add, delete, and modify topics; message types for added Displays automatically follow ROS2 topics without separate editing.
  - Add dialog supports `By topic` and `By display type`; the type list only includes types actually present in the current ROS2 graph.
  - Hiding or deleting a Display clears its message cache; TF updates will not recreate hidden objects.
  - Each Display can save independent configuration.
- 3D Visualization:
  - `sensor_msgs/msg/PointCloud2`
  - `sensor_msgs/msg/LaserScan`
  - `nav_msgs/msg/Odometry`
  - `nav_msgs/msg/Path`
  - `visualization_msgs/msg/Marker`
  - `visualization_msgs/msg/MarkerArray`
  - `nav_msgs/msg/OccupancyGrid`
  - Auto-subscribes to `/tf` and `/tf_static`, transforming display data to the selected Fixed Frame.
  - Hides data with unresolvable TF chains and shows the reason on the corresponding Display.
- RViz-style Tools & Camera:
  - Top toolbar provides Move Camera, Select, Focus, 2D Pose Estimate, and 2D Goal.
  - Orbit controls: left-click to rotate, middle-click to pan, right-click drag or scroll to zoom.
  - Shortcuts: `M` Move, `S` Select, `F` Focus, `P` 2D Pose, `G` 2D Goal, `Esc` Cancel.
  - Selected objects show a cyan bounding box; top-down preset uses an orthographic camera.
  - Toolbar supports capturing the current 3D canvas as PNG.
  - Supports recording the 3D canvas at 30 FPS; click again to stop and download as WebM. Selects VP9, VP8, or plain WebM based on browser capabilities.
  - The RTSP tool follows the same popover interaction as System Status. Clicking it only opens connection settings and status; it does not create a video window.
  - Titleless, borderless video appears at its saved position only after FFmpeg successfully probes the first frame. Connection failures, timeouts, and sources without a video track produce a system message without an empty window.
  - Drag the video itself to move it. Resize is at the top left, close at the top right, reconnect at the bottom left, and settings at the bottom right; controls appear on hover.
  - FFmpeg converts RTSP to browser-compatible MJPEG while the playback URL contains only a short-lived session ID. Temporary stalls reconnect automatically while preserving the last frame.
- Point Cloud & Path Styles:
  - PointCloud2 supports per-topic `Points` or `Boxes` rendering with independent `Point Size` or `Box Size` controls.
  - `Boxes` uses instanced cubes for occupied voxel maps, while `Points` is intended for high-frequency, large point clouds.
  - Path supports per-topic line width and color.
  - Marker/MarkerArray updates by `(ns,id)` and supports `DELETE`, `DELETEALL`, lifetimes, and common geometry types. Unsupported types report an error instead of rendering a false fallback shape.
  - MarkerArray supports color override and opacity; leaving color empty uses the message's own color.
- UAV Pose:
  - Select an odom topic in the position panel as the UAV model pose source.
  - The built-in UAV model is hidden by default. Enable it with the `Show UAV model` checkbox after selecting odom; the choice is saved in `.rvizweb`.
  - Hiding the built-in model does not affect custom robot models provided through Marker or MarkerArray topics.
  - The current odom subscription is protected from Display hiding to prevent the UAV model from stopping.
- Desired Target:
  - Enter target `Topic`, `X/Y/Z` below the position info.
  - `Show` only previews the target in the point cloud view.
  - `Publish` sends a `geometry_msgs/msg/PoseStamped` to the configured topic.
  - Default orientation is `+X`.
  - Publish status reads the current WebSocket connection in real time, avoiding stale "disconnected" reports from component initialization.
- Layout & View:
  - Right panel supports manual height dragging.
  - Point cloud view and right panel ratio can be saved.
  - 3D canvas resizes in real time with split pane and bottom dock dimensions, avoiding blank areas after dragging.
  - Grid, axes, view preset, and camera state can be saved.
- Data Charts:
  - Displayed in a resizable dock below the 3D view, collapsed by default at startup.
  - Select numeric fields from topics in the current ROS2 graph; supports multi-curve visibility toggling and deletion.
  - Supports 10-second to 10-minute time ranges, scroll wheel zoom, drag to view history, and return to real time.
  - Pause only freezes the display; data continues to buffer in the background.
  - X-axis shows relative time: seconds for short windows, auto-switches to minutes for 1 minute and above.

> The map file settings entry is temporarily hidden. The underlying display logic and existing config fields for `nav_msgs/msg/OccupancyGrid` are preserved for future restoration.

## Topic Discovery

When adding topics in Displays, the current ROS2 graph is read:

1. The backend first runs `ros2 topic list -t` to get topics and types.
2. If the CLI is unavailable or times out, it falls back to rclpy topic discovery.
3. The frontend Add panel and topic dropdowns refresh the topic list when opened, or click `Refresh` manually.

Topic sources are the current ROS2 system and `.rvizweb` config files, not `.env` or hardcoded frontend defaults.

## Configuration Files

Configuration files are stored in:

```text
rvizweb_configs/*.rvizweb
```

The generic configuration is:

```text
rvizweb_configs/default.rvizweb
```

`default.rvizweb` only contains generic UI settings and is not tied to any specific robot topics. Create separate configurations for different robots or tasks, then select one at startup with:

```bash
RVIZWEB_CONFIG=<name>.rvizweb ./start.sh local
```

The startup script validates that the config file exists and uses the `.rvizweb` suffix, then passes it to the frontend via `VITE_RVIZWEB_CONFIG`.

Saving uses atomic replacement via a temp file in the same directory. Backups of overwritten and deleted configs are stored in `rvizweb_configs/backups/`. The backend validates config version, structure, filename, and size; the frontend keeps its current state unchanged on read failure.

The settings panel supports:

- Saving the current frontend state as `.rvizweb`
- Loading existing configs
- Deleting configs
- Switching between dark and light themes, saved with the config
- Auto-compat with user-entered `.rviz` suffix, saved as `.rvizweb`

Configuration files primarily include:

- `fixedFrame`
- `followFrame` (optional; follows TF frame translation without rotating the camera view)
- `scene.showGrid`
- `scene.showAxes`
- `scene.viewPreset`
- `scene.camera`
- `layout.sceneWidth`
- `layout.panelHeights`
- `layout.collapsedPanels`
- `appearance.theme`
- `video.sourceUrl`
- `video.visible`
- `video.layout.x/y/width/height`
- `goal.topic`
- `goal.x/y/z`
- `position.odomTopic`
- `laser`
- `map`
- `displays`
- `extensions` (namespace for third-party extensions)

The schema is strictly versioned. RTSP usernames, passwords, and query tokens are
never persisted in `video.sourceUrl`; credential-bearing URLs live only for the
current browser page lifetime.

Backend config API:

```text
GET    /api/v1/configs
GET    /api/v1/configs/{name}
POST   /api/v1/configs/{name}
DELETE /api/v1/configs/{name}
```

RTSP video API:

```text
GET    /api/v1/video/status
POST   /api/v1/video/sessions
GET    /api/v1/video/stream/{session_id}
DELETE /api/v1/video/sessions/{session_id}
```

## Getting Started

Before first use, copy the environment config example and modify as needed:

```bash
cd <your_workspace>/rviz-web
cp .env.example .env
# Usually only ROS_DOMAIN_ID needs changing; use APP_HOST=0.0.0.0 for LAN access
```

When environment variables change after an upgrade, copy `.env.example` again and
fill in the current device settings. Retired variables are not migrated.

The backend uses [uv](https://docs.astral.sh/uv/) for Python environment management. Run the following on first install or when dependencies change:

```bash
./start.sh sync
```

Normal local startup:

```bash
./start.sh local
```

Running without arguments also defaults to local mode:

```bash
./start.sh
```

Normal mode builds the frontend for production first, then serves pages via a static preview server without watching source files. For frontend development with hot reload:

```bash
./start.sh dev
```

Local mode requires:

- ROS2 environment available
- Node.js 20.19+
- Python 3.10+
- FFmpeg (converts RTSP into browser-compatible MJPEG)
- curl (if `uv` is not installed, the startup script will install it via the official install script)

The startup script reads `.env` from the project root, loads the ROS2 environment, validates the default `.rvizweb` config and ports, waits for frontend and backend health checks, and writes all output to `logs/`. The browser uses `APP_HOST:APP_PORT`; the backend port is parsed from `ROS_WS_URL` and defaults to `8000` when it is unset. With `APP_HOST=0.0.0.0`, the script prints the detected LAN addresses. Startup failures exit immediately; Ctrl+C stops the entire frontend and backend process group.

The browser tab and top-left title can be changed in `.env`:

```env
VITE_APP_TITLE=RVizWeb
```

Normal deployments do not require a backend IP, API URL, WebSocket URL, or CORS
configuration. Use this advanced override only for a deliberately separated frontend
and backend:

```env
ROS_WS_URL=ws://192.168.31.16:8000/ws
```

When unset, the frontend uses the same-origin `/ws` endpoint. Restart the Vite dev
server or rebuild normal mode after changing a Vite environment variable.
The current `/ws` backend uses `rclpy` and supports ROS2 only. A future ROS1
integration should use a dedicated `/ws/ros1` adapter route; changing the path or
adding a query parameter alone does not provide ROS1 support.

Click the camera monitor button in the point cloud toolbar to open the connection popover below the button, then enter a source such as:

```text
rtsp://192.168.1.66:8554/1
```

Saving a `.rvizweb` configuration stores overlay layout and a credential-free
RTSP URL. Usernames, passwords, query parameters, and fragments remain only in
the current page and must be entered again after a reload.

Connect waits for the backend to receive a valid first frame. The video window is created only after that probe succeeds; failures and missing video are reported through the page notification system.

Backend transcoding can be tuned with `RTSP_TRANSPORT`, `RTSP_FRAME_RATE`,
`RTSP_WIDTH`, `RTSP_JPEG_QUALITY`, `RTSP_STARTUP_TIMEOUT`,
`RTSP_SESSION_TTL`, the `RTSP_MAX_*` process limits, and `FFMPEG_PATH`.
Private destinations are denied by default; use `RTSP_ALLOWED_HOSTS` for exact
camera hosts or explicitly enable `RTSP_ALLOW_PRIVATE_NETWORKS`. Hostnames are
pinned to the validated IP before FFmpeg starts, preventing DNS rebinding during
a second resolution.

In normal mode, re-run `./start.sh` after changes to rebuild the frontend. In dev mode, changes take effect on Vite restart or environment reload.

The application listens on `127.0.0.1` by default. For LAN access, only set
`APP_HOST=0.0.0.0`; the startup script derives proxy targets, health-check addresses,
and allowed browser origins. The application does not provide login authentication;
restrict access with a firewall, trusted LAN, or VPN, and never expose its service
ports directly to the public Internet.

ROS publishing is restricted by `ROS_PUBLISH_TOPIC_ALLOWLIST` and
`ROS_PUBLISH_TYPE_ALLOWLIST`; extend these lists explicitly for robot-specific
control topics.

The script sources setup.bash files in the order specified by `ROS2_SETUP_PATHS` in `.env`:

```bash
source /opt/ros/humble/setup.bash
source <your_workspace>/install/setup.bash
```

Starting separately:

> Generally not recommended

```bash
cd backend
uv venv --system-site-packages .venv
VIRTUAL_ENV="$PWD/.venv" uv sync --active
source /opt/ros/humble/setup.bash
source <your_workspace>/install/setup.bash
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm ci
VITE_RVIZWEB_CONFIG=default.rvizweb npm run build
npm run preview -- --host 127.0.0.1 --port 3000
```

Access URLs:

- Frontend: `http://localhost:3000/`
- Backend API: `http://localhost:8000/`
- Backend docs: `http://localhost:8000/docs`

The frontend uses same-origin `/api` and `/ws` proxies, so reverse-proxy and
HTTPS deployments do not expose the backend port to the browser. Set
`VITE_BACKEND_PUBLIC_URL` only for a deliberately separated backend deployment.

## FAQ

### File Watch Limit

This may only occur in dev mode. If `./start.sh dev` reports:

```text
OS file watch limit reached
ENOSPC: System limit for number of file watchers reached
```

Temporarily increase system watch limits:

```bash
sudo sysctl fs.inotify.max_user_watches=524288
sudo sysctl fs.inotify.max_user_instances=1024
```

You can also use `CHOKIDAR_USEPOLLING=true` polling mode in `.env`. Normal `./start.sh` does not watch files and is not affected by this limit.

### No Topics in Displays

First confirm that topics are visible in the ROS2 environment:

```bash
ros2 topic list -t
```

If the CLI shows topics but the frontend does not, check that the backend sourced the correct ROS2 workspace, then restart the backend.

### Config Changes Not Taking Effect

Before saving a config, the current view, layout ratio, and panel heights are captured. After loading a config, Fixed Frame, Displays, view, grid, axes, goal point, odom topic, and layout are restored.

### Screenshot or Recording Not Downloading

Screenshots and recordings use the browser's download capability. Ensure the site has download permission. Recording relies on `MediaRecorder` and `canvas.captureStream()`; current versions of Chrome, Edge, or Firefox are recommended. Recordings use the WebM format and do not include the toolbar or right panel.

### RTSP Video Cannot Connect

Verify that FFmpeg on the backend host can reach and read the camera:

```bash
ffmpeg -rtsp_transport tcp -i 'rtsp://<camera>/<path>' -t 3 -f null -
```

The backend, not the browser, connects to RTSP. If a camera only supports UDP, set `RTSP_TRANSPORT=udp` and restart. Expose the transcoding API only on trusted networks.

## Verification

Frontend build:

```bash
cd frontend
npm run build
```

Frontend static check:

```bash
cd frontend
npm run lint:check
```

Backend syntax check:

```bash
cd backend
uv run pytest -q
uv run flake8 app
uv run python -m compileall -q app
```

Frontend unit tests currently cover TF, config state, RTSP redaction, video
frames, and backend URL construction:

```bash
cd frontend
npm test
```

## Directory Structure

```text
RVIZ-RQT-VISUAL/
├── backend/                  # FastAPI + rclpy backend
│   └── app/
│       ├── api/v1/           # ROS, config, and visualization APIs
│       └── services/         # rosbridge and ROS2 services
├── frontend/                 # Vue 3 + Three.js frontend
│   └── src/
│       ├── components/RViz/  # 3D scene, Displays, controllers
│       ├── components/panels # Settings, position info, desired target, and data charts
│       ├── components/layout # Main layout and panel containers
│       ├── composables/      # ROS bridge connection and state
│       └── services/         # Backend API wrappers
├── rvizweb_configs/          # .rvizweb config file directory
├── .env                      # Runtime environment config (no ROS topic names)
├── start.sh                  # Startup script
└── README.md
```

## Development Notes

- Adding a new right panel: wire the component into `MainLayout.vue` and add persistent state to the config snapshot.
- Adding a new visualization type: extend `Scene3D.vue` subscription and rendering logic first, then add corresponding config items in Displays.
- Adding a new backend endpoint: place it in `backend/app/api/v1/`; frontend wrappers go in `frontend/src/services/api.js`.
- Route success, info, warning, and error notices through `frontend/src/composables/useSystemMessage.js`; it owns durations, close buttons, duplicate suppression, and backend error parsing.
- Keep config key names stable to avoid breaking existing `.rvizweb` files.

## Roadmap

- Add strict past/future extrapolation error states for TF and continue covering Display lifecycles.
- Add automated integration tests for WebSocket reconnection and real ROS2 graphs.
- Clean up unreferenced legacy layouts and example components to further reduce maintenance costs.

## Acknowledgements

Thanks to [lovelyyoshino/RVIZ-RQT-VISUAL](https://github.com/lovelyyoshino/RVIZ-RQT-VISUAL) for the foundation and reference.

## Feedback & Feature Development

[![QQ Group](https://img.shields.io/badge/QQ群-965312424-green)](https://qm.qq.com/cgi-bin/qm/qr?k=en97YqjfYaLpebd9Nn8gbSvxVrGdIXy2&jump_from=webapi&authKey=41BmkEjbGeJ81jJNdv7Bf5EDlmW8EHZeH7/nktkXYdLGpZ3ISOS7Ur4MKWXC7xIx)
