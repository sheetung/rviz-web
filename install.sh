#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGEMENT_DIR="$PROJECT_ROOT/backend/management"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
ENV_FILE="$PROJECT_ROOT/.env"

log() { printf '[rvizweb] %s\n' "$*"; }
fail() { printf '[rvizweb] ERROR: %s\n' "$*" >&2; exit 1; }

check_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

ensure_env() {
  if [[ -f "$ENV_FILE" ]]; then
    chmod 0600 "$ENV_FILE"
    return
  fi

  local env_example="$PROJECT_ROOT/.env.example"
  [[ -f "$env_example" ]] || fail "Missing environment template: $env_example"
  cp "$env_example" "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  log "Created $ENV_FILE from $env_example"
}

load_env() {
  local line key value first last
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || fail "Invalid .env entry: $line"
    key="${line%%=*}"
    [[ "$key" != ROS_VERSION ]] || fail "ROS_VERSION must come from ROS setup, not .env"
    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    first="${value:0:1}"
    last="${value: -1}"
    if [[ "$first" == "'" || "$first" == '"' ]]; then
      [[ "$last" == "$first" ]] || fail "Unterminated quote for $key in $ENV_FILE"
      value="${value:1:${#value}-2}"
    fi
    export "$key=$value"
  done < "$ENV_FILE"
}

load_ros() {
  source "$PROJECT_ROOT/scripts/ros-environment.sh"
  load_ros_environment || fail "Invalid ROS environment"
}

ensure_uv() {
  command -v uv >/dev/null 2>&1 && return

  check_command curl
  log "uv not found; installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  hash -r
  command -v uv >/dev/null 2>&1 || fail "uv installation completed but uv is not available in PATH"
}

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  check_command sudo
  sudo "$@"
}

ensure_ffmpeg() {
  local ffmpeg_command="ffmpeg"
  command -v "$ffmpeg_command" >/dev/null 2>&1 && return

  log "ffmpeg not found; installing ffmpeg"
  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update
    run_as_root apt-get install -y ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    run_as_root dnf install -y ffmpeg
  elif command -v yum >/dev/null 2>&1; then
    run_as_root yum install -y ffmpeg
  elif command -v pacman >/dev/null 2>&1; then
    run_as_root pacman -Sy --noconfirm ffmpeg
  else
    fail "ffmpeg is missing and no supported package manager was found; install ffmpeg manually"
  fi

  hash -r
  command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg installation completed but ffmpeg is not available in PATH"
}

check_management_python() {
  "$MANAGEMENT_DIR/.venv/bin/python" -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 13); import fastapi, uvicorn'
  if [[ "$ROS_VERSION" == 1 && "${ROS1_AUTOSTART_MASTER:-false}" == true ]]; then
    "$MANAGEMENT_DIR/.venv/bin/python" -c 'import rosmaster.master' \
      || fail "Automatic Master startup requires rosmaster in the management Python; use an existing Master or install compatible rosmaster packages"
  fi
}

install_dependencies() {
  log "Installing/updating backend dependencies"
  (
    cd "$MANAGEMENT_DIR"
    if [[ ! -d .venv ]]; then
      # Management no longer imports rospy/rclpy; ROS C++ and Python versions are independent.
      uv venv --python '>=3.10,<3.13' --system-site-packages .venv
    fi
    local -a optional_dependencies=()
    if [[ "$ROS_VERSION" == 1 && "${ROS1_AUTOSTART_MASTER:-false}" == true ]]; then
      optional_dependencies=(--extra ros1)
    fi
    VIRTUAL_ENV="$MANAGEMENT_DIR/.venv" uv sync --active --frozen --no-dev "${optional_dependencies[@]}"
    check_management_python

  )

  log "Installing/updating frontend dependencies"
  (cd "$FRONTEND_DIR" && npm ci)
}

main() {
  ensure_env
  load_env
  source "$PROJECT_ROOT/scripts/frontend-runtime.sh"
  ensure_frontend_runtime || fail "Unable to install pinned frontend runtime"
  load_ros
  ensure_uv
  check_command npm
  check_command ss
  check_command setsid
  check_command cmake
  check_command c++
  ensure_ffmpeg
  install_dependencies
  "$PROJECT_ROOT/backend/scripts/build.sh"
  log "Installation complete"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
