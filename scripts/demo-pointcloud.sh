#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/start.sh"
load_env
load_ros
[[ "$ROS_VERSION" == 1 ]] || fail "This point cloud demo requires ROS1"
check_ros_python "$MANAGEMENT_DIR/.venv/bin/python" || fail "Run ./start.sh sync first"
"$MANAGEMENT_DIR/.venv/bin/python" "$PROJECT_ROOT/scripts/ros1-master.py" check \
  || fail "Start ./start.sh (or your ROS Master) before this demo"
exec "$MANAGEMENT_DIR/.venv/bin/python" "$PROJECT_ROOT/scripts/demo_pointcloud.py" "$@"
