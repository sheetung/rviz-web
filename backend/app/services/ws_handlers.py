"""
WebSocket 请求分发与处理
处理来自前端的所有 WebSocket 操作请求
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.encoders import jsonable_encoder

from ..core.security import ensure_ros_operation_allowed

if TYPE_CHECKING:
    from .rosbridge import RosbridgeService

logger = logging.getLogger(__name__)


class WebSocketRequestHandler:
    """WebSocket 请求分发器和处理器"""

    def __init__(self, service: RosbridgeService):
        self._svc = service

    async def handle_operation(self, client_id: str, message: dict):
        """中心分发：根据 op 字段路由到对应的处理方法"""
        op = message.get("op")
        request_id = message.get("id")

        dispatch = {
            "ping": self._handle_ping,
            "subscribe": self._handle_subscribe,
            "unsubscribe": self._handle_unsubscribe,
            "advertise": self._handle_advertise,
            "unadvertise": self._handle_unadvertise,
            "publish": self._handle_publish,
            "get_topics": self._handle_get_topics,
            "get_nodes": self._handle_get_nodes,
            "get_topic_types": self._handle_get_topic_types,
            "get_topic_frequencies": self._handle_get_topic_frequencies,
            "get_system_status": self._handle_get_system_status,
            "get_services": self._handle_get_services,
            "get_service_types": self._handle_get_service_types,
            "get_params": self._handle_get_params,
        }

        handler = dispatch.get(op)
        if handler:
            # ping/subscribe/unsubscribe/advertise/unadvertise/publish 的参数签名不同
            if op == "ping":
                await handler(client_id, request_id)
            elif op in ("subscribe", "unsubscribe"):
                await handler(client_id, message)
            elif op in ("advertise", "unadvertise", "publish"):
                await handler(client_id, message)
            else:
                await handler(client_id, request_id)
        else:
            logger.warning(f"Unknown operation: {op}")
            if request_id:
                await self._send_response(
                    client_id, request_id, "error", error=f"Unknown operation: {op}"
                )

    async def _send_response(
        self, client_id: str, request_id: str = None, op: str = "", **payload
    ):
        """通用响应发送"""
        response = {"op": op, **payload}
        if request_id:
            response["id"] = request_id
        await self._svc.connection_manager.send_to_client(client_id, response)

    async def _send_error(
        self, client_id: str, request_id: str = None, error: str = ""
    ):
        """发送错误响应"""
        if request_id:
            await self._send_response(client_id, request_id, "error", error=error)

    # ── ping ────────────────────────────────────────────────────────────
    async def _handle_ping(self, client_id: str, request_id: str = None):
        await self._send_response(client_id, request_id, "pong")

    # ── subscribe / unsubscribe ─────────────────────────────────────────
    async def _handle_subscribe(self, client_id: str, message: dict):
        request_id = message.get("id")
        try:
            topic = message.get("topic")
            msg_type = message.get("type")
            ensure_ros_operation_allowed(
                self._svc.settings,
                "subscribe",
                topic,
            )
            success = await self._svc._handle_subscribe(client_id, message)
            if not success:
                raise RuntimeError(f"无法订阅 ROS topic: {topic}")
            await self._send_response(
                client_id,
                request_id,
                "subscribe_result",
                success=True,
                topic=topic,
            )
        except Exception as error:
            logger.error("Failed to subscribe client %s: %s", client_id, error)
            await self._send_error(client_id, request_id, str(error))

    async def _handle_unsubscribe(self, client_id: str, message: dict):
        """处理取消订阅"""
        request_id = message.get("id")
        topic = message.get("topic")
        if not topic:
            await self._send_error(client_id, request_id, "缺少 ROS topic")
            return
        info = self._svc.connection_manager.connection_info.get(client_id)
        if info and topic in info.subscribed_topics:
            info.subscribed_topics.remove(topic)
            await self._svc._stop_ros_subscription_if_unused(topic)
        await self._send_response(
            client_id,
            request_id,
            "unsubscribe_result",
            success=True,
            topic=topic,
        )

    # ── advertise / unadvertise / publish ────────────────────────────────
    async def _handle_advertise(self, client_id: str, message: dict):
        """处理前端声明发布者"""
        request_id = message.get("id")
        topic = message.get("topic")
        msg_type = message.get("type")
        if not topic or not msg_type:
            await self._send_error(
                client_id,
                request_id,
                "声明发布者时缺少 topic 或 type",
            )
            return
        try:
            ensure_ros_operation_allowed(
                self._svc.settings,
                "publish",
                topic,
            )
            await self._svc._ensure_publisher(topic, msg_type, client_id)
            info = self._svc.connection_manager.connection_info.get(client_id)
            if info:
                info.advertised_topics[topic] = msg_type
            await self._send_response(
                client_id,
                request_id,
                "advertise_result",
                success=True,
                topic=topic,
            )
            logger.info(f"✅ Advertised publisher for {topic} ({msg_type})")
        except Exception as e:
            logger.error(f"❌ Failed to advertise {topic}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_unadvertise(self, client_id: str, message: dict):
        """处理前端取消发布者"""
        request_id = message.get("id")
        topic = message.get("topic")
        if not topic:
            await self._send_error(client_id, request_id, "缺少 ROS topic")
            return
        try:
            await self._svc._release_publisher(topic, client_id)
            info = self._svc.connection_manager.connection_info.get(client_id)
            if info:
                info.advertised_topics.pop(topic, None)
            await self._send_response(
                client_id,
                request_id,
                "unadvertise_result",
                success=True,
                topic=topic,
            )
            logger.info(f"🗑️ Unadvertised publisher for {topic}")
        except Exception as e:
            logger.error(f"Failed to unadvertise {topic}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_publish(self, client_id: str, message: dict):
        """处理发布消息"""
        request_id = message.get("id")
        topic = message.get("topic")
        msg_data = message.get("msg")
        msg_type = message.get("type")

        if not topic or msg_data is None:
            await self._send_error(
                client_id,
                request_id,
                "发布消息时缺少 topic 或 msg",
            )
            return

        try:
            publisher_record = self._svc.publishers.get(topic)
            resolved_type = msg_type or (
                publisher_record.get("msg_type") if publisher_record else None
            )
            ensure_ros_operation_allowed(
                self._svc.settings,
                "publish",
                topic,
            )
            # 即使 publisher 已存在，也要先原子地登记当前连接的所有权，
            # 防止另一个客户端同时 unadvertise 后销毁它。
            await self._svc._ensure_publisher(topic, resolved_type, client_id)

            publisher_record = self._svc.publishers.get(topic)
            if not publisher_record:
                raise RuntimeError(f"Publisher for {topic} not available")
            if publisher_record["msg_type"] != resolved_type:
                raise ValueError(
                    f"{topic} 已按 {publisher_record['msg_type']} 创建，"
                    f"不能改用 {resolved_type}"
                )

            info = self._svc.connection_manager.connection_info.get(client_id)
            if info:
                info.advertised_topics[topic] = resolved_type

            msg_class = publisher_record["msg_class"]
            ros_msg = self._svc._converter.from_dict(msg_class, msg_data)
            if ros_msg is None:
                raise ValueError(f"无法把消息转换为 {msg_class.__name__}")

            publisher = publisher_record["publisher"]
            publisher.publish(ros_msg)
            await self._send_response(
                client_id,
                request_id,
                "publish_result",
                success=True,
                topic=topic,
            )
            logger.info(f"📤 Published {msg_class.__name__} to {topic}")
        except Exception as e:
            logger.error(f"❌ Error publishing to {topic}: {e}", exc_info=True)
            await self._send_error(client_id, request_id, str(e))

    # ── 查询类 ──────────────────────────────────────────────────────────
    async def _handle_get_topics(self, client_id: str, request_id: str = None):
        try:
            topics = await self._svc.get_topics()
            await self._send_response(
                client_id,
                request_id,
                "get_topics_result",
                topics=jsonable_encoder(topics),
            )
            logger.info(f"Sent {len(topics)} topics to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_topics for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_nodes(self, client_id: str, request_id: str = None):
        try:
            nodes = await self._svc.get_nodes()
            await self._send_response(
                client_id,
                request_id,
                "get_nodes_result",
                nodes=[node.dict() for node in nodes],
            )
            logger.info(f"Sent {len(nodes)} nodes to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_nodes for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_topic_types(self, client_id: str, request_id: str = None):
        try:
            topic_types = await self._svc.get_topic_types()
            await self._send_response(
                client_id, request_id, "get_topic_types_result", topic_types=topic_types
            )
            logger.info(f"Sent topic types to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_topic_types for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_topic_frequencies(
        self, client_id: str, request_id: str = None
    ):
        try:
            frequencies = await self._svc.get_topic_frequencies(sample_duration=None)
            await self._send_response(
                client_id,
                request_id,
                "get_topic_frequencies_result",
                frequencies=frequencies,
            )
            logger.info(f"Sent topic frequencies to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_topic_frequencies for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_system_status(self, client_id: str, request_id: str = None):
        try:
            status = await self._svc.get_system_status()
            await self._send_response(
                client_id,
                request_id,
                "get_system_status_result",
                status=jsonable_encoder(status),
            )
        except Exception as e:
            logger.error(f"Failed to handle get_system_status for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_services(self, client_id: str, request_id: str = None):
        try:
            services = await self._svc.get_services()
            await self._send_response(
                client_id, request_id, "get_services_result", services=services
            )
            logger.info(f"Sent {len(services)} services to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_services for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_service_types(self, client_id: str, request_id: str = None):
        try:
            service_types = await self._svc.get_service_types()
            await self._send_response(
                client_id,
                request_id,
                "get_service_types_result",
                service_types=service_types,
            )
            logger.info(f"Sent service types to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_service_types for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))

    async def _handle_get_params(self, client_id: str, request_id: str = None):
        try:
            params = await self._svc.get_params()
            await self._send_response(
                client_id, request_id, "get_params_result", params=params
            )
            logger.info(f"Sent {len(params)} params to client {client_id}")
        except Exception as e:
            logger.error(f"Failed to handle get_params for {client_id}: {e}")
            await self._send_error(client_id, request_id, str(e))
