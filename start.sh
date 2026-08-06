#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
ENV_FILE="$PROJECT_ROOT/.env"
BACKEND_PID=""
FRONTEND_PID=""

mkdir -p "$LOG_DIR"

log() { printf '[rvizweb] %s\n' "$*"; }
fail() { printf '[rvizweb] ERROR: %s\n' "$*" >&2; exit 1; }

load_env() {
  [[ -f "$ENV_FILE" ]] || return

  local line key value first last
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || fail "Invalid .env entry: $line"
    key="${line%%=*}"
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
  log "Loaded $ENV_FILE"
}

load_ros() {
  set +u
  local setup_file
  for setup_file in ${ROS2_SETUP_PATHS:-}; do
    [[ -f "$setup_file" ]] && source "$setup_file"
  done
  set -u
}

check_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

is_initialized() {
  (
    [[ -f "$ENV_FILE" ]] || exit 1
    command -v uv >/dev/null 2>&1 || exit 1
    command -v npm >/dev/null 2>&1 || exit 1
    command -v "${FFMPEG_PATH:-ffmpeg}" >/dev/null 2>&1 || exit 1
    [[ -x "$BACKEND_DIR/.venv/bin/python" ]] || exit 1
    [[ -d "$FRONTEND_DIR/node_modules" ]] || exit 1
  )
}

ensure_initialized() {
  is_initialized && return

  local install_script="$PROJECT_ROOT/install.sh"
  [[ -x "$install_script" ]] || fail "Installation script is missing or not executable: $install_script"
  log "Project is not initialized; running install.sh"
  "$install_script"
  hash -r
  is_initialized || fail "Installation completed but the project is still not initialized"
}

check_port() {
  local port="$1"
  if ss -ltn "sport = :$port" 2>/dev/null | grep -q LISTEN; then
    fail "Port $port is already in use"
  fi
}

validate_port() {
  local name="$1" port="$2"
  [[ "$port" =~ ^[0-9]+$ ]] || fail "$name must be a number: $port"
  (( port >= 1 && port <= 65535 )) || fail "$name must be between 1 and 65535: $port"
}

backend_port_from_ws_url() {
  local url="${1:-}"
  [[ -n "$url" ]] || { printf '8000'; return; }
  node -e '
    const url = new URL(process.argv[1]);
    if (url.protocol !== "ws:" && url.protocol !== "wss:") process.exit(1);
    process.stdout.write(url.port || (url.protocol === "wss:" ? "443" : "80"));
  ' "$url"
}

wait_for_http() {
  local url="$1" name="$2" pid="$3" timeout_seconds="${4:-60}"
  local max_attempts=$(( timeout_seconds * 5 ))

  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    kill -0 "$pid" 2>/dev/null || fail "$name exited during startup; see $LOG_DIR"
    # Health checks target loopback services and must never be routed through
    # HTTP_PROXY/HTTPS_PROXY inherited from the user's shell.
    curl --noproxy '*' -fsS "$url" >/dev/null 2>&1 && return 0

    if (( attempt % 20 == 0 )); then
      log "Still waiting for $name at $url ($attempt/$max_attempts)"
    fi

    sleep 0.2
  done

  fail "$name did not become ready within ${timeout_seconds}s: $url"
}

health_host_for_bind() {
  case "$1" in
    0.0.0.0) printf '127.0.0.1' ;;
    "::"|"::1") printf '[::1]' ;;
    *) printf '%s' "$1" ;;
  esac
}

default_cors_origins() {
  local app_host="$1" app_port="$2"
  local origins="http://localhost:$app_port,http://127.0.0.1:$app_port"
  local candidate

  if [[ "$app_host" != "0.0.0.0" && "$app_host" != "::" && "$app_host" != "127.0.0.1" && "$app_host" != "localhost" ]]; then
    origins+=",http://$app_host:$app_port"
  fi

  if [[ "$app_host" == "0.0.0.0" || "$app_host" == "::" ]]; then
    for candidate in $(hostname -I 2>/dev/null || true); do
      [[ "$candidate" == *:* ]] && continue
      origins+=",http://$candidate:$app_port"
    done
    candidate="$(hostname 2>/dev/null || true)"
    [[ -n "$candidate" ]] && origins+=",http://$candidate:$app_port"
  fi

  printf '%s' "$origins"
}

log_access_urls() {
  local app_host="$1" app_port="$2" candidate
  if [[ "$app_host" != "0.0.0.0" && "$app_host" != "::" ]]; then
    log "Application: http://$app_host:$app_port"
    return
  fi

  log "Application: http://127.0.0.1:$app_port"
  for candidate in $(hostname -I 2>/dev/null || true); do
    [[ "$candidate" == *:* ]] && continue
    log "LAN:         http://$candidate:$app_port"
  done
}

cleanup() {
  trap - INT TERM EXIT
  log "Stopping services"
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  for _ in {1..30}; do
    local alive=0
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
      [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && alive=1
    done
    [[ "$alive" -eq 0 ]] && return
    sleep 0.1
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    [[ -n "$pid" ]] && kill -KILL -- "-$pid" 2>/dev/null || true
  done
}

start_local() {
  local frontend_mode="${1:-local}"
  ensure_initialized
  check_command curl
  check_command uv
  check_command npm
  check_command node
  check_command ss
  check_command setsid
  load_env
  load_ros

  check_command "${FFMPEG_PATH:-ffmpeg}"

  local app_host="${APP_HOST:-127.0.0.1}"
  local app_port="${APP_PORT:-3000}"
  local backend_port
  backend_port="$(backend_port_from_ws_url "${ROS_WS_URL:-}")" || fail "Invalid ROS_WS_URL: ${ROS_WS_URL:-}"
  local backend_host_default="127.0.0.1"
  [[ -n "${ROS_WS_URL:-}" ]] && backend_host_default="0.0.0.0"
  local backend_host="$backend_host_default"
  local backend_health_host
  local frontend_health_host
  local default_rvizweb_config="${RVIZWEB_CONFIG:?Set RVIZWEB_CONFIG in $ENV_FILE}"
  backend_health_host="$(health_host_for_bind "$backend_host")"
  frontend_health_host="$(health_host_for_bind "$app_host")"
  export CORS_ORIGINS="${CORS_ORIGINS:-$(default_cors_origins "$app_host" "$app_port")}"
  validate_port APP_PORT "$app_port"
  validate_port ROS_WS_URL_PORT "$backend_port"
  [[ "$app_port" != "$backend_port" ]] || fail "APP_PORT and the ROS_WS_URL port must be different"
  check_port "$backend_port"
  check_port "$app_port"

  [[ "$default_rvizweb_config" == *.rvizweb ]] || fail "Default frontend config must use the .rvizweb suffix"
  [[ -f "$PROJECT_ROOT/rvizweb_configs/$default_rvizweb_config" ]] || fail "Default frontend config not found: rvizweb_configs/$default_rvizweb_config"
  "$BACKEND_DIR/.venv/bin/python" -c "import rclpy" || fail "rclpy is unavailable; check the ROS2 setup files"

  if [[ "$frontend_mode" == "local" ]]; then
    log "Building frontend for normal local use"
    (
      cd "$FRONTEND_DIR"
      VITE_RVIZWEB_CONFIG="$default_rvizweb_config" npm run build
    ) >"$LOG_DIR/frontend.log" 2>&1 || fail "Frontend build failed; see $LOG_DIR/frontend.log"
  fi

  trap cleanup INT TERM EXIT

  log "Starting backend on $backend_port"
  (
    cd "$BACKEND_DIR"
    exec setsid uv run --no-sync uvicorn app.main:app --host "$backend_host" --port "$backend_port"
  ) >"$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!

  log "Starting frontend on $app_port ($frontend_mode mode)"
  (
    cd "$FRONTEND_DIR"
    if [[ "$frontend_mode" == "dev" ]]; then
      export VITE_RVIZWEB_CONFIG="$default_rvizweb_config"
      export CHOKIDAR_USEPOLLING="${CHOKIDAR_USEPOLLING:-true}"
      export CHOKIDAR_INTERVAL="${CHOKIDAR_INTERVAL:-500}"
      exec setsid npm run dev -- --host "$app_host" --port "$app_port"
    fi
    exec setsid npm run preview -- --host "$app_host" --port "$app_port"
  ) >>"$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID=$!

  wait_for_http "http://$backend_health_host:$backend_port/health" backend "$BACKEND_PID" 120
  wait_for_http "http://$frontend_health_host:$app_port" frontend "$FRONTEND_PID" 120

  log_access_urls "$app_host" "$app_port"
  log "Config:      rvizweb_configs/$default_rvizweb_config"
  wait -n "$BACKEND_PID" "$FRONTEND_PID"
  fail "A service stopped unexpectedly; see $LOG_DIR"
}

show_help() {
  printf 'Usage: %s [local|dev|install|sync|help]\n' "$0"
  printf '  install  Install/update system, backend, and frontend dependencies\n'
  printf '  sync     Alias for install\n'
  printf '  local  Build and start for normal local use (default)\n'
  printf '  dev    Start with Vite hot reload for development\n'
}

main() {
  case "${1:-local}" in
    install|sync) "$PROJECT_ROOT/install.sh" ;;
    local) start_local local ;;
    dev) start_local dev ;;
    help|-h|--help) show_help ;;
    *) show_help; return 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
