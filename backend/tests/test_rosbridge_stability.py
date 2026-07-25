import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from rclpy.qos import QoSHistoryPolicy

from app.models.ros import ConnectionInfo
from app.services.rosbridge import RosbridgeService


def test_client_ids_are_unique_under_connection_bursts(settings):
    service = RosbridgeService(settings)

    client_ids = {service._new_client_id() for _ in range(10_000)}

    assert len(client_ids) == 10_000
    assert all(client_id.startswith("client_") for client_id in client_ids)


@pytest.mark.asyncio
async def test_message_cache_does_not_retain_serialized_payloads(settings, monkeypatch):
    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    service = RosbridgeService(settings)
    service.connection_manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        subscribed_topics=["/large_points"],
        message_count=0,
    )
    large_payload = {"data": "x" * 1_000_000, "data_encoding": "base64"}
    service._subscription_types["/large_points"] = "sensor_msgs/msg/PointCloud2"
    service._converter.to_dict = Mock(return_value=large_payload)
    service.connection_manager.broadcast = AsyncMock(return_value=True)

    await service._on_message_received("/large_points", object())

    service.connection_manager.broadcast.assert_awaited_once()
    assert len(service.message_cache) == 1
    assert service.message_cache[0]["topic"] == "/large_points"
    assert "message" not in service.message_cache[0]
    assert (
        service.connection_manager.broadcast.await_args.kwargs["coalesce_topic"] is True
    )


def test_pointcloud_forward_rate_is_limited_before_conversion(settings):
    limited_settings = settings.model_copy(update={"ros_pointcloud_max_hz": 10.0})
    service = RosbridgeService(limited_settings)
    service._subscription_types["/points"] = "sensor_msgs/msg/PointCloud2"

    assert service._claim_topic_forward_slot("/points", now=1.0)
    assert service._claim_topic_forward_slot("/points", now=1.05)
    assert not service._claim_topic_forward_slot("/points", now=1.06)
    assert service._claim_topic_forward_slot("/points", now=1.11)


def test_high_bandwidth_sensor_qos_keeps_only_latest_sample(settings):
    service = RosbridgeService(settings)
    keep_all_publisher = Mock(history=QoSHistoryPolicy.KEEP_ALL)

    history, depth = service._subscriber_history_settings(
        "sensor_msgs/msg/PointCloud2",
        [keep_all_publisher],
    )
    assert history == QoSHistoryPolicy.KEEP_LAST
    assert depth == 1

    marker_history, marker_depth = service._subscriber_history_settings(
        "visualization_msgs/msg/MarkerArray",
        [keep_all_publisher],
    )
    assert marker_history == QoSHistoryPolicy.KEEP_ALL
    assert marker_depth == 1000
