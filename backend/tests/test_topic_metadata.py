from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.ros import TopicInfo
from app.services.ros2.adapter import Ros2Adapter
from app.services.ros_application import RosApplication
from app.services.ros_gateway import RosGateway
from app.services.connection_manager import ConnectionManager


class FakeGraphNode:
    def get_topic_names_and_types(self):
        return [
            ("/idle", ["std_msgs/msg/String"]),
            ("/points", ["sensor_msgs/msg/PointCloud2"]),
            ("/unknown", ["std_msgs/msg/String"]),
        ]

    def get_publishers_info_by_topic(self, topic_name):
        if topic_name != "/points":
            return []
        return [SimpleNamespace(node_name="driver", node_namespace="/camera")]

    def get_subscriptions_info_by_topic(self, topic_name):
        if topic_name != "/points":
            return []
        return [SimpleNamespace(node_name="viewer", node_namespace="/")]


class FakeSamplingNode(FakeGraphNode):
    def __init__(self):
        self.callbacks = {}
        self.destroyed_subscriptions = []

    def create_subscription(self, _msg_class, topic_name, callback, _qos, raw=False):
        assert raw is True
        subscription = object()
        self.callbacks[topic_name] = callback
        return subscription

    def destroy_subscription(self, subscription):
        self.destroyed_subscriptions.append(subscription)


@pytest.mark.asyncio
async def test_topics_include_graph_and_observed_message_metadata(
    settings, monkeypatch
):
    service = Ros2Adapter(settings)
    service.node = FakeGraphNode()
    monkeypatch.setattr(
        service,
        "_get_topics_from_cli",
        AsyncMock(
            return_value=[
                TopicInfo(
                    name="/points",
                    message_type="sensor_msgs/msg/PointCloud2",
                )
            ]
        ),
    )
    monkeypatch.setattr("app.services.ros2.adapter.time.time", lambda: 1000.0)
    service.subscribers["/points"] = object()
    service._topic_observation_started_at["/points"] = 990.0
    service._topic_message_times["/points"] = deque([999.8, 999.9, 1000.0])
    service._topic_last_message_times["/points"] = 1000.0

    topics = await service.get_topics()

    assert len(topics) == 1
    assert topics[0].publishers == ["/camera/driver"]
    assert topics[0].subscribers == ["/viewer"]
    assert topics[0].frequency == pytest.approx(10.0)
    assert topics[0].last_message_time.tzinfo == timezone.utc
    assert topics[0].last_message_time.timestamp() == 1000.0


@pytest.mark.asyncio
async def test_frequencies_distinguish_measured_zero_from_unobserved(
    settings, monkeypatch
):
    service = Ros2Adapter(settings)
    service.node = FakeGraphNode()
    monkeypatch.setattr("app.services.ros2.adapter.time.time", lambda: 1000.0)
    service.subscribers["/idle"] = object()
    service._topic_observation_started_at["/idle"] = 990.0
    service.subscribers["/points"] = object()
    service._topic_observation_started_at["/points"] = 990.0
    service._topic_message_times["/points"] = deque([999.8, 999.9, 1000.0])

    frequencies = await service.get_topic_frequencies()

    assert frequencies["/points"] == pytest.approx(10.0)
    assert frequencies["/idle"] == 0.0
    assert frequencies["/unknown"] is None


@pytest.mark.asyncio
async def test_frequency_endpoint_actively_samples_published_topics(
    settings, monkeypatch
):
    service = Ros2Adapter(settings)
    service.node = FakeSamplingNode()
    monotonic_times = iter([100.0, 100.1, 100.2])

    monkeypatch.setattr(service, "_get_message_class", lambda _message_type: object)
    monkeypatch.setattr(service, "_frequency_clock", lambda: next(monotonic_times))
    monkeypatch.setattr("app.services.ros2.adapter.time.time", lambda: 1000.0)

    async def emit_samples(_duration):
        callback = service.node.callbacks["/points"]
        callback(b"first")
        callback(b"second")
        callback(b"third")

    monkeypatch.setattr("app.services.ros2.adapter.asyncio.sleep", emit_samples)

    frequencies = await service.get_topic_frequencies(sample_duration=1.0)

    assert frequencies["/points"] == pytest.approx(10.0)
    assert frequencies["/idle"] == 0.0
    assert frequencies["/unknown"] == 0.0
    assert service._topic_frequency("/points", now=1000.0) == pytest.approx(10.0)
    assert service._topic_last_message_times["/points"] == 1000.0
    assert len(service.node.destroyed_subscriptions) == 1


@pytest.mark.asyncio
async def test_websocket_topics_encode_last_message_time(settings, monkeypatch):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)
    topic = TopicInfo(
        name="/points",
        message_type="sensor_msgs/msg/PointCloud2",
        last_message_time=datetime(2026, 7, 13, 6, 15, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(service, "get_topics", AsyncMock(return_value=[topic]))
    application.connection_manager.send_to_client = AsyncMock()

    await gateway.handle_message("client-1", {"op": "get_topics", "id": "request-1"})

    response = application.connection_manager.send_to_client.await_args.args[1]
    encoded_time = response["topics"][0]["last_message_time"].replace("Z", "+00:00")
    assert datetime.fromisoformat(encoded_time) == datetime(
        2026, 7, 13, 6, 15, tzinfo=timezone.utc
    )
