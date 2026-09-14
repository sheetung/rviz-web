"""
依赖注入服务
管理应用中的全局服务实例，避免循环导入
"""

from typing import Optional

from ..core.config import get_settings
from .ros_contract import RosService
from .ros2_service import Ros2Service

# 当前部署的全局 ROS 服务实例
_ros_service: Optional[RosService] = None


def get_ros_service() -> RosService:
    """获取当前部署选择的 ROS 服务实现。"""
    global _ros_service
    if _ros_service is None:
        settings = get_settings()
        _ros_service = Ros2Service(settings)
    return _ros_service
