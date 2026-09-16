#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$root/start.sh"
load_env
cd "$root"
exec "$root/backend/management/.venv/bin/python" -m uvicorn app.main:app --app-dir "$root/backend/management" \
  --host 127.0.0.1 --port "${RVIZWEB_MANAGEMENT_PORT:-8000}" --ws websockets
