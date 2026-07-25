"""
WebSocket 连接管理器
管理客户端连接、消息路由和广播
"""

import asyncio
import contextlib
import json
import logging
import math
import struct
from collections import OrderedDict
from datetime import datetime
from typing import Dict

from fastapi import WebSocket

from ..models.ros import ConnectionInfo

logger = logging.getLogger(__name__)

POINTCLOUD_BINARY_TRANSPORT = "pointcloud-binary-v1"
_POINTCLOUD_BINARY_MAGIC = b"RVPC"
_POINTCLOUD_BINARY_VERSION = 1
_POINTCLOUD_BINARY_HEADER = struct.Struct("<4sBBHI")


def _replace_non_finite_numbers(value):
    """将 JSON 不支持的 NaN/Infinity 递归替换为 null。"""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _replace_non_finite_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_replace_non_finite_numbers(item) for item in value]
    return value


def _serialize_json_message(message: dict) -> str:
    """生成浏览器可严格解析的 JSON，并避免正常消息的额外遍历。"""
    try:
        return json.dumps(message, allow_nan=False, separators=(",", ":"))
    except ValueError:
        return json.dumps(
            _replace_non_finite_numbers(message),
            allow_nan=False,
            separators=(",", ":"),
        )


def _pointcloud_binary_data(message: dict):
    """返回内部 PointCloud2 原始字节；其他消息返回 None。"""
    if message.get("op") != "publish":
        return None
    pointcloud = message.get("msg")
    if not isinstance(pointcloud, dict):
        return None
    data = pointcloud.get("data")
    if pointcloud.get("data_encoding") != "binary" or not isinstance(
        data,
        (bytes, bytearray, memoryview),
    ):
        return None
    return data


def _serialize_binary_pointcloud_message(message: dict) -> bytes:
    """编码 pointcloud-binary-v1 帧，元数据 JSON 后接 4 字节对齐的原始数据。"""
    point_data = _pointcloud_binary_data(message)
    if point_data is None:
        raise ValueError("message is not an internal binary PointCloud2 update")

    pointcloud = message["msg"]
    metadata = {
        **message,
        "msg": {
            **pointcloud,
            "data_encoding": POINTCLOUD_BINARY_TRANSPORT,
        },
    }
    metadata["msg"].pop("data", None)
    metadata_bytes = _serialize_json_message(metadata).encode("utf-8")
    payload_offset = _POINTCLOUD_BINARY_HEADER.size + len(metadata_bytes)
    padding_size = (-payload_offset) % 4
    prefix = _POINTCLOUD_BINARY_HEADER.pack(
        _POINTCLOUD_BINARY_MAGIC,
        _POINTCLOUD_BINARY_VERSION,
        0,
        0,
        len(metadata_bytes),
    )
    return b"".join(
        (
            prefix,
            metadata_bytes,
            b"\0" * padding_size,
            bytes(point_data),
        )
    )


def _serialize_topic_message(message: dict):
    """PointCloud2 使用二进制帧，其他 topic 使用 JSON 文本。"""
    if _pointcloud_binary_data(message) is not None:
        return _serialize_binary_pointcloud_message(message)
    return _serialize_json_message(message)


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(
        self,
        max_connections: int = 100,
        outbound_queue_size: int = 8,
        send_timeout: float = 2.0,
        max_outbound_message_bytes: int = 16_777_216,
    ):
        self.max_connections = max_connections
        self.outbound_queue_size = outbound_queue_size
        self.send_timeout = send_timeout
        self.max_outbound_message_bytes = max_outbound_message_bytes
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_info: Dict[str, ConnectionInfo] = {}
        # Control-plane responses remain ordered and reliable. Delta/event topics
        # have their own bounded FIFO, while replaceable sensor snapshots use a
        # latest-value store so slow clients never accumulate stale frames.
        self._send_queues: Dict[str, asyncio.Queue[str]] = {}
        self._ordered_topic_queues: Dict[str, asyncio.Queue[str]] = {}
        self._latest_topic_messages: Dict[str, OrderedDict[str, dict]] = {}
        self._prefer_latest_topics: Dict[str, bool] = {}
        self._sender_events: Dict[str, asyncio.Event] = {}
        self._sender_tasks: Dict[str, asyncio.Task] = {}
        self._connection_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """连接客户端"""
        async with self._connection_lock:
            if len(self.active_connections) >= self.max_connections:
                await websocket.close(code=1008, reason="Max connections reached")
                return False

            await websocket.accept()
            self.active_connections[client_id] = websocket
            self.connection_info[client_id] = ConnectionInfo(
                client_id=client_id,
                connected_at=datetime.now(),
                subscribed_topics=[],
                message_count=0,
            )
            self._send_queues[client_id] = asyncio.Queue(
                maxsize=self.outbound_queue_size
            )
            self._ordered_topic_queues[client_id] = asyncio.Queue(
                maxsize=self.outbound_queue_size
            )
            self._latest_topic_messages[client_id] = OrderedDict()
            self._prefer_latest_topics[client_id] = True
            self._sender_events[client_id] = asyncio.Event()
            self._sender_tasks[client_id] = asyncio.create_task(
                self._sender_loop(client_id),
                name=f"websocket-sender-{client_id}",
            )
        logger.info(f"Client {client_id} connected")
        return True

    def disconnect(self, client_id: str):
        """断开客户端"""
        self.active_connections.pop(client_id, None)
        self.connection_info.pop(client_id, None)
        self._send_queues.pop(client_id, None)
        self._ordered_topic_queues.pop(client_id, None)
        self._latest_topic_messages.pop(client_id, None)
        self._prefer_latest_topics.pop(client_id, None)
        self._sender_events.pop(client_id, None)
        task = self._sender_tasks.pop(client_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        logger.info(f"Client {client_id} disconnected")

    async def _sender_loop(self, client_id: str) -> None:
        try:
            while True:
                queue = self._send_queues.get(client_id)
                ordered_topic_queue = self._ordered_topic_queues.get(client_id)
                latest_topics = self._latest_topic_messages.get(client_id)
                sender_event = self._sender_events.get(client_id)
                websocket = self.active_connections.get(client_id)
                if (
                    queue is None
                    or ordered_topic_queue is None
                    or latest_topics is None
                    or sender_event is None
                    or websocket is None
                ):
                    return

                await sender_event.wait()

                queued_message_source = None
                try:
                    outbound_message = queue.get_nowait()
                    queued_message_source = queue
                except asyncio.QueueEmpty:
                    outbound_message, queued_message_source = (
                        await self._take_next_topic_message(
                            client_id,
                            ordered_topic_queue,
                            latest_topics,
                        )
                    )
                    if outbound_message is None:
                        sender_event.clear()
                        # No await occurs between clear and this check, but the
                        # recheck protects the wake-up invariant.
                        if (
                            not queue.empty()
                            or not ordered_topic_queue.empty()
                            or latest_topics
                        ):
                            sender_event.set()
                        continue

                try:
                    send_operation = (
                        websocket.send_bytes
                        if isinstance(outbound_message, bytes)
                        else websocket.send_text
                    )
                    await asyncio.wait_for(
                        send_operation(outbound_message),
                        timeout=self.send_timeout,
                    )
                    info = self.connection_info.get(client_id)
                    if info:
                        info.message_count += 1
                finally:
                    if queued_message_source is not None:
                        queued_message_source.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Failed to send message to %s: %s", client_id, error)
            # 保留 connection_info，交给 RosbridgeService 的 finally 释放
            # 该客户端持有的 ROS 订阅和发布者。
            await self._close_client_socket(
                client_id,
                code=1011,
                reason="WebSocket send failed",
            )

    async def _take_next_topic_message(
        self,
        client_id: str,
        ordered_topic_queue: asyncio.Queue[str],
        latest_topics: OrderedDict[str, dict],
    ):
        """在顺序事件和最新快照之间轮转，避免任一数据通道饥饿。"""
        prefer_latest = self._prefer_latest_topics.get(client_id, True)
        if not ordered_topic_queue.empty() and (not prefer_latest or not latest_topics):
            self._prefer_latest_topics[client_id] = True
            return ordered_topic_queue.get_nowait(), ordered_topic_queue

        if latest_topics:
            self._prefer_latest_topics[client_id] = False
            topic, message = latest_topics.popitem(last=False)
            outbound_message = await asyncio.to_thread(
                _serialize_topic_message,
                message,
            )
            if len(outbound_message) > self.max_outbound_message_bytes:
                logger.warning(
                    "Dropping oversized outbound topic update %s",
                    topic,
                )
                return None, None
            return outbound_message, None

        return None, None

    async def _close_client_socket(
        self,
        client_id: str,
        *,
        code: int,
        reason: str,
    ) -> None:
        websocket = self.active_connections.get(client_id)
        if websocket is None:
            return
        sender_task = self._sender_tasks.get(client_id)
        if (
            sender_task
            and sender_task is not asyncio.current_task()
            and not sender_task.done()
        ):
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)
        with contextlib.suppress(Exception, asyncio.TimeoutError):
            await asyncio.wait_for(
                websocket.close(code=code, reason=reason),
                timeout=max(self.send_timeout, 0.1),
            )

    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """发送消息给指定客户端"""
        message_text = _serialize_json_message(message)
        return await self._send_text_to_client(client_id, message_text)

    async def _send_text_to_client(
        self,
        client_id: str,
        message_text: str,
    ) -> bool:
        """将已序列化的可靠消息加入控制/事件 FIFO。"""
        queue = self._send_queues.get(client_id)
        if queue is None:
            return False
        # json.dumps defaults to ensure_ascii=True, so character and UTF-8 byte
        # lengths are identical; avoid allocating another full-size bytes copy.
        if len(message_text) > self.max_outbound_message_bytes:
            logger.warning("Dropping oversized outbound WebSocket response")
            return False
        try:
            await asyncio.wait_for(
                queue.put(message_text),
                timeout=self.send_timeout,
            )
            sender_event = self._sender_events.get(client_id)
            if sender_event is not None:
                sender_event.set()
            return True
        except asyncio.TimeoutError:
            logger.warning("Closing slow WebSocket client %s", client_id)
            # 关闭后 receive_text 会退出，再由上层 finally 按正确顺序清理
            # ROS 资源并删除连接元数据。
            await self._close_client_socket(
                client_id,
                code=1011,
                reason="Outbound queue timeout",
            )
            return False

    async def broadcast(self, message: dict, *, coalesce_topic: bool = True):
        """广播消息；可替换的 topic 更新按客户端只保留最新一条。"""
        if not self.active_connections:
            logger.debug("📭 No active connections for broadcast")
            return False

        sent_count = 0

        # 如果是主题消息，只发送给订阅了该主题的客户端
        if message.get("op") == "publish" and "topic" in message:
            topic = message["topic"]
            recipients = [
                client_id
                for client_id, info in list(self.connection_info.items())
                if topic in info.subscribed_topics
            ]
            if not recipients:
                return False
            if coalesce_topic:
                for client_id in recipients:
                    latest_topics = self._latest_topic_messages.get(client_id)
                    sender_event = self._sender_events.get(client_id)
                    if latest_topics is None or sender_event is None:
                        continue
                    replaced = topic in latest_topics
                    latest_topics[topic] = message
                    sender_event.set()
                    sent_count += 1
                    if replaced:
                        logger.debug(
                            "Replaced stale topic update for client %s (%s)",
                            client_id,
                            topic,
                        )
            else:
                # Marker and other delta/event topics cannot be overwritten
                # without changing their semantics. Preserve their order in a
                # separate bounded FIFO and keep control responses responsive.
                message_text = await asyncio.to_thread(
                    _serialize_json_message,
                    message,
                )
                if len(message_text) > self.max_outbound_message_bytes:
                    logger.warning("Dropping oversized ordered topic update")
                    return False
                for client_id in recipients:
                    ordered_topic_queue = self._ordered_topic_queues.get(client_id)
                    sender_event = self._sender_events.get(client_id)
                    if ordered_topic_queue is None or sender_event is None:
                        continue
                    try:
                        ordered_topic_queue.put_nowait(message_text)
                        sender_event.set()
                        sent_count += 1
                    except asyncio.QueueFull:
                        logger.debug(
                            "Dropping ordered topic update for slow client %s (%s)",
                            client_id,
                            topic,
                        )
        else:
            # 非主题消息广播给所有客户端
            results = await asyncio.gather(
                *(
                    self.send_to_client(client_id, message)
                    for client_id in list(self.active_connections)
                ),
                return_exceptions=True,
            )
            sent_count = sum(result is True for result in results)

        logger.debug("Broadcast queued for %s clients", sent_count)
        return sent_count > 0

    async def close_all(self) -> None:
        await asyncio.gather(
            *(
                self._close_client_socket(
                    client_id,
                    code=1001,
                    reason="Server shutting down",
                )
                for client_id in list(self.active_connections)
            ),
            return_exceptions=True,
        )
        tasks = list(self._sender_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sender_tasks.clear()
        self._send_queues.clear()
        self._ordered_topic_queues.clear()
        self._latest_topic_messages.clear()
        self._prefer_latest_topics.clear()
        self._sender_events.clear()
        self.active_connections.clear()
        self.connection_info.clear()
