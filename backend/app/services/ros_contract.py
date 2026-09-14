"""应用层使用的 ROS 服务契约。

该模块不能导入 rclpy、rospy 或具体 ROS 实现。FastAPI 路由只依赖此契约，
中间件差异由 ROS2/ROS1 适配器负责。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from fastapi import WebSocket

from ..core.config import Settings
from ..models.ros import NodeInfo, SystemStatus, TopicInfo


@runtime_checkable
class RosService(Protocol):
    """FastAPI 和 WebSocket 入口可见的稳定 ROS 能力边界。"""

    middleware: str
    settings: Settings

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def handle_websocket(self, websocket: WebSocket) -> None: ...

    async def get_topics(self, include_details: bool = True) -> List[TopicInfo]: ...

    async def get_topic_info(self, topic_name: str) -> Optional[TopicInfo]: ...

    async def subscribe_topic(
        self, topic_name: str, message_type: Optional[str] = None
    ) -> bool: ...

    async def unsubscribe_topic(self, topic_name: str) -> bool: ...

    async def publish_message(
        self,
        topic_name: str,
        message: Dict[str, Any],
        message_type: Optional[str] = None,
    ) -> bool: ...

    async def get_nodes(self) -> List[NodeInfo]: ...

    async def get_node_info(self, node_name: str) -> Optional[NodeInfo]: ...

    async def get_topic_types(self) -> Dict[str, str]: ...

    async def get_topic_frequencies(
        self, sample_duration: Optional[float] = None
    ) -> Dict[str, Optional[float]]: ...

    async def get_services(self) -> List[str]: ...

    async def get_service_types(self) -> Dict[str, str]: ...

    async def get_params(self) -> List[str]: ...

    async def get_system_status(self) -> SystemStatus: ...
