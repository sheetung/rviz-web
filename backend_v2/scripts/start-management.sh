#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$root/start.sh"
load_env
export RVIZWEB_ROS_BACKEND=v2
cd "$root"
exec "$root/backend/.venv/bin/python" -m uvicorn app.main:app --app-dir "$root/backend" \
  --host 127.0.0.1 --port "${RVIZWEB_MANAGEMENT_PORT:-8000}" --ws websockets
