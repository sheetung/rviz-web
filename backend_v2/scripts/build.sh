#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${ROS_VERSION:-}" in
  1|2) ;;
  *) echo 'Source one ROS environment first (ROS_VERSION must be 1 or 2).' >&2; exit 2 ;;
esac
build_dir="$root/build/ros$ROS_VERSION"
startup=false
if [[ "${1:-}" == --startup ]]; then
  startup=true
  shift
fi

# CMake's build system tracks source/header/CMakeLists changes. Reconfigure
# explicitly only when the selected toolchain or sourced ROS environment changes.
context_file="$build_dir/.startup-context"
context="$(printf '%s\n' "$root" "$ROS_VERSION" "${ROS_DISTRO:-}" \
  "${ROS1_SETUP_PATHS:-}" "${ROS2_SETUP_PATHS:-}" "${CMAKE_PREFIX_PATH:-}" \
  "${AMENT_PREFIX_PATH:-}" "${RMW_IMPLEMENTATION:-}" "${CC:-}" "${CXX:-}" \
  "${CMAKE_TOOLCHAIN_FILE:-}" | sha256sum)"
if [[ "$startup" != true || ! -f "$build_dir/CMakeCache.txt" ||
      ! -f "$context_file" || "$(cat "$context_file")" != "$context" || $# -gt 0 ]]; then
  cmake -S "$root" -B "$build_dir" -DROS_VERSION="$ROS_VERSION" -DCMAKE_BUILD_TYPE=Release "$@"
  if [[ "$startup" == true ]]; then
    printf '%s\n' "$context" > "$context_file"
  else
    # Explicit builds may supply different CMake options.
    rm -f "$context_file"
  fi
fi

if [[ "$startup" == true ]]; then
  cmake --build "$build_dir" --target rvizweb_native --parallel "${RVIZWEB_BUILD_JOBS:-2}"
else
  cmake --build "$build_dir" --parallel "${RVIZWEB_BUILD_JOBS:-2}"
  ctest --test-dir "$build_dir" --output-on-failure
fi
