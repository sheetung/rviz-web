#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Reuse the existing .env parser (it does not execute shell expressions).
source "$root/start.sh"
load_env
load_ros
exec "$root/backend_v2/build/ros$ROS_VERSION/rvizweb_native" "$@"
