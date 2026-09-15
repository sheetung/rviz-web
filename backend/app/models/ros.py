"""
ROS2 数据模型
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

from ..core.ros_types import canonical_message_type


class TopicInfo(BaseModel):
    """ROS2 主题信息"""

    name: str = Field(..., description="主题名称")
    message_type: str = Field(..., description="消息类型")
    publishers: List[str] = Field(default_factory=list, description="发布者列表")
    subscribers: List[str] = Field(default_factory=list, description="订阅者列表")
    frequency: Optional[float] = Field(
        None, description="后端最近订阅或主动采样得到的接收频率 (Hz)，样本不足时为 null"
    )
    last_message_time: Optional[datetime] = Field(
        None,
        description="后端最近一次订阅或主动采样收到消息的 UTC 时间，未观测时为 null",
    )

    @field_validator("message_type")
    @classmethod
    def normalize_message_type(cls, value: str) -> str:
        return canonical_message_type(value)


class NodeInfo(BaseModel):
    """ROS2 节点信息"""

    name: str = Field(..., description="节点名称")
    namespace: str = Field(..., description="命名空间")
    publishers: List[str] = Field(default_factory=list, description="发布的主题")
    subscribers: List[str] = Field(default_factory=list, description="订阅的主题")
    services: List[str] = Field(default_factory=list, description="提供的服务")
    actions: List[str] = Field(default_factory=list, description="提供的动作")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="节点参数")


class ConnectionInfo(BaseModel):
    """连接信息"""

    client_id: str = Field(..., description="客户端ID")
    connected_at: datetime = Field(..., description="连接时间")
    subscribed_topics: List[str] = Field(default_factory=list, description="订阅的主题")
    advertised_topics: Dict[str, str] = Field(
        default_factory=dict,
        description="该客户端声明的发布主题及消息类型",
    )
    message_count: int = Field(default=0, description="消息计数")


class SystemStatus(BaseModel):
    """系统状态"""

    ros_domain_id: Optional[int] = Field(None, description="ROS2 Domain ID; ROS1 为 null")
    active_nodes: int = Field(..., description="活跃节点数")
    active_topics: int = Field(..., description="活跃主题数")
    active_connections: int = Field(..., description="活跃连接数")
    system_time: datetime = Field(..., description="系统时间")
    uptime: float = Field(..., description="运行时间 (秒)")
    memory_usage: float = Field(..., description="内存使用率")
    cpu_usage: float = Field(..., description="CPU 使用率")
    cpu_temperature: Optional[float] = Field(None, description="CPU 温度")
