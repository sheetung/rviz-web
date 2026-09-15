"""公共层用假适配器验证，禁止依赖 ROS 安装和私有实现。"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.ros import ConnectionInfo
from app.services.connection_manager import ConnectionManager
from app.services.ros_application import RosApplication
from app.services.ros_gateway import RosGateway


def make_application(settings):
    adapter = SimpleNamespace(
        middleware="fake",
        set_message_sink=Mock(),
        subscribe_topic=AsyncMock(return_value=True),
        unsubscribe_topic=AsyncMock(return_value=True),
        acquire_publisher=AsyncMock(),
        release_publisher=AsyncMock(),
        publish_prepared=Mock(return_value="geometry_msgs/msg/Pose"),
    )
    connections = ConnectionManager()
    for client in ("a", "b"):
        connections.connection_info[client] = ConnectionInfo(
            client_id=client, connected_at=datetime.now()
        )
    return RosApplication(settings, adapter, connections), adapter


@pytest.mark.asyncio
async def test_shared_subscription_survives_first_disconnect(settings):
    app, adapter = make_application(settings)
    await asyncio.gather(
        app.subscribe_client("a", "/points", "sensor_msgs/msg/PointCloud2"),
        app.subscribe_client("b", "/points", "sensor_msgs/msg/PointCloud2"),
    )
    await app.cleanup_client("a")
    adapter.unsubscribe_topic.assert_not_awaited()
    await app.cleanup_client("b")
    adapter.unsubscribe_topic.assert_awaited_once_with("/points")


@pytest.mark.asyncio
async def test_publisher_cleanup_and_type_inference_are_session_scoped(settings):
    app, adapter = make_application(settings)
    await app.advertise_client("a", "/goal_pose", "geometry_msgs/Pose")
    with pytest.raises(ValueError):
        await app.publish_client("b", "/goal_pose", {}, None)
    await app.publish_client("a", "/goal_pose", {}, None)
    adapter.publish_prepared.assert_called_once_with("/goal_pose", {})
    await app.cleanup_client("a")
    adapter.release_publisher.assert_awaited_once_with("/goal_pose", "a")


@pytest.mark.asyncio
async def test_failed_subscription_does_not_register_owner(settings):
    app, adapter = make_application(settings)
    adapter.subscribe_topic.return_value = False
    assert not await app.subscribe_client("a", "/points", None)
    assert app.connection_manager.connection_info["a"].subscribed_topics == []


@pytest.mark.asyncio
async def test_gateway_shutdown_releases_ros_before_removing_metadata(settings):
    app, adapter = make_application(settings)
    await app.subscribe_client("a", "/points", None)
    await app.advertise_client("a", "/goal_pose", "geometry_msgs/Pose")
    gateway = RosGateway(settings, app, app.connection_manager)
    await gateway.stop()
    adapter.unsubscribe_topic.assert_awaited_once_with("/points")
    adapter.release_publisher.assert_awaited_once_with("/goal_pose", "a")
    assert not app.connection_manager.connection_info


@pytest.mark.asyncio
async def test_gateway_invalid_json_then_ping_and_disconnect(settings):
    app, adapter = make_application(settings)
    gateway = RosGateway(settings, app, app.connection_manager)
    gateway.new_client_id = lambda: "a"
    from fastapi import WebSocketDisconnect

    socket = SimpleNamespace(
        accept=AsyncMock(),
        close=AsyncMock(),
        send_text=AsyncMock(),
        receive_text=AsyncMock(
            side_effect=["{", '{"op":"ping","id":"p"}', WebSocketDisconnect()]
        ),
    )
    app.connection_manager.send_to_client = AsyncMock()
    await gateway.handle_websocket(socket)
    replies = app.connection_manager.send_to_client.await_args_list
    assert replies[0].args[1]["op"] == "connection_info"
    assert replies[0].args[1]["protocol_version"] == 1
    assert replies[1].args[1]["op"] == "error"
    assert replies[2].args[1] == {"op": "pong", "id": "p"}
    assert "a" not in app.connection_manager.connection_info


def test_public_application_imports_without_ros():
    code = """
import importlib.abc
import sys
class RejectRos(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'rclpy', 'rospy', 'geometry_msgs', 'sensor_msgs'}:
            raise AssertionError('Public layer imported ' + fullname)
sys.meta_path.insert(0, RejectRos())
from app.main import app
app.openapi()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "DEBUG": "false"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
