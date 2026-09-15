#!/usr/bin/env bash
# Shared local/container ROS loader. Only source trusted setup files.
ros2_python_for_venv() {
  # rclpy contains native extensions: create the venv with the interpreter
  # that can import the sourced ROS2 installation, not an auto-downloaded one.
  python3 -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 13), "Backend requires Python 3.10–3.12"; import rclpy; print(sys.executable)'
}

check_ros_python() {
  local python_executable="$1"
  if [[ "${ROS_VERSION:-}" == 1 ]]; then
    "$python_executable" -c 'import rospy, roslib.message; from sensor_msgs.msg import PointCloud2; from geometry_msgs.msg import Twist' || return 1
    if [[ "${ROS1_AUTOSTART_MASTER:-false}" == true ]]; then
      "$python_executable" -c 'import rosmaster.master' || return 1
    fi
  else
    "$python_executable" -c 'import rclpy'
  fi
}

load_ros_environment() {
  local setup_file previous_version="${ROS_VERSION:-}" previous_distro="${ROS_DISTRO:-}"
  local socket_path="${ROS_WS_URL-/ws/ros2}" selected_version=2 setup_paths setup_variable
  socket_path="${socket_path%%[?#]*}"
  case "$socket_path" in
    /ws/ros1|*/ws/ros1) selected_version=1 ;;
  esac
  setup_variable="ROS${selected_version}_SETUP_PATHS"
  setup_paths="${!setup_variable:-}"
  [[ -n "$setup_paths" ]] || { echo "Set $setup_variable to your ROS setup file" >&2; return 1; }
  for setup_file in $setup_paths; do
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
    if [[ "$ROS_VERSION" != "$selected_version" ]]; then
      echo "$setup_variable must provide ROS_VERSION=$selected_version (got $ROS_VERSION)" >&2
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
