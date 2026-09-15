import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from rclpy.qos import QoSHistoryPolicy

from app.models.ros import ConnectionInfo
from app.services.ros2.adapter import Ros2Adapter
from app.services.ros_application import RosApplication
from app.services.ros_gateway import RosGateway
from app.services.connection_manager import ConnectionManager


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [False, True])
async def test_conversion_drops_frame_after_subscription_changes(
    settings, monkeypatch, replacement
):
    service = Ros2Adapter(settings)
    service.subscribers["/points"] = object()
    service._subscription_types["/points"] = "sensor_msgs/msg/PointCloud2"
    sink = AsyncMock()
    service.set_message_sink(sink)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def convert(_function, _message):
        entered.set()
        await release.wait()
        return {"data": b"old frame"}

    monkeypatch.setattr(asyncio, "to_thread", convert)
    task = asyncio.create_task(service._on_message_received("/points", object()))
    await entered.wait()
    service.subscribers.pop("/points")
    service._subscription_types.pop("/points")
    if replacement:
        service.subscribers["/points"] = object()
        service._subscription_types["/points"] = "sensor_msgs/msg/PointCloud2"
    release.set()
    await task
    sink.assert_not_awaited()
    assert not service.message_cache


@pytest.mark.asyncio
async def test_spin_does_not_wait_on_http_event_loop(settings, monkeypatch):
    from rclpy.executors import ExternalShutdownException

    service = Ros2Adapter(settings)
    service.node = Mock()
    spin = Mock(side_effect=ExternalShutdownException)
    monkeypatch.setattr("app.services.ros2.adapter.rclpy.spin_once", spin)
    await service._ros_spin_loop()
    spin.assert_called_once_with(service.node, timeout_sec=0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("context_alive", [False, True])
async def test_spin_errors_are_only_normal_after_context_shutdown(
    settings, monkeypatch, caplog, context_alive
):
    service = Ros2Adapter(settings)
    service.node = Mock()
    monkeypatch.setattr("app.services.ros2.adapter.rclpy.ok", lambda: context_alive)
    monkeypatch.setattr(
        "app.services.ros2.adapter.rclpy.spin_once",
        Mock(side_effect=RuntimeError("wait set failed")),
    )
    with caplog.at_level("INFO"):
        await service._ros_spin_loop()
    assert ("Fatal error" in caplog.text) is context_alive
    assert ("after context shutdown" in caplog.text) is not context_alive


def test_client_ids_are_unique_under_connection_bursts(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)

    client_ids = {gateway.new_client_id() for _ in range(10_000)}

    assert len(client_ids) == 10_000
    assert all(client_id.startswith("client_") for client_id in client_ids)


@pytest.mark.asyncio
async def test_message_cache_does_not_retain_serialized_payloads(settings, monkeypatch):
    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    application.connection_manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        subscribed_topics=["/large_points"],
        message_count=0,
    )
    service.subscribers["/large_points"] = object()
    large_payload = {"data": "x" * 1_000_000, "data_encoding": "base64"}
    service._subscription_types["/large_points"] = "sensor_msgs/msg/PointCloud2"
    service._converter.to_dict = Mock(return_value=large_payload)
    application.connection_manager.broadcast = AsyncMock(return_value=True)

    await service._on_message_received("/large_points", object())

    application.connection_manager.broadcast.assert_awaited_once()
    assert len(service.message_cache) == 1
    assert service.message_cache[0]["topic"] == "/large_points"
    assert "message" not in service.message_cache[0]
    assert (
        application.connection_manager.broadcast.await_args.kwargs["coalesce_topic"]
        is True
    )


def test_pointcloud_forward_rate_is_limited_before_conversion(settings):
    limited_settings = settings.model_copy(update={"ros_pointcloud_max_hz": 10.0})
    service = Ros2Adapter(limited_settings)
    service._subscription_types["/points"] = "sensor_msgs/msg/PointCloud2"

    assert service._claim_topic_forward_slot("/points", now=1.0)
    assert service._claim_topic_forward_slot("/points", now=1.05)
    assert not service._claim_topic_forward_slot("/points", now=1.06)
    assert service._claim_topic_forward_slot("/points", now=1.11)


def test_high_bandwidth_sensor_qos_keeps_only_latest_sample(settings):
    service = Ros2Adapter(settings)
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
