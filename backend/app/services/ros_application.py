"""公共 ROS 应用层：会话所有权、权限和规范消息转发。"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional
import psutil
from ..models.ros import SystemStatus

from ..core.ros_types import canonical_message_type
from ..core.security import ensure_ros_operation_allowed
from .ros_contract import RosAdapter

logger = logging.getLogger(__name__)


class RosApplication:
    def __init__(self, settings, adapter: RosAdapter, connection_manager):
        self.start_time = time.monotonic()
        self.settings = settings
        self.adapter = adapter
        self.middleware = adapter.middleware
        self.connection_manager = connection_manager
        self._subscription_lock = asyncio.Lock()
        self._publisher_lock = asyncio.Lock()
        adapter.set_message_sink(self.forward_message)

    async def start(self):
        await self.adapter.start()

    async def stop(self):
        await self.adapter.stop()

    async def forward_message(self, topic, payload, message_type):
        await self.connection_manager.broadcast(
            {"op": "publish", "topic": topic, "msg": payload},
            coalesce_topic=message_type
            in {
                "sensor_msgs/msg/PointCloud2",
                "sensor_msgs/msg/LaserScan",
                "sensor_msgs/msg/Image",
                "sensor_msgs/msg/CompressedImage",
            },
        )

    def _client(self, client_id):
        info = self.connection_manager.connection_info.get(client_id)
        if info is None:
            raise ValueError("客户端会话已关闭")
        return info

    async def subscribe_client(self, client_id, topic, message_type):
        ensure_ros_operation_allowed(self.settings, "subscribe", topic)
        async with self._subscription_lock:
            info = self._client(client_id)
            if topic in info.subscribed_topics:
                return True
            if (
                len(info.subscribed_topics)
                >= self.settings.ros_max_subscriptions_per_client
            ):
                raise RuntimeError("该客户端的 ROS 订阅数量已达上限")
            if not await self.adapter.subscribe_topic(topic, message_type):
                return False
            info.subscribed_topics.append(topic)
            retained = getattr(self.adapter, "get_retained_messages", None)
            if retained:
                for payload in retained(topic):
                    await self.connection_manager.send_to_client(
                        client_id, {"op": "publish", "topic": topic, "msg": payload}
                    )
            return True

    async def unsubscribe_client(self, client_id, topic):
        async with self._subscription_lock:
            info = self.connection_manager.connection_info.get(client_id)
            if info is None or topic not in info.subscribed_topics:
                return
            info.subscribed_topics.remove(topic)
            if not any(
                topic in other.subscribed_topics
                for other in self.connection_manager.connection_info.values()
            ):
                await self.adapter.unsubscribe_topic(topic)

    async def _advertise_locked(self, client_id, topic, message_type):
        info = self._client(client_id)
        normalized = canonical_message_type(message_type)
        await self.adapter.acquire_publisher(topic, normalized, client_id)
        info.advertised_topics[topic] = normalized
        return normalized

    async def advertise_client(self, client_id, topic, message_type):
        ensure_ros_operation_allowed(self.settings, "publish", topic)
        async with self._publisher_lock:
            return await self._advertise_locked(client_id, topic, message_type)

    async def unadvertise_client(self, client_id, topic):
        async with self._publisher_lock:
            info = self.connection_manager.connection_info.get(client_id)
            if info is None or topic not in info.advertised_topics:
                return
            await self.adapter.release_publisher(topic, client_id)
            info.advertised_topics.pop(topic, None)

    async def publish_client(self, client_id, topic, message, message_type):
        ensure_ros_operation_allowed(self.settings, "publish", topic)
        async with self._publisher_lock:
            info = self._client(client_id)
            resolved = message_type or info.advertised_topics.get(topic)
            if not resolved:
                raise ValueError("发布消息缺少 type；请先声明当前会话的发布者")
            await self._advertise_locked(client_id, topic, resolved)
            return self.adapter.publish_prepared(topic, message)

    async def cleanup_client(self, client_id):
        info = self.connection_manager.connection_info.get(client_id)
        if info is None:
            return
        try:
            for topic in list(info.subscribed_topics):
                await self.unsubscribe_client(client_id, topic)
        finally:
            for topic in list(info.advertised_topics):
                await self.unadvertise_client(client_id, topic)

    async def get_topics(self, include_details=True):
        return await self.adapter.get_topics(include_details=include_details)

    async def get_topic_info(self, topic_name):
        return await self.adapter.get_topic_info(topic_name)

    async def get_nodes(self):
        return await self.adapter.get_nodes()

    async def get_node_info(self, node_name):
        return await self.adapter.get_node_info(node_name)

    async def get_topic_types(self):
        return await self.adapter.get_topic_types()

    async def get_topic_frequencies(self, sample_duration=None):
        return await self.adapter.get_topic_frequencies(sample_duration=sample_duration)

    async def get_services(self):
        return await self.adapter.get_services()

    async def get_service_types(self):
        return await self.adapter.get_service_types()

    async def get_params(self):
        return await self.adapter.get_params()

    async def get_system_status(self) -> SystemStatus:
        """获取系统状态"""
        topics = await self.get_topics(include_details=False)
        nodes = await self.get_nodes()
        cpu_usage = 0.0
        memory_usage = 0.0
        cpu_temperature = None

        if psutil:
            cpu_usage = psutil.cpu_percent(interval=None)
            memory_usage = psutil.virtual_memory().percent
            cpu_temperature = self._get_cpu_temperature()

        return SystemStatus(
            ros_domain_id=self.settings.ros_domain_id if self.middleware == 'ros2' else None,
            active_nodes=len(nodes),
            active_topics=len(topics),
            active_connections=len(self.connection_manager.active_connections),
            system_time=datetime.now(),
            uptime=time.monotonic() - self.start_time,
            memory_usage=memory_usage,
            cpu_usage=cpu_usage,
            cpu_temperature=cpu_temperature,
        )

    def _get_cpu_temperature(self) -> Optional[float]:
        """读取 CPU 温度，优先使用 psutil，失败时尝试 Linux thermal zone。"""
        if psutil and hasattr(psutil, "sensors_temperatures"):
            try:
                temperatures = psutil.sensors_temperatures() or {}
                preferred_keys = ("coretemp", "k10temp", "cpu_thermal", "soc_thermal")
                for key in preferred_keys:
                    entries = temperatures.get(key)
                    if entries:
                        values = [
                            entry.current
                            for entry in entries
                            if entry.current is not None
                        ]
                        if values:
                            return round(max(values), 1)
                for entries in temperatures.values():
                    values = [
                        entry.current for entry in entries if entry.current is not None
                    ]
                    if values:
                        return round(max(values), 1)
            except Exception as e:
                logger.debug(f"Could not read CPU temperature from psutil: {e}")

        thermal_root = "/sys/class/thermal"
        try:
            for name in os.listdir(thermal_root):
                if not name.startswith("thermal_zone"):
                    continue
                temp_path = os.path.join(thermal_root, name, "temp")
                with open(temp_path, "r", encoding="utf-8") as temp_file:
                    raw_value = temp_file.read().strip()
                if raw_value:
                    value = float(raw_value)
                    return round(value / 1000.0 if value > 1000 else value, 1)
        except Exception as e:
            logger.debug(f"Could not read CPU temperature from thermal zone: {e}")

        return None

    async def publish_message(self, topic_name, message, message_type=None):
        ensure_ros_operation_allowed(self.settings, "publish", topic_name)
        return await self.adapter.publish_message(topic_name, message, message_type)
