"""
依赖注入服务
管理应用中的全局服务实例，避免循环导入
"""

from typing import Optional

from ..core.config import get_settings
from .connection_manager import ConnectionManager
from .ros_gateway import RosGateway
from .ros_contract import RosService
from .ros_application import RosApplication

# 当前部署的全局 ROS 服务实例
_ros_service: Optional[RosApplication] = None
_ros_gateway: Optional[RosGateway] = None


def _create_connection_manager(settings) -> ConnectionManager:
    return ConnectionManager(
        settings.max_connections,
        settings.websocket_outbound_queue_size,
        settings.websocket_send_timeout,
        settings.websocket_max_outbound_message_bytes,
    )


def get_ros_service() -> RosService:
    """获取当前部署选择的 ROS 服务实现。"""
    global _ros_service
    if _ros_service is None:
        settings = get_settings()
        from .ros2.adapter import Ros2Adapter

        _ros_service = RosApplication(
            settings, Ros2Adapter(settings), _create_connection_manager(settings)
        )
    return _ros_service


def get_ros_gateway() -> RosGateway:
    """获取浏览器 WebSocket Gateway。"""
    global _ros_gateway
    if _ros_gateway is None:
        settings = get_settings()
        service = get_ros_service()
        _ros_gateway = RosGateway(settings, service, service.connection_manager)
    return _ros_gateway
