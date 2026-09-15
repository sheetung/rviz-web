#!/usr/bin/env bash
# Shared local/container ROS loader. Only source trusted setup files.
load_ros_environment() {
  local setup_file previous_version="${ROS_VERSION:-}" previous_distro="${ROS_DISTRO:-}"
  [[ -n "${ROS_SETUP_PATHS:-}" ]] || { echo 'Set ROS_SETUP_PATHS to your ROS setup file' >&2; return 1; }
  for setup_file in $ROS_SETUP_PATHS; do
    [[ -f "$setup_file" ]] || { echo "ROS setup file missing: $setup_file" >&2; return 1; }
    set +u
    source "$setup_file" || { set -u; echo "Failed loading ROS setup: $setup_file" >&2; return 1; }
    set -u
    [[ "${ROS_VERSION:-}" == 1 || "${ROS_VERSION:-}" == 2 ]] || {
      echo 'Setup must provide ROS_VERSION=1 or 2' >&2; return 1;
    }
    if [[ -n "$previous_version" && "$previous_version" != "$ROS_VERSION" ]] ||
       [[ -n "$previous_distro" && "$previous_distro" != "${ROS_DISTRO:-}" ]]; then
      echo 'Mixed ROS environments. Start from a clean shell with one ROS installation.' >&2
      return 1
    fi
    previous_version="$ROS_VERSION"
    previous_distro="${ROS_DISTRO:-}"
  done
  if [[ "$ROS_VERSION" == 1 ]]; then
    [[ -n "${ROS_IP:-}" ]] || unset ROS_IP
    [[ -n "${ROS_HOSTNAME:-}" ]] || unset ROS_HOSTNAME
    if [[ -n "${ROS_IP:-}" && -n "${ROS_HOSTNAME:-}" ]]; then
      echo 'Set only one of ROS_IP or ROS_HOSTNAME' >&2
      return 1
    fi
  fi
}
