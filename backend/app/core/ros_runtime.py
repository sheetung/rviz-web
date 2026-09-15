"""Runtime selection comes from sourced ROS, never from application Settings."""

import os


def selected_middleware():
    version = os.environ.get("ROS_VERSION")
    if version not in ("1", "2"):
        raise RuntimeError(
            "Source ROS_SETUP_PATHS first: ROS_VERSION must be provided by the ROS environment"
        )
    return f"ros{version}"
