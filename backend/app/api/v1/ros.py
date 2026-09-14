"""
ROS2 相关 API 端点
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ...core.config import get_settings
from ...core.ros_types import canonical_message_type
from ...core.security import ensure_ros_operation_allowed
from ...models.ros import NodeInfo, SystemStatus, TopicInfo
from ...services.dependencies import get_ros_service
from ...services.ros_contract import RosService

router = APIRouter()
logger = logging.getLogger(__name__)


class TopicSubscriptionRequest(BaseModel):
    topic: str = Field(..., description="ROS2 topic name")
    message_type: Optional[str] = Field(None, description="ROS2 message type")

    @field_validator("message_type")
    @classmethod
    def normalize_message_type(cls, value):
        return canonical_message_type(value) if value is not None else None


class TopicPublishRequest(BaseModel):
    topic: str = Field(..., description="ROS2 topic name")
    message_type: str = Field(..., description="ROS2 message type")
    msg: Dict[str, Any] = Field(..., description="ROS message payload")

    @field_validator("message_type")
    @classmethod
    def normalize_message_type(cls, value):
        return canonical_message_type(value)


@router.get("/topics", response_model=List[TopicInfo])
async def get_topics(service: RosService = Depends(get_ros_service)):
    """获取所有 ROS2 主题列表"""
    try:
        topics = await service.get_topics()
        return topics
    except Exception as e:
        logger.error(f"Failed to get topics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topics/frequencies", response_model=Dict[str, Optional[float]])
async def get_topic_frequencies(
    active_sampling: bool = Query(
        False,
        description="是否临时订阅所有 topic 进行主动采样",
    ),
    sample_seconds: float = Query(
        1.0,
        ge=0.5,
        le=5.0,
        description="主动订阅采样时长（秒）",
    ),
    service: RosService = Depends(get_ros_service),
):
    """短时订阅当前 ROS2 主题并测量实际接收频率。"""
    try:
        frequencies = await service.get_topic_frequencies(
            sample_duration=sample_seconds if active_sampling else None
        )
        return frequencies
    except Exception as e:
        logger.error(f"Failed to get topic frequencies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/topic-info", response_model=TopicInfo)
async def get_topic_info_by_query(
    topic_name: str, service: RosService = Depends(get_ros_service)
):
    """通过 query 参数获取主题信息，支持包含 / 的 ROS topic 名。"""
    try:
        topic_info = await service.get_topic_info(topic_name)
        if not topic_info:
            raise HTTPException(status_code=404, detail=f"Topic {topic_name} not found")
        return topic_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get topic info for {topic_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/topics/subscribe")
async def subscribe_topic_by_body(
    payload: TopicSubscriptionRequest,
    service: RosService = Depends(get_ros_service),
):
    """REST 订阅没有连接所有权，必须使用 WebSocket 会话。"""
    raise HTTPException(
        status_code=405,
        detail="请通过 WebSocket 会话订阅 ROS topic",
    )


@router.post("/topics/unsubscribe")
async def unsubscribe_topic_by_body(
    payload: TopicSubscriptionRequest,
    service: RosService = Depends(get_ros_service),
):
    """REST 取消订阅没有连接所有权，必须使用 WebSocket 会话。"""
    raise HTTPException(
        status_code=405,
        detail="请通过 WebSocket 会话取消订阅 ROS topic",
    )


@router.post("/topics/publish")
async def publish_message_by_body(
    payload: TopicPublishRequest,
    service: RosService = Depends(get_ros_service),
):
    """通过请求体发布消息，支持包含 / 的 ROS topic 名。"""
    try:
        ensure_ros_operation_allowed(
            get_settings(),
            "publish",
            payload.topic,
        )
        success = await service.publish_message(
            payload.topic,
            payload.msg,
            payload.message_type,
        )
        if not success:
            raise HTTPException(
                status_code=422,
                detail=f"消息未能发布到 {payload.topic}",
            )
        return {"success": success, "topic": payload.topic, "action": "published"}
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to publish to {payload.topic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes", response_model=List[NodeInfo])
async def get_nodes(service: RosService = Depends(get_ros_service)):
    """获取所有 ROS2 节点列表"""
    try:
        nodes = await service.get_nodes()
        return nodes
    except Exception as e:
        logger.error(f"Failed to get nodes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{node_name}", response_model=NodeInfo)
async def get_node_info(
    node_name: str, service: RosService = Depends(get_ros_service)
):
    """获取特定节点信息"""
    try:
        node_info = await service.get_node_info(node_name)
        if not node_info:
            raise HTTPException(status_code=404, detail=f"Node {node_name} not found")
        return node_info
    except Exception as e:
        logger.error(f"Failed to get node info for {node_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=SystemStatus)
async def get_system_status(service: RosService = Depends(get_ros_service)):
    """获取系统状态"""
    try:
        status = await service.get_system_status()
        return status
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
