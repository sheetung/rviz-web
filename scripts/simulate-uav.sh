#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/start.sh"
load_env
load_ros
# Limit numerical-library threads; a small live scan should not occupy every CPU.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
check_ros_python "$BACKEND_DIR/.venv/bin/python" \
  || fail "The simulator needs ROS Python and numpy in backend/.venv (independent of the C++ backend)."
if [[ "$ROS_VERSION" == 1 ]]; then
  "$BACKEND_DIR/.venv/bin/python" "$PROJECT_ROOT/scripts/ros1-master.py" check \
    || fail "Start the ROS1 Master before the simulator"
fi
exec "$BACKEND_DIR/.venv/bin/python" "$PROJECT_ROOT/scripts/simulate_uav.py" "$@"
