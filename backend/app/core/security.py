"""浏览器来源与 ROS 操作的安全边界。"""

from __future__ import annotations

import fnmatch
import re

from .config import Settings

ROS_TOPIC_PATTERN = re.compile(r"^/[A-Za-z0-9_~-]+(?:/[A-Za-z0-9_~-]+)*$")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def origin_is_allowed(origin: str | None, settings: Settings) -> bool:
    if not origin:
        return True
    return origin in split_csv(settings.cors_origins)


def ensure_ros_operation_allowed(
    settings: Settings,
    operation: str,
    topic: str,
) -> None:
    if not topic or len(topic) > 512 or not ROS_TOPIC_PATTERN.fullmatch(topic):
        raise ValueError("ROS topic 名称无效")

    if operation == "subscribe":
        allowed_topics = split_csv(settings.ros_subscribe_topic_allowlist)
    elif operation == "publish":
        allowed_topics = split_csv(settings.ros_publish_topic_allowlist)
    else:
        raise ValueError(f"未知 ROS 操作: {operation}")

    if not any(fnmatch.fnmatchcase(topic, pattern) for pattern in allowed_topics):
        raise PermissionError(f"不允许 {operation} ROS topic: {topic}")
