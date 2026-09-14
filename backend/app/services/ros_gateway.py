"""浏览器 WebSocket 协议与 ROS 服务之间的 Gateway。"""

import asyncio
import json
import logging
import time
import uuid
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

from ..core.config import Settings
from .connection_manager import ConnectionManager
from .ros_contract import RosSessionService
from .ws_handlers import WebSocketRequestHandler

logger = logging.getLogger(__name__)


class RosGateway:
    """管理 WebSocket 连接、协议校验、限流和客户端 ROS 资源。"""

    def __init__(
        self,
        settings: Settings,
        service: RosSessionService,
        connection_manager: ConnectionManager,
    ):
        self.settings = settings
        self.service = service
        self.connection_manager = connection_manager
        self._handler = WebSocketRequestHandler(service, connection_manager)
        self._sessions = set()
        self._stopping = False

    async def stop(self) -> None:
        """关闭全部浏览器连接；ROS 中间件由具体服务单独停止。"""
        self._stopping = True
        tasks = list(self._sessions)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # 清理先于连接元数据删除，确保最后一位订阅者的资源可被释放。
        for client_id in list(self.connection_manager.connection_info):
            await self.service.cleanup_client(client_id)
        await self.connection_manager.close_all()

    async def handle_websocket(self, websocket: WebSocket) -> None:
        if self._stopping:
            await websocket.close(code=1001, reason="Server shutting down")
            return
        task = asyncio.current_task()
        self._sessions.add(task)
        try:
            await self._serve(websocket)
        finally:
            self._sessions.discard(task)

    async def _serve(self, websocket: WebSocket) -> None:
        client_id = self.new_client_id()
        request_times = deque()

        if not await self.connection_manager.connect(websocket, client_id):
            return

        try:
            while True:
                data = await websocket.receive_text()
                request_now = time.monotonic()
                while request_times and request_times[0] <= request_now - 1:
                    request_times.popleft()
                if (
                    len(request_times)
                    >= self.settings.websocket_max_requests_per_second
                ):
                    await websocket.close(code=1008, reason="Rate limit exceeded")
                    return
                request_times.append(request_now)

                if (
                    len(data.encode("utf-8"))
                    > self.settings.websocket_max_message_bytes
                ):
                    await websocket.close(code=1009, reason="Message too large")
                    return

                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    await self.connection_manager.send_to_client(
                        client_id,
                        {"op": "error", "error": "WebSocket 消息不是有效 JSON"},
                    )
                    continue
                if not isinstance(message, dict):
                    await self.connection_manager.send_to_client(
                        client_id,
                        {"op": "error", "error": "WebSocket 消息必须是对象"},
                    )
                    continue
                await self.handle_message(client_id, message)
        except WebSocketDisconnect:
            logger.info("Client %s disconnected", client_id)
        except Exception as error:
            logger.error("WebSocket error for %s: %s", client_id, error)
        finally:
            try:
                await self.service.cleanup_client(client_id)
            finally:
                try:
                    await websocket.close()
                except Exception:
                    pass
                self.connection_manager.disconnect(client_id)

    @staticmethod
    def new_client_id() -> str:
        return f"client_{uuid.uuid4().hex}"

    async def handle_message(self, client_id: str, message: dict) -> None:
        await self._handler.handle_operation(client_id, message)
