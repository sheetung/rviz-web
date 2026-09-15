"""当前基于 rclpy 的 ROS2 服务实现。"""

import asyncio
import logging
import subprocess
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)

from ...core.config import Settings
from ...core.ros_types import canonical_message_type
from ...models.ros import NodeInfo, TopicInfo
from typing import Awaitable, Callable
from .frequency_tracker import FrequencyTracker
from .message_converter import MessageConverter
from .message_types import get_message_class

logger = logging.getLogger(__name__)

_POINTCLOUD_MESSAGE_TYPES = {
    "sensor_msgs/msg/PointCloud2",
}

# These messages describe a complete current sample. Replacing an unsent
# sample with a newer one is safe. Marker/MarkerArray are deliberately absent:
# they may contain DELETE/DELETEALL deltas that must remain ordered.
_LATEST_ONLY_MESSAGE_TYPES = _POINTCLOUD_MESSAGE_TYPES | {
    "sensor_msgs/msg/LaserScan",
    "sensor_msgs/msg/Image",
    "sensor_msgs/msg/CompressedImage",
}


class Ros2Adapter:
    """基于 rclpy 的 ROS2 服务实现。"""

    middleware = "ros2"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._message_sink = None
        self._converter = MessageConverter(settings)
        self._freq = FrequencyTracker(
            message_class_resolver=lambda msg_type: self._get_message_class(msg_type),
            frequency_clock=lambda: self._frequency_clock(),
            wall_clock=lambda: time.time(),
            sleep=lambda duration: asyncio.sleep(duration),
        )
        self.node: Optional[Node] = None
        self.subscribers = {}
        self._subscription_types: Dict[str, str] = {}
        self._topic_forward_buckets: Dict[str, tuple[float, float]] = {}
        self.publishers = {}
        self.message_cache = deque(maxlen=settings.message_buffer_size)
        self.topic_info_cache = {}
        self.node_info_cache = {}
        self._topic_cache = {}
        self._node_cache = None
        self._topic_cache_lock = asyncio.Lock()
        self._node_cache_lock = asyncio.Lock()
        self._subscription_lock = asyncio.Lock()
        self._publisher_lock = asyncio.Lock()
        self._message_counts = {}

        # 异步消息处理队列
        self.message_queue = None
        self._pending_latest_messages = {}
        self._queued_topics = set()
        self.message_processor_task = None
        self._loop = None

        self._cache_warning_counts = {}  # 缓存警告计数

    # Compatibility aliases keep callers stable while state and behavior live
    # in the focused helper modules.
    @property
    def _topic_message_times(self):
        return self._freq._topic_message_times

    @property
    def _topic_last_message_times(self):
        return self._freq._topic_last_message_times

    @property
    def _topic_observation_started_at(self):
        return self._freq._topic_observation_started_at

    @property
    def _sampled_topic_frequencies(self):
        return self._freq._sampled_topic_frequencies

    @_sampled_topic_frequencies.setter
    def _sampled_topic_frequencies(self, value):
        self._freq._sampled_topic_frequencies = value

    @property
    def _frequency_sampled_at(self):
        return self._freq._frequency_sampled_at

    @_frequency_sampled_at.setter
    def _frequency_sampled_at(self, value):
        self._freq._frequency_sampled_at = value

    @property
    def _frequency_sample_lock(self):
        return self._freq._sample_lock

    def _get_message_class(self, msg_type: str):
        return get_message_class(msg_type)

    @staticmethod
    def _subscriber_history_settings(msg_type: str, publisher_qos_profiles):
        """高带宽快照只缓存最新样本，其他类型保持原有兼容策略。"""
        if msg_type in _LATEST_ONLY_MESSAGE_TYPES:
            return QoSHistoryPolicy.KEEP_LAST, 1
        if (
            publisher_qos_profiles
            and publisher_qos_profiles[0].history == QoSHistoryPolicy.KEEP_ALL
        ):
            return QoSHistoryPolicy.KEEP_ALL, 1000
        return QoSHistoryPolicy.KEEP_LAST, 10

    def _topic_frequency(
        self, topic_name: str, now: Optional[float] = None
    ) -> Optional[float]:
        return self._freq.get_frequency(topic_name, topic_name in self.subscribers, now)

    @staticmethod
    def _frequency_from_samples(timestamps) -> Optional[float]:
        return FrequencyTracker._from_samples(timestamps)

    @staticmethod
    def _frequency_clock() -> float:
        return time.monotonic()

    async def _sample_topic_frequencies(
        self,
        sample_duration: float,
    ) -> Dict[str, Optional[float]]:
        return await self._freq.sample_frequencies(self.node, sample_duration)

    async def start(self):
        """启动服务"""
        try:
            # 获取当前事件循环
            self._loop = asyncio.get_event_loop()

            # 初始化异步消息队列
            self.message_queue = asyncio.Queue(maxsize=1000)
            self._pending_latest_messages = {}
            self._queued_topics = set()

            # 初始化 ROS2
            if not rclpy.ok():
                rclpy.init()

            self.node = Node("ros_web_viz_bridge")
            logger.info("ROS2 node initialized")

            # 启动消息处理任务
            self.message_processor_task = asyncio.create_task(
                self._message_processor_loop()
            )

            # 🔥 启动ROS2事件循环 - 这是关键！
            self.ros_spin_task = asyncio.create_task(self._ros_spin_loop())

        except Exception as e:
            logger.error(f"Failed to start ROS2 service: {e}")
            raise

    async def stop(self):
        """停止服务"""
        try:
            # 停止消息处理任务
            if self.message_processor_task and not self.message_processor_task.done():
                self.message_processor_task.cancel()
                try:
                    await self.message_processor_task
                except asyncio.CancelledError:
                    pass

            # 停止ROS spin任务
            if (
                hasattr(self, "ros_spin_task")
                and self.ros_spin_task
                and not self.ros_spin_task.done()
            ):
                self.ros_spin_task.cancel()
                try:
                    await self.ros_spin_task
                except asyncio.CancelledError:
                    pass

            if self.node:
                self.node.destroy_node()
                self.node = None
            self.subscribers.clear()
            self.publishers.clear()
            self._subscription_types.clear()
            self._pending_latest_messages.clear()
            self._queued_topics.clear()
            self._topic_cache.clear()
            self._node_cache = None
            if rclpy.ok():
                rclpy.shutdown()
            logger.info("ROS2 service stopped")
        except Exception as e:
            logger.error(f"Error stopping ROS2 service: {e}")

    async def _create_subscriber(self, topic: str, msg_type: str):
        """创建 ROS2 订阅者"""
        try:
            msg_type = canonical_message_type(msg_type)
            # 获取消息类
            msg_class = get_message_class(msg_type)

            if msg_class is None:
                logger.error(
                    f"Cannot create subscriber for {topic}: unsupported or unavailable message type {msg_type}"
                )
                return

            def callback(msg):
                # ROS2回调必须是同步的，但我们需要异步处理
                # 使用线程安全的方式将消息放入队列
                logger.debug(
                    f"🚀 ROS2 CALLBACK TRIGGERED for {topic}! Message type: {type(msg).__name__}"
                )
                try:
                    # 调用同步版本的消息处理
                    self._on_message_received_sync(topic, msg)
                    logger.debug(f"✅ Successfully processed callback for {topic}")
                except Exception as e:
                    logger.error(f"❌ Error in message callback for {topic}: {e}")

            # 使用兼容的QoS配置 - 优先兼容rosbag2_player

            # 首先尝试检测发布者的QoS设置
            publisher_qos_profiles = []
            if self.node:
                try:
                    # 获取发布者信息
                    publishers_info = self.node.get_publishers_info_by_topic(topic)
                    logger.info(
                        f"Found {len(publishers_info)} publishers for topic {topic}"
                    )
                    for pub_info in publishers_info:
                        publisher_qos_profiles.append(pub_info.qos_profile)
                        logger.info(
                            "Publisher %s QoS: reliability=%s, durability=%s, "
                            "history=%s, depth=%s",
                            pub_info.node_name,
                            pub_info.qos_profile.reliability,
                            pub_info.qos_profile.durability,
                            pub_info.qos_profile.history,
                            pub_info.qos_profile.depth,
                        )
                except Exception as e:
                    logger.warning(f"Could not get publisher QoS info for {topic}: {e}")

            # 如果没有获取到发布者信息，再次尝试等待一下
            if not publisher_qos_profiles and self.node:
                logger.info(
                    f"No publisher info found initially for {topic}, waiting and retrying..."
                )
                await asyncio.sleep(0.1)  # 等待100ms
                try:
                    publishers_info = self.node.get_publishers_info_by_topic(topic)
                    for pub_info in publishers_info:
                        publisher_qos_profiles.append(pub_info.qos_profile)
                        logger.info(
                            "Publisher %s QoS (retry): reliability=%s, durability=%s",
                            pub_info.node_name,
                            pub_info.qos_profile.reliability,
                            pub_info.qos_profile.durability,
                        )
                except Exception as e:
                    logger.warning(
                        f"Could not get publisher QoS info for {topic} on retry: {e}"
                    )

            # 分析发布者的实际QoS并尽量兼容。传感器数据常用 BEST_EFFORT；
            # 如果订阅端使用 RELIABLE，会和 BEST_EFFORT 发布者不兼容，导致收不到点云。
            logger.info(f"🔧 Analyzing publisher QoS for {topic}")

            sensor_like_types = {
                "sensor_msgs/msg/PointCloud2",
                "sensor_msgs/msg/LaserScan",
                "sensor_msgs/msg/Image",
                "sensor_msgs/msg/CompressedImage",
                "mars_quadrotor_msgs/msg/PositionCommand",
            }

            reliability = (
                QoSReliabilityPolicy.BEST_EFFORT
                if msg_type in sensor_like_types
                else QoSReliabilityPolicy.RELIABLE
            )
            durability = (
                QoSDurabilityPolicy.TRANSIENT_LOCAL
                if topic == "/tf_static"
                else QoSDurabilityPolicy.VOLATILE
            )
            history, depth = self._subscriber_history_settings(
                msg_type,
                publisher_qos_profiles,
            )

            if publisher_qos_profiles:
                first_pub_qos = publisher_qos_profiles[0]
                logger.info(
                    "📊 Raw publisher QoS: reliability=%s, durability=%s, "
                    "history=%s, depth=%s",
                    first_pub_qos.reliability,
                    first_pub_qos.durability,
                    first_pub_qos.history,
                    first_pub_qos.depth,
                )

                if first_pub_qos.reliability == QoSReliabilityPolicy.BEST_EFFORT:
                    reliability = QoSReliabilityPolicy.BEST_EFFORT

                if first_pub_qos.durability == QoSDurabilityPolicy.TRANSIENT_LOCAL:
                    durability = QoSDurabilityPolicy.TRANSIENT_LOCAL

            qos_profile = QoSProfile(
                reliability=reliability,
                durability=durability,
                history=history,
                depth=depth,
            )
            logger.info(f"🎯 Using compatible QoS for {topic}")

            logger.info(
                "✨ Final QoS for %s: reliability=%s, durability=%s, "
                "history=%s, depth=%s",
                topic,
                qos_profile.reliability.name,
                qos_profile.durability.name,
                qos_profile.history.name,
                qos_profile.depth,
            )

            # 记录最终的QoS配置
            reliability_name = (
                qos_profile.reliability.name
                if hasattr(qos_profile.reliability, "name")
                else str(qos_profile.reliability)
            )
            durability_name = (
                qos_profile.durability.name
                if hasattr(qos_profile.durability, "name")
                else str(qos_profile.durability)
            )
            history_name = (
                qos_profile.history.name
                if hasattr(qos_profile.history, "name")
                else str(qos_profile.history)
            )
            logger.info(
                "Creating subscriber for %s with QoS: reliability=%s, "
                "durability=%s, history=%s, depth=%s",
                topic,
                reliability_name,
                durability_name,
                history_name,
                qos_profile.depth,
            )

            # 创建订阅者 - 使用简化的单一配置
            try:
                subscriber = self.node.create_subscription(
                    msg_class, topic, callback, qos_profile
                )

                self.subscribers[topic] = subscriber
                self._subscription_types[topic] = msg_type
                self._freq.mark_observation_start(topic)
                logger.info(f"✅ Successfully created subscriber for {topic}")
                logger.info(
                    f"🎯 QoS: {reliability_name} + {durability_name} + {history_name} + depth={qos_profile.depth}"
                )

            except Exception as e:
                logger.error(f"❌ Failed to create subscriber for {topic}: {e}")
                logger.error(
                    "💡 This usually indicates QoS incompatibility with publishers"
                )
                raise e

            # 启动一个简单的数据检查任务
            asyncio.create_task(self._check_topic_data(topic, 10.0))  # 10秒后检查

        except Exception as e:
            logger.error(f"Failed to create subscriber for {topic}: {e}")

    async def _check_topic_data(self, topic: str, delay: float):
        """检查主题是否有数据发布"""
        await asyncio.sleep(delay)

        if not hasattr(self, "_message_counts") or topic not in self._message_counts:
            # 检查系统中是否有发布者
            if self.node:
                topic_info = self.node.get_publishers_info_by_topic(topic)
                publisher_count = len(topic_info)

                if publisher_count == 0:
                    logger.warning(
                        f"🚨 Topic {topic} has no publishers in the ROS system"
                    )
                    logger.info(
                        f"💡 To publish test data, try: ros2 topic pub {topic} <msg_type> '<data>'"
                    )
                else:
                    logger.warning(
                        f"⚠️ Topic {topic} has {publisher_count} publisher(s) but no messages received"
                    )
                    logger.info(
                        f"📊 Publishers: {[pub.node_name for pub in topic_info]}"
                    )
            else:
                logger.error(f"❌ ROS node not initialized, cannot check topic {topic}")
        else:
            logger.info(
                f"✅ Topic {topic} is receiving data normally ({self._message_counts[topic]} messages)"
            )

    def _on_message_received_sync(self, topic: str, msg):
        """同步消息处理入口 - 从ROS2回调调用

        这个方法在ROS2回调线程中被调用，需要线程安全地将消息传递到异步处理循环
        """
        try:
            if self._loop and self.message_queue:
                # 记录第一次接收到消息
                if not hasattr(self, "_first_message_logged"):
                    self._first_message_logged = set()

                if topic not in self._first_message_logged:
                    logger.info(
                        f"🚀 First ROS2 callback received for topic {topic}, type: {type(msg).__name__}"
                    )
                    self._first_message_logged.add(topic)

                # 使用call_soon_threadsafe将消息传递到异步循环
                self._loop.call_soon_threadsafe(self._enqueue_message, topic, msg)
            else:
                logger.error(
                    f"❌ Message loop or queue not initialized for topic {topic}"
                )
                logger.error(
                    f"   Loop: {self._loop is not None}, Queue: {self.message_queue is not None}"
                )
        except Exception as e:
            logger.error(
                f"❌ Error in sync message handler for {topic}: {e}", exc_info=True
            )

    def _enqueue_message(self, topic: str, msg):
        """将消息放入异步队列 - 在事件循环中调用"""
        try:
            if self.message_queue:
                self._pending_latest_messages[topic] = (msg, time.time())

                if topic in self._queued_topics:
                    logger.debug(
                        f"📥 Coalesced latest message for {topic}, queue size: {self.message_queue.qsize()}"
                    )
                    return

                try:
                    # 队列只保存 topic 名，同一 topic 的高频消息在 _pending_latest_messages 中合并为最新帧
                    self._queued_topics.add(topic)
                    self.message_queue.put_nowait(topic)
                    logger.debug(
                        f"📥 Enqueued message for {topic}, queue size: {self.message_queue.qsize()}"
                    )
                except asyncio.QueueFull:
                    self._queued_topics.discard(topic)
                    logger.warning(
                        f"⚠️ Message queue full (size: {self.message_queue.maxsize}), dropping message for {topic}"
                    )
                    logger.warning(
                        "   Latest-message coalescing is enabled; consider reducing subscribed topic rates"
                    )
            else:
                logger.error(f"❌ Message queue not initialized for {topic}")
        except Exception as e:
            logger.error(f"❌ Error enqueuing message for {topic}: {e}", exc_info=True)

    async def _message_processor_loop(self):
        """异步消息处理循环 - 从队列中取出消息并处理"""
        logger.info("Starting message processor loop")

        # 初始化消息计数
        if not hasattr(self, "_message_counts"):
            self._message_counts = {}

        try:
            while True:
                try:
                    # 从队列中获取 topic，再取该 topic 最新消息
                    topic = await self.message_queue.get()
                    pending = self._pending_latest_messages.pop(topic, None)
                    self._queued_topics.discard(topic)

                    if pending is None:
                        self.message_queue.task_done()
                        continue

                    msg, timestamp = pending

                    # 记录消息接收
                    if topic not in self._message_counts:
                        self._message_counts[topic] = 0
                    self._message_counts[topic] += 1
                    self._freq.record_message(topic, timestamp)

                    # 只记录第一条消息，减少日志输出
                    if self._message_counts[topic] == 1:
                        logger.info(
                            f"🎉 First message received on topic {topic}! Type: {type(msg).__name__}"
                        )
                        logger.info(
                            f"✅ Successfully bridged ROS2 callback to async processing for {topic}"
                        )
                    # 移除频繁的统计日志以避免刷屏

                    logger.debug(
                        "📨 Processing message on topic %s, type: %s, queue size: %s",
                        topic,
                        type(msg).__name__,
                        self.message_queue.qsize(),
                    )

                    # 调用原有的异步消息处理逻辑
                    await self._on_message_received(topic, msg)

                    # 标记任务完成
                    self.message_queue.task_done()

                except asyncio.CancelledError:
                    logger.info("Message processor loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in message processor loop: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Fatal error in message processor loop: {e}", exc_info=True)
        finally:
            logger.info("Message processor loop stopped")

    async def _ros_spin_loop(self):
        """异步ROS2事件循环 - 处理ROS回调"""
        logger.info(
            "🔥 Starting ROS2 spin loop - THIS IS CRITICAL FOR MESSAGE RECEPTION!"
        )

        try:
            while True:
                # 与 HTTP/WS 共用事件循环，不能在这里等待 DDS 数据。
                if self.node:
                    rclpy.spin_once(self.node, timeout_sec=0.0)

                # 让出控制权给其他协程
                await asyncio.sleep(0.001)  # 1ms间隔，保持高响应性

        except asyncio.CancelledError:
            logger.info("ROS2 spin loop cancelled")
        except ExternalShutdownException:
            logger.info("ROS2 context shut down")
        except Exception as e:
            # SIGINT 也可能恰好发生在构造 wait set 时，表现为 RCLError。
            if not rclpy.ok():
                logger.info("ROS2 spin stopped after context shutdown: %s", e)
            else:
                logger.error(f"Fatal error in ROS2 spin loop: {e}", exc_info=True)
        finally:
            logger.info("ROS2 spin loop stopped")

    def _claim_topic_forward_slot(
        self,
        topic: str,
        now: Optional[float] = None,
    ) -> bool:
        """在昂贵的转换前限制点云转发频率。"""
        message_type = self._subscription_types.get(topic, "")
        if message_type not in _POINTCLOUD_MESSAGE_TYPES:
            return True

        max_hz = self.settings.ros_pointcloud_max_hz
        if max_hz <= 0:
            return True

        current_time = time.monotonic() if now is None else now
        # A two-token bucket keeps the long-run rate bounded while absorbing
        # normal publisher jitter. A strict ``elapsed >= 1 / max_hz`` gate can
        # turn a nominal 10 Hz source into roughly 6-7 Hz when adjacent samples
        # arrive a few milliseconds early.
        capacity = 2.0
        bucket = self._topic_forward_buckets.get(topic)
        if bucket is None:
            self._topic_forward_buckets[topic] = (current_time, capacity - 1.0)
            return True

        updated_at, tokens = bucket
        elapsed = max(0.0, current_time - updated_at)
        tokens = min(capacity, tokens + elapsed * max_hz)
        if tokens < 1.0:
            self._topic_forward_buckets[topic] = (current_time, tokens)
            return False

        self._topic_forward_buckets[topic] = (current_time, tokens - 1.0)
        return True

    def set_message_sink(
        self, sink: Callable[[str, dict, str], Awaitable[None]]
    ) -> None:
        """注册规范消息回调；适配器不感知浏览器和传输协议。"""
        self._message_sink = sink

    async def _on_message_received(self, topic: str, msg):
        subscriber = self.subscribers.get(topic)
        message_type = self._subscription_types.get(topic)
        sink = self._message_sink
        if sink is None or subscriber is None or message_type is None:
            return
        if not self._claim_topic_forward_slot(topic):
            return
        payload = await asyncio.to_thread(self._converter.to_dict, msg)
        # 转换期间可能取消并重新订阅同名话题，旧帧不能交给新订阅。
        if (
            self.subscribers.get(topic) is not subscriber
            or self._subscription_types.get(topic) != message_type
            or self._message_sink is not sink
        ):
            return
        await sink(topic, payload, message_type)
        self.message_cache.append({"topic": topic, "timestamp": time.time()})

    def publish_prepared(self, topic: str, message: Dict[str, Any]) -> str:
        """向已创建的 ROS publisher 写入规范消息。"""
        record = self.publishers[topic]
        converted = self._converter.from_dict(record["msg_class"], message)
        if converted is None:
            raise ValueError("无法转换 ROS 消息")
        record["publisher"].publish(converted)
        return record["msg_type"]

    # API 方法实现
    def _get_topics_from_cli_sync(self) -> List[TopicInfo]:
        """Read the live ROS graph using the ros2 CLI."""
        try:
            result = subprocess.run(
                ["ros2", "topic", "list", "-t", "--no-daemon"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except FileNotFoundError:
            logger.debug("ros2 CLI not found, falling back to rclpy topic discovery")
            return []
        except subprocess.TimeoutExpired:
            logger.warning(
                "ros2 topic list timed out, falling back to rclpy topic discovery"
            )
            return []
        except Exception as e:
            logger.debug(f"Failed to read topics from ros2 CLI: {e}")
            return []

        if result.returncode != 0:
            logger.debug(f"ros2 topic list failed: {result.stderr.strip()}")
            return []

        topics = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.endswith("]") and " [" in line:
                name, _, type_part = line.rpartition(" [")
                raw_message_type = type_part[:-1].strip() or "unknown"
                try:
                    message_type = canonical_message_type(raw_message_type)
                except ValueError:
                    logger.warning(
                        "Ignoring invalid ROS2 CLI message type %s for %s",
                        raw_message_type,
                        name,
                    )
                    message_type = "unknown"
            else:
                name = line
                message_type = "unknown"

            if name:
                topics.append(
                    TopicInfo(
                        name=name,
                        message_type=message_type,
                        publishers=[],
                        subscribers=[],
                    )
                )

        return topics

    async def _get_topics_from_cli(self) -> List[TopicInfo]:
        """异步读取 ros2 CLI，避免阻塞 WebSocket 事件循环。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "ros2",
                "topic",
                "list",
                "-t",
                "--no-daemon",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=3,
            )
        except FileNotFoundError:
            logger.debug("ros2 CLI not found, falling back to rclpy topic discovery")
            return []
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("ros2 topic list timed out, falling back to rclpy")
            return []
        except Exception as error:
            logger.debug("Failed to read topics from ros2 CLI: %s", error)
            return []

        if process.returncode != 0:
            logger.debug(
                "ros2 topic list failed: %s",
                stderr.decode("utf-8", errors="replace").strip(),
            )
            return []

        topics = []
        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("]") and " [" in line:
                name, _, type_part = line.rpartition(" [")
                raw_message_type = type_part[:-1].strip() or "unknown"
                try:
                    message_type = canonical_message_type(raw_message_type)
                except ValueError:
                    logger.warning(
                        "Ignoring invalid ROS2 CLI message type %s for %s",
                        raw_message_type,
                        name,
                    )
                    message_type = "unknown"
            else:
                name = line
                message_type = "unknown"
            if name:
                topics.append(
                    TopicInfo(
                        name=name,
                        message_type=message_type,
                        publishers=[],
                        subscribers=[],
                    )
                )
        return topics

    @staticmethod
    def _endpoint_node_name(endpoint) -> str:
        node_name = str(getattr(endpoint, "node_name", "") or "").strip("/")
        namespace = str(getattr(endpoint, "node_namespace", "") or "").strip("/")
        if not node_name:
            return ""
        return f"/{namespace}/{node_name}" if namespace else f"/{node_name}"

    def _enrich_topic_info(self, topic: TopicInfo, now: float) -> TopicInfo:
        if self.node:
            try:
                topic.publishers = sorted(
                    filter(
                        None,
                        {
                            self._endpoint_node_name(info)
                            for info in self.node.get_publishers_info_by_topic(
                                topic.name
                            )
                        },
                    )
                )
            except Exception as e:
                logger.debug(f"Could not get publishers for {topic.name}: {e}")

            try:
                topic.subscribers = sorted(
                    filter(
                        None,
                        {
                            self._endpoint_node_name(info)
                            for info in self.node.get_subscriptions_info_by_topic(
                                topic.name
                            )
                        },
                    )
                )
            except Exception as e:
                logger.debug(f"Could not get subscribers for {topic.name}: {e}")

        topic.frequency = self._freq.get_frequency(
            topic.name, topic.name in self.subscribers, now
        )
        last_message_time = self._freq.get_last_message_time(topic.name)
        topic.last_message_time = (
            datetime.fromtimestamp(last_message_time, tz=timezone.utc)
            if last_message_time is not None
            else None
        )
        return topic

    async def get_topics(self, include_details: bool = True) -> List[TopicInfo]:
        """获取主题列表"""
        now_monotonic = time.monotonic()
        cached = self._topic_cache.get(include_details)
        if cached and now_monotonic - cached[0] < self.settings.ros_graph_cache_ttl:
            return [topic.model_copy(deep=True) for topic in cached[1]]

        async with self._topic_cache_lock:
            now_monotonic = time.monotonic()
            cached = self._topic_cache.get(include_details)
            if cached and now_monotonic - cached[0] < self.settings.ros_graph_cache_ttl:
                return [topic.model_copy(deep=True) for topic in cached[1]]

            cli_topics = await self._get_topics_from_cli()
            if cli_topics:
                topics = cli_topics
            elif not self.node:
                topics = []
            else:
                try:
                    topics = [
                        TopicInfo(
                            name=name,
                            message_type=(
                                canonical_message_type(types[0]) if types else "unknown"
                            ),
                            publishers=[],
                            subscribers=[],
                        )
                        for name, types in self.node.get_topic_names_and_types()
                    ]
                except Exception as e:
                    logger.error(f"Failed to get topics: {e}")
                    topics = []

            if include_details:
                wall_now = time.time()
                topics = [self._enrich_topic_info(topic, wall_now) for topic in topics]
            self._topic_cache[include_details] = (
                now_monotonic,
                [topic.model_copy(deep=True) for topic in topics],
            )
            return topics

    async def get_topic_info(self, topic_name: str) -> Optional[TopicInfo]:
        """获取主题信息"""
        topics = await self.get_topics()
        for topic in topics:
            if topic.name == topic_name:
                return topic
        return None

    async def _resolve_topic_message_type(
        self, topic_name: str, requested_type: Optional[str] = None
    ) -> Optional[str]:
        """根据 ROS graph 中的实际 topic 信息解析订阅类型。"""
        requested_type = (
            canonical_message_type(requested_type) if requested_type else None
        )
        publisher_types = []
        if self.node:
            try:
                publisher_types = [
                    canonical_message_type(info.topic_type)
                    for info in self.node.get_publishers_info_by_topic(topic_name)
                    if getattr(info, "topic_type", None)
                ]
            except Exception as e:
                logger.debug(f"Could not inspect publishers for {topic_name}: {e}")

        unique_publisher_types = list(dict.fromkeys(publisher_types))
        if unique_publisher_types:
            resolved_type = (
                requested_type
                if requested_type in unique_publisher_types
                else unique_publisher_types[0]
            )
            if requested_type and requested_type != resolved_type:
                logger.warning(
                    f"Requested type {requested_type} for {topic_name} does not match publisher type "
                    f"{resolved_type}; using publisher type"
                )
            return resolved_type

        topic_info = await self.get_topic_info(topic_name)
        discovered_type = topic_info.message_type if topic_info else None
        if discovered_type and discovered_type != "unknown":
            if requested_type and requested_type != discovered_type:
                logger.warning(
                    f"Requested type {requested_type} for {topic_name} does not match discovered type "
                    f"{discovered_type}; using discovered type"
                )
            return discovered_type

        return requested_type

    async def subscribe_topic(
        self, topic_name: str, message_type: Optional[str] = None
    ) -> bool:
        """订阅主题"""
        async with self._subscription_lock:
            return await self._subscribe_topic_locked(topic_name, message_type)

    async def _subscribe_topic_locked(
        self,
        topic_name: str,
        message_type: Optional[str] = None,
    ) -> bool:
        try:
            if not self.node:
                logger.error("Cannot subscribe before ROS2 node is initialized")
                return False

            if topic_name in self.subscribers:
                return True

            msg_type = await self._resolve_topic_message_type(
                topic_name,
                message_type,
            )

            if not msg_type or msg_type == "unknown":
                logger.error(f"Cannot subscribe to {topic_name}: unknown message type")
                return False

            await self._create_subscriber(topic_name, msg_type)
            return topic_name in self.subscribers
        except Exception as e:
            logger.error(f"Failed to subscribe to {topic_name}: {e}")
            return False

    async def unsubscribe_topic(self, topic_name: str) -> bool:
        """取消订阅主题"""
        async with self._subscription_lock:
            return self._unsubscribe_topic_locked(topic_name)

    def _unsubscribe_topic_locked(self, topic_name: str) -> bool:
        try:
            subscriber = self.subscribers.pop(topic_name, None)
            if subscriber and self.node:
                self.node.destroy_subscription(subscriber)
            self._subscription_types.pop(topic_name, None)
            self._topic_forward_buckets.pop(topic_name, None)
            self._freq.cleanup_topic(topic_name)
            self._message_counts.pop(topic_name, None)
            return True
        except Exception as e:
            logger.error(f"Failed to unsubscribe from {topic_name}: {e}")
            return False

    async def publish_message(
        self,
        topic_name: str,
        message: Dict[str, Any],
        message_type: Optional[str] = None,
    ) -> bool:
        """发布消息"""
        try:
            if not self.node:
                logger.error("Cannot publish before ROS2 node is initialized")
                return False

            publisher_record = self.publishers.get(topic_name)
            msg_type = message_type or (publisher_record or {}).get("msg_type")
            if not msg_type:
                topic_info = await self.get_topic_info(topic_name)
                msg_type = topic_info.message_type if topic_info else None

            if not msg_type or msg_type == "unknown":
                logger.error(f"Cannot publish to {topic_name}: unknown message type")
                return False

            msg_type = canonical_message_type(msg_type)

            # REST 请求可能并发发布到同一 topic。每个请求必须持有独立 owner，
            # 否则先结束的请求会移除共享 owner，并销毁仍被其他请求使用的 Publisher。
            rest_owner = f"rest_{uuid.uuid4().hex}"
            await self.acquire_publisher(topic_name, msg_type, rest_owner)
            try:
                publisher_record = self.publishers.get(topic_name)
                if not publisher_record:
                    return False

                ros_msg = self._converter.from_dict(
                    publisher_record["msg_class"],
                    message,
                )
                if ros_msg is None:
                    return False

                publisher_record["publisher"].publish(ros_msg)
                return True
            finally:
                await self.release_publisher(topic_name, rest_owner)
        except Exception as e:
            logger.error(f"Failed to publish to {topic_name}: {e}")
            return False

    async def get_nodes(self) -> List[NodeInfo]:
        """获取节点列表"""
        if not self.node:
            return []

        now_monotonic = time.monotonic()
        if (
            self._node_cache
            and now_monotonic - self._node_cache[0] < self.settings.ros_graph_cache_ttl
        ):
            return [node.model_copy(deep=True) for node in self._node_cache[1]]

        async with self._node_cache_lock:
            now_monotonic = time.monotonic()
            if (
                self._node_cache
                and now_monotonic - self._node_cache[0]
                < self.settings.ros_graph_cache_ttl
            ):
                return [node.model_copy(deep=True) for node in self._node_cache[1]]
            try:
                if hasattr(self.node, "get_node_names_and_namespaces"):
                    node_entries = self.node.get_node_names_and_namespaces()
                else:
                    node_entries = [(name, "/") for name in self.node.get_node_names()]
                relationships = {
                    (name, namespace): {"publishers": set(), "subscribers": set()}
                    for name, namespace in node_entries
                }
                for topic_name, _ in self.node.get_topic_names_and_types():
                    try:
                        for endpoint in self.node.get_publishers_info_by_topic(
                            topic_name
                        ):
                            key = (
                                endpoint.node_name,
                                getattr(endpoint, "node_namespace", "/"),
                            )
                            relationships.setdefault(
                                key,
                                {"publishers": set(), "subscribers": set()},
                            )["publishers"].add(topic_name)
                        for endpoint in self.node.get_subscriptions_info_by_topic(
                            topic_name
                        ):
                            key = (
                                endpoint.node_name,
                                getattr(endpoint, "node_namespace", "/"),
                            )
                            relationships.setdefault(
                                key,
                                {"publishers": set(), "subscribers": set()},
                            )["subscribers"].add(topic_name)
                    except Exception as topic_error:
                        logger.debug(
                            "Could not get info for topic %s: %s",
                            topic_name,
                            topic_error,
                        )

                nodes = [
                    NodeInfo(
                        name=name,
                        namespace=namespace,
                        publishers=sorted(values["publishers"]),
                        subscribers=sorted(values["subscribers"]),
                        services=[],
                        actions=[],
                        parameters={},
                    )
                    for (name, namespace), values in relationships.items()
                ]
                self._node_cache = (
                    now_monotonic,
                    [node.model_copy(deep=True) for node in nodes],
                )
                logger.info("Found %s nodes with topic relationships", len(nodes))
                return nodes
            except Exception as e:
                logger.error(f"Failed to get nodes: {e}")
                return []

    async def get_topic_types(self) -> Dict[str, str]:
        """获取主题类型映射"""
        try:
            topics = await self.get_topics(include_details=False)
            topic_types = {
                topic.name: topic.message_type or "unknown" for topic in topics
            }
            logger.info(f"Found {len(topic_types)} topic types")
            return topic_types
        except Exception as e:
            logger.error(f"Failed to get topic types: {e}")
            return {}

    async def get_topic_frequencies(
        self, sample_duration: Optional[float] = None
    ) -> Dict[str, Optional[float]]:
        """获取主题频率信息"""
        if not self.node:
            return {}

        if sample_duration is not None:
            return await self._freq.sample_frequencies(self.node, sample_duration)

        try:
            frequencies = {}
            topic_names_and_types = self.node.get_topic_names_and_types()
            now = time.time()

            for topic_name, _ in topic_names_and_types:
                try:
                    frequencies[topic_name] = self._freq.get_frequency(
                        topic_name, topic_name in self.subscribers, now
                    )

                except Exception as e:
                    logger.warning(
                        f"Could not get frequency for topic {topic_name}: {e}"
                    )
                    frequencies[topic_name] = None

            logger.info(f"Found frequencies for {len(frequencies)} topics")
            return frequencies
        except Exception as e:
            logger.error(f"Failed to get topic frequencies: {e}")
            return {}

    async def get_services(self) -> List[str]:
        """获取服务列表"""
        if not self.node:
            return []

        try:
            service_names_and_types = self.node.get_service_names_and_types()
            services = [name for name, _ in service_names_and_types]

            logger.info(f"Found {len(services)} services")
            return services
        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            return []

    async def get_service_types(self) -> Dict[str, str]:
        """获取服务类型映射"""
        if not self.node:
            return {}

        try:
            service_names_and_types = self.node.get_service_names_and_types()
            service_types = {}

            for name, types in service_names_and_types:
                service_types[name] = types[0] if types else "unknown"

            logger.info(f"Found {len(service_types)} service types")
            return service_types
        except Exception as e:
            logger.error(f"Failed to get service types: {e}")
            return {}

    async def get_params(self) -> List[str]:
        """获取参数列表"""
        if not self.node:
            return []

        try:
            # 获取参数名称列表 - 这是一个简化版本
            # 实际实现可能需要递归获取所有节点的参数
            param_names = []

            # 尝试获取当前节点的参数
            try:
                param_names = list(self.node.get_parameter_names())
            except Exception as param_e:
                logger.debug(f"Could not get parameters: {param_e}")

            logger.info(f"Found {len(param_names)} parameters")
            return param_names
        except Exception as e:
            logger.error(f"Failed to get params: {e}")
            return []

    async def get_node_info(self, node_name: str) -> Optional[NodeInfo]:
        """获取节点信息"""
        nodes = await self.get_nodes()
        for node in nodes:
            if node.name == node_name:
                return node
        return None

    async def acquire_publisher(
        self,
        topic: str,
        msg_type: str,
        owner_id: str,
    ):
        """创建或返回已存在的Publisher"""
        async with self._publisher_lock:
            self._ensure_publisher_locked(topic, msg_type, owner_id)

    def _ensure_publisher_locked(
        self,
        topic: str,
        msg_type: str,
        owner_id: str,
    ) -> None:
        if not self.node:
            raise RuntimeError("ROS2 node not initialized")

        msg_type = canonical_message_type(msg_type)

        if topic in self.publishers:
            record = self.publishers[topic]
            if record["msg_type"] != msg_type:
                raise ValueError(
                    f"{topic} 已按 {record['msg_type']} 创建，不能改用 {msg_type}"
                )
            record.setdefault("owners", set()).add(owner_id)
            return

        if len(self.publishers) >= self.settings.ros_max_publishers:
            raise RuntimeError("ROS Publisher 数量已达上限")

        msg_class = get_message_class(msg_type)
        if msg_class is None:
            raise RuntimeError(f"Unsupported message type: {msg_type}")

        # 针对一次性关键话题（/initialpose, /goal_pose）使用 TRANSIENT_LOCAL，便于后订阅者获取最后一次
        use_transient_local = topic in ("/initialpose", "/goal_pose") or (
            msg_type
            in (
                "geometry_msgs/msg/PoseStamped",
                "geometry_msgs/msg/PoseWithCovarianceStamped",
            )
            and topic in ("/initialpose", "/goal_pose")
        )

        qos_profile = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=(
                QoSDurabilityPolicy.TRANSIENT_LOCAL
                if use_transient_local
                else QoSDurabilityPolicy.VOLATILE
            ),
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1 if use_transient_local else 10,
        )

        publisher = self.node.create_publisher(msg_class, topic, qos_profile)
        self.publishers[topic] = {
            "publisher": publisher,
            "msg_class": msg_class,
            "msg_type": msg_type,
            "owners": {owner_id},
        }
        logger.info(f"🆕 Created publisher for {topic} ({msg_type})")

    async def release_publisher(self, topic: str, owner_id: str) -> None:
        async with self._publisher_lock:
            self._release_publisher_locked(topic, owner_id)

    def _release_publisher_locked(self, topic: str, owner_id: str) -> None:
        record = self.publishers.get(topic)
        if not record:
            return
        owners = record.setdefault("owners", set())
        owners.discard(owner_id)
        if owners:
            return
        self.publishers.pop(topic, None)
        if self.node:
            try:
                self.node.destroy_publisher(record["publisher"])
            except Exception as error:
                logger.warning("Failed to destroy publisher for %s: %s", topic, error)
        logger.info("Destroyed unused publisher for %s", topic)
