# ROS1 1.15 runtime from Ubuntu Jammy packages, paired with Python 3.10.
# This is not an official /opt/ros/noetic installation.
export ROS_VERSION=1
export ROS_DISTRO=ros1-jammy
export ROS_PACKAGE_PATH=/usr/share
export ROS_MASTER_URI="${ROS_MASTER_URI:-http://127.0.0.1:11311}"
