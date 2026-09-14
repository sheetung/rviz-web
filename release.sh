#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENT=""
VERSION=""
PUSH_RELEASE=false
GENERATED=false

log() { printf '[release] %s\n' "$*"; }
fail() { printf '[release] ERROR: %s\n' "$*" >&2; exit 1; }

show_help() {
  printf 'Usage: %s <frontend|backend> <version> [--push]\n' "$0"
  printf 'Examples:\n'
  printf '  %s frontend 1.4.0\n' "$0"
  printf '  %s backend 1.3.1 --push\n' "$0"
}

restore_generated_files() {
  local exit_code=$?
  trap - ERR
  if [[ "$GENERATED" == true ]]; then
    log "Release failed; restoring generated version files"
    if [[ "$COMPONENT" == "frontend" ]]; then
      git -C "$PROJECT_ROOT" restore -- frontend/package.json frontend/package-lock.json
    else
      git -C "$PROJECT_ROOT" restore -- backend/pyproject.toml backend/uv.lock
    fi
  fi
  exit "$exit_code"
}

parse_args() {
  [[ $# -gt 0 ]] || { show_help; exit 2; }
  case "${1:-}" in
    help|-h|--help) show_help; exit 0 ;;
  esac
  [[ $# -ge 2 ]] || { show_help; exit 2; }
  COMPONENT="$1"
  VERSION="$2"
  shift 2
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --push) PUSH_RELEASE=true ;;
      *) fail "Unknown argument: $1" ;;
    esac
    shift
  done
}

run_backend_checks() {
  (
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/start.sh"
    load_env
    load_ros
    export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
    "$PROJECT_ROOT/backend/.venv/bin/pytest" -q "$PROJECT_ROOT/backend/tests"
    "$PROJECT_ROOT/backend/.venv/bin/python" -m compileall -q "$PROJECT_ROOT/backend/app"
  )
}

main() {
  parse_args "$@"
  [[ "$COMPONENT" == "frontend" || "$COMPONENT" == "backend" ]] \
    || fail "Component must be frontend or backend"
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] \
    || fail "Version must be semantic, for example 1.4.0"

  cd "$PROJECT_ROOT"
  for command_name in git node; do
    command -v "$command_name" >/dev/null 2>&1 || fail "Missing command: $command_name"
  done
  [[ -z "$(git status --porcelain)" ]] || fail "Working tree must be clean"

  local tag="$COMPONENT-v$VERSION"
  git rev-parse "$tag" >/dev/null 2>&1 && fail "Tag already exists: $tag"

  trap restore_generated_files ERR
  GENERATED=true
  node scripts/sync-version.mjs "$COMPONENT" "$VERSION"
  node scripts/sync-version.mjs "$COMPONENT" --check

  if [[ "$COMPONENT" == "frontend" ]]; then
    command -v npm >/dev/null 2>&1 || fail "Missing command: npm"
    npm --prefix frontend test
    npm --prefix frontend run lint:check
    npm --prefix frontend run build
    git add frontend/package.json frontend/package-lock.json
  else
    [[ -x backend/.venv/bin/python ]] || fail "Backend environment is missing"
    run_backend_checks
    git add backend/pyproject.toml backend/uv.lock
  fi

  git commit -m "chore($COMPONENT): release v$VERSION"
  git tag -a "$tag" -m "Release $COMPONENT v$VERSION"
  GENERATED=false
  trap - ERR

  if [[ "$PUSH_RELEASE" == true ]]; then
    local branch
    branch="$(git branch --show-current)"
    [[ -n "$branch" ]] || fail "Cannot push from detached HEAD"
    git push origin "$branch"
    git push origin "$tag"
    log "Pushed $branch and $tag"
  else
    log "Created $tag; push it after review"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
