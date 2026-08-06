#!/usr/bin/env bash
set -Eeuo pipefail

source /opt/ros/humble/setup.bash

backend_pid=""
nginx_pid=""

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$nginx_pid" ]] && kill -TERM "$nginx_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill -TERM "$backend_pid" 2>/dev/null || true
  [[ -n "$nginx_pid" ]] && wait "$nginx_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && wait "$backend_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

/app/backend/.venv/bin/uvicorn app.main:app \
  --host "${BACKEND_HOST:-127.0.0.1}" \
  --port 8000 &
backend_pid=$!

nginx -g "daemon off;" &
nginx_pid=$!

wait -n "$backend_pid" "$nginx_pid"
