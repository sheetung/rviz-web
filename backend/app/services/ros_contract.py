"""应用层使用的 ROS 服务契约。

该模块不能导入 rclpy、rospy 或具体 ROS 实现。FastAPI 路由只依赖此契约，
中间件差异由 ROS2/ROS1 适配器负责。
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
    Callable,
    Awaitable,
)

from ..core.config import Settings
from ..models.ros import NodeInfo, SystemStatus, TopicInfo


@runtime_checkable
class RosQueries(Protocol):
    """FastAPI 和 WebSocket 入口可见的稳定 ROS 能力边界。"""

    middleware: str
    settings: Settings

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def get_topics(self, include_details: bool = True) -> List[TopicInfo]: ...

    async def get_topic_info(self, topic_name: str) -> Optional[TopicInfo]: ...

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


@runtime_checkable
class RosService(RosQueries, Protocol):
    """应用入口能力，系统状态属于公共层。"""

    async def get_system_status(self) -> SystemStatus: ...


class RosSessionService(RosService, Protocol):
    """WebSocket Gateway 使用的客户端级 ROS 操作。"""

    async def subscribe_client(
        self, client_id: str, topic: str, message_type: Optional[str]
    ) -> bool: ...

    async def unsubscribe_client(self, client_id: str, topic: str) -> None: ...

    async def advertise_client(
        self, client_id: str, topic: str, message_type: str
    ) -> str: ...

    async def unadvertise_client(self, client_id: str, topic: str) -> None: ...

    async def publish_client(
        self,
        client_id: str,
        topic: str,
        message: Dict[str, Any],
        message_type: Optional[str],
    ) -> str: ...

    async def cleanup_client(self, client_id: str) -> None: ...


@runtime_checkable
class RosAdapter(RosQueries, Protocol):
    """中间件能力：只交换规范数据和不透明资源所有者标识。"""

    async def subscribe_topic(
        self, topic_name: str, message_type: Optional[str] = None
    ) -> bool: ...

    async def unsubscribe_topic(self, topic_name: str) -> bool: ...

    def set_message_sink(
        self, sink: Callable[[str, dict, str], Awaitable[None]]
    ) -> None: ...

    async def acquire_publisher(
        self, topic: str, msg_type: str, owner_id: str
    ) -> None: ...

    async def release_publisher(self, topic: str, owner_id: str) -> None: ...

    def publish_prepared(self, topic: str, message: Dict[str, Any]) -> str: ...
