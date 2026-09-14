"""ROS 接口名称的协议层规范化。

浏览器和应用内部统一使用 ``package/msg/Type``。ROS1 常见的
``package/Type`` 只允许在边界输入，进入系统后立即转换为规范形式。
"""

from __future__ import annotations

import re

UNKNOWN_MESSAGE_TYPE = "unknown"
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def canonical_message_type(message_type: str) -> str:
    """返回规范消息类型，格式非法时抛出 ``ValueError``。"""
    value = str(message_type or "").strip()
    if value == UNKNOWN_MESSAGE_TYPE:
        return value

    parts = value.split("/")
    if len(parts) == 2:
        package, type_name = parts
    elif len(parts) == 3 and parts[1] == "msg":
        package, _, type_name = parts
    else:
        raise ValueError(
            f"消息类型必须使用 package/msg/Type 或 package/Type: {value or '<empty>'}"
        )

    if not _IDENTIFIER.fullmatch(package) or not _IDENTIFIER.fullmatch(type_name):
        raise ValueError(f"消息类型包含非法标识符: {value}")
    return f"{package}/msg/{type_name}"


def ros1_message_type(message_type: str) -> str:
    """把内部规范类型转换为 ROS1 的 ``package/Type``。"""
    canonical = canonical_message_type(message_type)
    if canonical == UNKNOWN_MESSAGE_TYPE:
        return canonical
    package, _, type_name = canonical.split("/")
    return f"{package}/{type_name}"
