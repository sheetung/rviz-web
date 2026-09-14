"""
ROS2 话题频率追踪
追踪消息到达时间，计算发布频率，支持主动采样
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Awaitable, Callable, Dict, Optional

from rclpy.qos import (
    QoSProfile,
    QoSReliabilityPolicy,
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
)

from .message_types import get_message_class

logger = logging.getLogger(__name__)


class FrequencyTracker:
    """追踪和计算 ROS2 话题发布频率"""

    def __init__(
        self,
        message_class_resolver: Optional[Callable[[str], object]] = None,
        frequency_clock: Optional[Callable[[], float]] = None,
        wall_clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ):
        self._message_class_resolver = message_class_resolver or get_message_class
        self._monotonic_clock = frequency_clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._sleep = sleep or asyncio.sleep
        self._topic_message_times: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=200)
        )
        self._topic_last_message_times: Dict[str, float] = {}
        self._topic_observation_started_at: Dict[str, float] = {}
        self._sampled_topic_frequencies: Dict[str, Optional[float]] = {}
        self._frequency_sampled_at: Optional[float] = None
        self._sample_lock = asyncio.Lock()

    def record_message(self, topic: str, timestamp: float):
        """记录消息到达时间（从消息管道调用）"""
        self._topic_message_times[topic].append(timestamp)
        self._topic_last_message_times[topic] = timestamp

    def mark_observation_start(self, topic: str):
        """标记话题订阅开始时间"""
        self._topic_observation_started_at[topic] = self._wall_clock()

    def cleanup_topic(self, topic: str):
        """清理话题相关状态（取消订阅时调用）"""
        self._topic_message_times.pop(topic, None)
        self._topic_observation_started_at.pop(topic, None)
        self._sampled_topic_frequencies.pop(topic, None)

    def get_last_message_time(self, topic: str) -> Optional[float]:
        """获取话题最后一条消息的时间戳"""
        return self._topic_last_message_times.get(topic)

    def get_frequency(
        self, topic_name: str, is_subscribed: bool, now: Optional[float] = None
    ) -> Optional[float]:
        """计算话题当前频率"""
        current_time = self._wall_clock() if now is None else now
        timestamps = self._topic_message_times.get(topic_name)
        if timestamps:
            while timestamps and current_time - timestamps[0] > 5.0:
                timestamps.popleft()

        if timestamps and len(timestamps) >= 2:
            duration = timestamps[-1] - timestamps[0]
            if duration > 0:
                return (len(timestamps) - 1) / duration

        observation_started_at = self._topic_observation_started_at.get(topic_name)
        if (
            is_subscribed
            and observation_started_at is not None
            and current_time - observation_started_at >= 5.0
        ):
            return 0.0

        if (
            self._frequency_sampled_at is not None
            and current_time - self._frequency_sampled_at <= 5.0
        ):
            return self._sampled_topic_frequencies.get(topic_name)
        return None

    async def sample_frequencies(
        self, node, sample_duration: float
    ) -> Dict[str, Optional[float]]:
        """临时订阅所有已发布话题，测量回调频率"""
        if not node:
            return {}

        duration = max(0.5, min(float(sample_duration), 5.0))
        async with self._sample_lock:
            topics = node.get_topic_names_and_types()
            frequencies = {topic_name: None for topic_name, _ in topics}
            sample_times = defaultdict(lambda: deque(maxlen=1000))
            monitored_topics = set()
            monitor_subscriptions = []

            try:
                for topic_name, message_types in topics:
                    if not message_types:
                        continue

                    try:
                        publisher_info = node.get_publishers_info_by_topic(topic_name)
                    except Exception as e:
                        logger.debug(
                            f"Could not inspect publishers for {topic_name}: {e}"
                        )
                        continue

                    if not publisher_info:
                        frequencies[topic_name] = 0.0
                        continue

                    msg_class = self._message_class_resolver(message_types[0])
                    if msg_class is None:
                        logger.warning(
                            f"Cannot sample frequency for {topic_name}: unavailable type {message_types[0]}"
                        )
                        continue

                    def callback(_msg, measured_topic=topic_name):
                        sample_times[measured_topic].append(self._monotonic_clock())
                        self._topic_last_message_times[measured_topic] = (
                            self._wall_clock()
                        )

                    # BEST_EFFORT + VOLATILE can receive both common sensor QoS and
                    # reliable publishers. raw=True avoids deserializing large point clouds.
                    qos_profile = QoSProfile(
                        reliability=QoSReliabilityPolicy.BEST_EFFORT,
                        durability=QoSDurabilityPolicy.VOLATILE,
                        history=QoSHistoryPolicy.KEEP_LAST,
                        depth=1,
                    )

                    try:
                        subscription = node.create_subscription(
                            msg_class,
                            topic_name,
                            callback,
                            qos_profile,
                            raw=True,
                        )
                        monitor_subscriptions.append(subscription)
                        monitored_topics.add(topic_name)
                    except Exception as e:
                        logger.warning(
                            f"Could not monitor frequency for {topic_name}: {e}"
                        )

                await self._sleep(duration)
            finally:
                for subscription in monitor_subscriptions:
                    try:
                        node.destroy_subscription(subscription)
                    except Exception as e:
                        logger.debug(f"Could not destroy frequency monitor: {e}")

            for topic_name in monitored_topics:
                timestamps = sample_times[topic_name]
                frequencies[topic_name] = (
                    0.0 if not timestamps else self._from_samples(timestamps)
                )

            sampled_at = self._wall_clock()
            self._sampled_topic_frequencies = frequencies.copy()
            self._frequency_sampled_at = sampled_at
            logger.info(
                f"Sampled frequencies for {len(monitored_topics)} topics over {duration:.1f}s"
            )
            return frequencies

    @staticmethod
    def _from_samples(timestamps) -> Optional[float]:
        if len(timestamps) < 2:
            return None
        duration = timestamps[-1] - timestamps[0]
        if duration <= 0:
            return None
        return (len(timestamps) - 1) / duration
