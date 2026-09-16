#!/usr/bin/env bash
set -Eeuo pipefail

export PATH="$HOME/.local/bin:$PATH"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGEMENT_DIR="$PROJECT_ROOT/backend/management"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
ENV_FILE="$PROJECT_ROOT/.env"
BACKEND_PID=""
NATIVE_PID=""
FRONTEND_PID=""
ROS_MASTER_PID=""
LOG_RUN_DIR=""
START_LOG_FILE=""
BACKEND_LOG_FILE=""
NATIVE_LOG_FILE=""
FRONTEND_LOG_FILE=""
LAST_STARTED_PID=""

log() {
  printf '[rvizweb] %s\n' "$*"
  [[ -z "$START_LOG_FILE" ]] || printf '[rvizweb] %s\n' "$*" >> "$START_LOG_FILE"
}

fail() {
  printf '[rvizweb] ERROR: %s\n' "$*" >&2
  [[ -z "$START_LOG_FILE" ]] || printf '[rvizweb] ERROR: %s\n' "$*" >> "$START_LOG_FILE"
  exit 1
}

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
  log "Loaded $ENV_FILE"
}

load_ros() {
  source "$PROJECT_ROOT/scripts/ros-environment.sh"
  load_ros_environment || fail "Invalid ROS environment"
}

configure_logging() {
  local enabled="${LOG_ENABLED:-false}"
  case "${enabled,,}" in
    false) return ;;
    true) ;;
    *) fail "LOG_ENABLED must be true or false: $enabled" ;;
  esac

  mkdir -p "$LOG_DIR"
  local timestamp candidate sequence=1
  timestamp="$(date '+%Y%m%d-%H%M%S')"
  candidate="$LOG_DIR/$timestamp"
  while ! mkdir "$candidate" 2>/dev/null; do
    ((sequence += 1))
    candidate="$LOG_DIR/$timestamp-$sequence"
  done
  LOG_RUN_DIR="$candidate"
  START_LOG_FILE="$LOG_RUN_DIR/start.log"
  BACKEND_LOG_FILE="$LOG_RUN_DIR/backend.log"
  NATIVE_LOG_FILE="$LOG_RUN_DIR/native.log"
  FRONTEND_LOG_FILE="$LOG_RUN_DIR/frontend.log"
  log "Logging to $LOG_RUN_DIR"
}

failure_output_hint() {
  local component="${1:-}"
  if [[ -n "$LOG_RUN_DIR" ]]; then
    case "$component" in
      native) printf 'see %s' "$NATIVE_LOG_FILE" ;;
      backend) printf 'see %s' "$BACKEND_LOG_FILE" ;;
      frontend) printf 'see %s' "$FRONTEND_LOG_FILE" ;;
      *) printf 'see %s' "$LOG_RUN_DIR" ;;
    esac
  else
    printf 'see the process output above'
  fi
}

run_with_optional_log() {
  local output_file="$1"
  shift
  if [[ -n "$output_file" ]]; then
    "$@" >>"$output_file" 2>&1
  else
    "$@"
  fi
}

start_in_background() {
  local output_file="$1"
  shift
  if [[ -n "$output_file" ]]; then
    "$@" >>"$output_file" 2>&1 &
  else
    "$@" &
  fi
  LAST_STARTED_PID=$!
}

build_frontend() {
  local default_rvizweb_config="$1"
  cd "$FRONTEND_DIR"
  VITE_RVIZWEB_CONFIG="$default_rvizweb_config" npm run build
}

run_backend() {
  local backend_host="$1" backend_port="$2"
  cd "$MANAGEMENT_DIR"
  exec setsid "$MANAGEMENT_DIR/.venv/bin/python" -m uvicorn app.main:app --host "$backend_host" --port "$backend_port" --ws websockets
}

run_native() {
  exec setsid "$PROJECT_ROOT/backend/build/ros$ROS_VERSION/rvizweb_native" --host 127.0.0.1 --port "$1"
}

run_ros_master() {
  exec setsid "$MANAGEMENT_DIR/.venv/bin/python" "$PROJECT_ROOT/scripts/ros1-master.py" run
}

ensure_ros_master() {
  [[ "$ROS_VERSION" == 1 ]] || return 0
  local helper="$PROJECT_ROOT/scripts/ros1-master.py"
  local python="$MANAGEMENT_DIR/.venv/bin/python"
  local autostart="${ROS1_AUTOSTART_MASTER:-false}"
  [[ "$autostart" == true || "$autostart" == false ]] || fail "ROS1_AUTOSTART_MASTER must be true or false"
  if "$python" "$helper" check >/dev/null 2>&1; then
    log "Using ROS1 Master: ${ROS_MASTER_URI:-http://127.0.0.1:11311}"
    return 0
  fi
  [[ "$autostart" == true ]] || fail "ROS1 Master unavailable: ${ROS_MASTER_URI:-http://127.0.0.1:11311}. Start your Master, correct ROS_MASTER_URI, or set ROS1_AUTOSTART_MASTER=true for a local Master."
  "$python" "$helper" validate-local || fail "Cannot start a remote ROS Master"
  log "Starting local ROS1 Master"
  start_in_background "$START_LOG_FILE" run_ros_master
  ROS_MASTER_PID="$LAST_STARTED_PID"
  for _ in {1..30}; do
    kill -0 "$ROS_MASTER_PID" 2>/dev/null || fail "Local ROS1 Master exited; check its output and run ./start.sh sync if dependencies are missing"
    "$python" "$helper" check >/dev/null 2>&1 && return 0
    sleep 0.2
  done
  fail "Local ROS1 Master did not become ready"
}

run_frontend() {
  local frontend_mode="$1" app_host="$2" app_port="$3" default_rvizweb_config="$4"
  cd "$FRONTEND_DIR"
  if [[ "$frontend_mode" == "dev" ]]; then
    export VITE_RVIZWEB_CONFIG="$default_rvizweb_config"
    export CHOKIDAR_USEPOLLING="${CHOKIDAR_USEPOLLING:-true}"
    export CHOKIDAR_INTERVAL="${CHOKIDAR_INTERVAL:-500}"
    exec setsid npm run dev -- --host "$app_host" --port "$app_port"
  fi
  exec setsid npm run preview -- --host "$app_host" --port "$app_port"
}

check_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

is_initialized() {
  (
    [[ -f "$ENV_FILE" ]] || exit 1
    command -v uv >/dev/null 2>&1 || exit 1
    check_frontend_runtime || exit 1
    command -v ffmpeg >/dev/null 2>&1 || exit 1
    [[ -x "$MANAGEMENT_DIR/.venv/bin/python" ]] || exit 1
    [[ -d "$FRONTEND_DIR/node_modules" ]] || exit 1
  )
}

ensure_initialized() {
  is_initialized && return

  local install_script="$PROJECT_ROOT/install.sh"
  [[ -x "$install_script" ]] || fail "Installation script is missing or not executable: $install_script"
  log "Project is not initialized; running install.sh"
  "$install_script"
  configure_frontend_runtime
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

wait_for_http() {
  local url="$1" name="$2" pid="$3" timeout_seconds="${4:-60}"
  local max_attempts=$(( timeout_seconds * 5 ))

  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    kill -0 "$pid" 2>/dev/null || fail "$name exited during startup; $(failure_output_hint "$name")"
    # Health checks target loopback services and must never be routed through
    # HTTP_PROXY/HTTPS_PROXY inherited from the user's shell.
    curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS "$url" >/dev/null 2>&1 && return 0

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
  for pid in "$FRONTEND_PID" "$BACKEND_PID" "$NATIVE_PID" "$ROS_MASTER_PID"; do
    [[ -n "$pid" ]] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  for _ in {1..30}; do
    local alive=0
    for pid in "$FRONTEND_PID" "$BACKEND_PID" "$NATIVE_PID" "$ROS_MASTER_PID"; do
      [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && alive=1
    done
    [[ "$alive" -eq 0 ]] && return
    sleep 0.1
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID" "$NATIVE_PID" "$ROS_MASTER_PID"; do
    [[ -n "$pid" ]] && kill -KILL -- "-$pid" 2>/dev/null || true
  done
}

start_local() {
  local frontend_mode="${1:-local}"
  source "$PROJECT_ROOT/scripts/frontend-runtime.sh"
  configure_frontend_runtime
  ensure_initialized
  check_command curl
  check_command uv
  check_command npm
  check_command node
  check_command ss
  check_command setsid
  load_env
  configure_logging
  load_ros

  check_command ffmpeg
  check_command cmake
  check_command c++

  local app_host="${APP_HOST:-127.0.0.1}"
  local app_port="${APP_PORT:-3000}"
  local backend_port
  backend_port="${RVIZWEB_MANAGEMENT_PORT:-8000}"
  local native_port="${RVIZWEB_NATIVE_PORT:-8082}"
  local backend_host_default="127.0.0.1"
  local backend_host="$backend_host_default"
  local backend_health_host
  local frontend_health_host
  local default_rvizweb_config="${RVIZWEB_CONFIG:?Set RVIZWEB_CONFIG in $ENV_FILE}"
  backend_health_host="$(health_host_for_bind "$backend_host")"
  frontend_health_host="$(health_host_for_bind "$app_host")"
  export CORS_ORIGINS="${CORS_ORIGINS:-$(default_cors_origins "$app_host" "$app_port")}"
  validate_port RVIZWEB_MANAGEMENT_PORT "$backend_port"
  validate_port APP_PORT "$app_port"
  [[ "$app_port" != "$backend_port" ]] || fail "APP_PORT must differ from the internal backend port $backend_port"
  check_port "$backend_port"
  check_port "$app_port"

  validate_port RVIZWEB_NATIVE_PORT "$native_port"
  [[ "$native_port" != "$app_port" && "$native_port" != "$backend_port" ]] || fail "Native, management and frontend ports must differ"
  check_port "$native_port"
  export ROS_V2_PROXY_TARGET="http://127.0.0.1:$native_port"

  [[ "$default_rvizweb_config" == *.rvizweb ]] || fail "Default frontend config must use the .rvizweb suffix"
  [[ -f "$PROJECT_ROOT/rvizweb_configs/$default_rvizweb_config" ]] || fail "Default frontend config not found: rvizweb_configs/$default_rvizweb_config"

  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  ensure_ros_master

  log "Incremental build of C++ backend for ROS $ROS_VERSION"
  run_with_optional_log "$NATIVE_LOG_FILE" "$PROJECT_ROOT/backend/scripts/build.sh" --startup \
    || fail "Native build failed; $(failure_output_hint native)"
  start_in_background "$NATIVE_LOG_FILE" run_native "$native_port"
  NATIVE_PID="$LAST_STARTED_PID"
  wait_for_http "http://127.0.0.1:$native_port/api/v2/ros/health" native "$NATIVE_PID" 60

  if [[ "$frontend_mode" == "local" ]]; then
    log "Building frontend for normal local use"
    run_with_optional_log "$FRONTEND_LOG_FILE" build_frontend "$default_rvizweb_config" \
      || fail "Frontend build failed; $(failure_output_hint frontend)"
  fi

  log "Starting backend on $backend_port (management)"
  start_in_background "$BACKEND_LOG_FILE" run_backend "$backend_host" "$backend_port"
  BACKEND_PID="$LAST_STARTED_PID"

  log "Starting frontend on $app_port ($frontend_mode mode)"
  start_in_background "$FRONTEND_LOG_FILE" run_frontend \
    "$frontend_mode" "$app_host" "$app_port" "$default_rvizweb_config"
  FRONTEND_PID="$LAST_STARTED_PID"

  wait_for_http "http://$backend_health_host:$backend_port/health" backend "$BACKEND_PID" 120
  wait_for_http "http://$frontend_health_host:$app_port" frontend "$FRONTEND_PID" 120
  wait_for_http "http://$frontend_health_host:$app_port/api/v2/ros/health" native-proxy "$NATIVE_PID" 30
  wait_for_http "http://$frontend_health_host:$app_port/health" management-proxy "$BACKEND_PID" 30

  log_access_urls "$app_host" "$app_port"
  log "Config:      rvizweb_configs/$default_rvizweb_config"
  local -a service_pids=("$BACKEND_PID" "$FRONTEND_PID")
  [[ -z "$NATIVE_PID" ]] || service_pids+=("$NATIVE_PID")
  [[ -z "$ROS_MASTER_PID" ]] || service_pids+=("$ROS_MASTER_PID")
  wait -n "${service_pids[@]}"
  fail "A service stopped unexpectedly; $(failure_output_hint)"
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
