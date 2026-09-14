import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.ros import ConnectionInfo, SystemStatus
from app.services.ros2.adapter import Ros2Adapter
from app.services.ros_application import RosApplication
from app.services.ros_gateway import RosGateway
from app.services.connection_manager import ConnectionManager


@pytest.mark.asyncio
async def test_ping_returns_matching_pong(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)
    application.connection_manager.send_to_client = AsyncMock()

    await gateway.handle_message("client-1", {"op": "ping", "id": "ping-42"})

    application.connection_manager.send_to_client.assert_awaited_once_with(
        "client-1",
        {"op": "pong", "id": "ping-42"},
    )


@pytest.mark.asyncio
async def test_system_status_returns_over_websocket(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)
    application.connection_manager.send_to_client = AsyncMock()
    application.get_system_status = AsyncMock(
        return_value=SystemStatus(
            ros_domain_id=0,
            active_nodes=3,
            active_topics=12,
            active_connections=1,
            system_time=datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc),
            uptime=120.0,
            memory_usage=42.5,
            cpu_usage=17.25,
            cpu_temperature=51.0,
        )
    )

    await gateway.handle_message(
        "client-1",
        {"op": "get_system_status", "id": "status-7"},
    )

    application.connection_manager.send_to_client.assert_awaited_once_with(
        "client-1",
        {
            "op": "get_system_status_result",
            "status": {
                "ros_domain_id": 0,
                "active_nodes": 3,
                "active_topics": 12,
                "active_connections": 1,
                "system_time": "2026-07-14T09:00:00Z",
                "uptime": 120.0,
                "memory_usage": 42.5,
                "cpu_usage": 17.25,
                "cpu_temperature": 51.0,
            },
            "id": "status-7",
        },
    )


@pytest.mark.asyncio
async def test_publish_success_is_acknowledged_after_ros_publish(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)
    service.node = Mock()
    publisher = Mock()

    class FakeMessage:
        pass

    service.publishers["/goal_pose"] = {
        "publisher": publisher,
        "msg_class": FakeMessage,
        "msg_type": "geometry_msgs/msg/PoseStamped",
        "owners": set(),
    }
    application.connection_manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
    )
    application.connection_manager.send_to_client = AsyncMock()
    ros_message = object()
    service._converter.from_dict = Mock(return_value=ros_message)

    await gateway.handle_message(
        "client-1",
        {
            "op": "publish",
            "id": "publish-1",
            "topic": "/goal_pose",
            "type": "geometry_msgs/PoseStamped",
            "msg": {"pose": {}},
        },
    )

    publisher.publish.assert_called_once_with(ros_message)
    assert (
        application.connection_manager.connection_info["client-1"].advertised_topics[
            "/goal_pose"
        ]
        == "geometry_msgs/msg/PoseStamped"
    )
    application.connection_manager.send_to_client.assert_awaited_once_with(
        "client-1",
        {
            "op": "publish_result",
            "success": True,
            "topic": "/goal_pose",
            "id": "publish-1",
        },
    )


@pytest.mark.asyncio
async def test_publish_conversion_failure_returns_matching_error(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    gateway = RosGateway(settings, application, application.connection_manager)
    service.node = Mock()

    class FakeMessage:
        pass

    service.publishers["/goal_pose"] = {
        "publisher": Mock(),
        "msg_class": FakeMessage,
        "msg_type": "geometry_msgs/msg/PoseStamped",
        "owners": set(),
    }
    application.connection_manager.send_to_client = AsyncMock()
    service._converter.from_dict = Mock(return_value=None)
    application.connection_manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
    )

    await gateway.handle_message(
        "client-1",
        {
            "op": "publish",
            "id": "publish-failed",
            "topic": "/goal_pose",
            "type": "geometry_msgs/msg/PoseStamped",
            "msg": {"pose": {}},
        },
    )

    response = application.connection_manager.send_to_client.await_args.args[1]
    assert response["op"] == "error"
    assert response["id"] == "publish-failed"
    assert (
        "/goal_pose"
        in application.connection_manager.connection_info["client-1"].advertised_topics
    )


@pytest.mark.asyncio
async def test_concurrent_publisher_owners_share_one_ros_publisher(settings):
    service = Ros2Adapter(settings)
    service.node = Mock()
    publisher = Mock()
    service.node.create_publisher.return_value = publisher

    await asyncio.gather(
        service.acquire_publisher(
            "/goal_pose",
            "geometry_msgs/msg/PoseStamped",
            "client-1",
        ),
        service.acquire_publisher(
            "/goal_pose",
            "geometry_msgs/msg/PoseStamped",
            "client-2",
        ),
    )

    service.node.create_publisher.assert_called_once()
    assert service.publishers["/goal_pose"]["owners"] == {"client-1", "client-2"}


@pytest.mark.asyncio
async def test_rest_publish_releases_temporary_publisher(settings):
    service = Ros2Adapter(settings)
    service.node = Mock()
    publisher = Mock()
    service.node.create_publisher.return_value = publisher
    service._converter.from_dict = Mock(return_value=object())

    success = await service.publish_message(
        "/goal_pose",
        {"pose": {}},
        "geometry_msgs/msg/PoseStamped",
    )

    assert success
    publisher.publish.assert_called_once()
    assert "/goal_pose" not in service.publishers
    service.node.destroy_publisher.assert_called_once_with(publisher)


@pytest.mark.asyncio
async def test_concurrent_rest_publishes_keep_shared_publisher_alive(settings):
    service = Ros2Adapter(settings)
    service.node = Mock()
    publisher = Mock()
    service.node.create_publisher.return_value = publisher
    service._converter.from_dict = Mock(side_effect=lambda _type, message: message)

    original_ensure = service.acquire_publisher
    both_owners_registered = asyncio.Event()
    registered_count = 0

    async def ensure_then_wait(topic, msg_type, owner_id):
        nonlocal registered_count
        await original_ensure(topic, msg_type, owner_id)
        registered_count += 1
        if registered_count == 2:
            both_owners_registered.set()
        await both_owners_registered.wait()

    service.acquire_publisher = ensure_then_wait

    results = await asyncio.gather(
        service.publish_message(
            "/goal_pose",
            {"request": 1},
            "geometry_msgs/msg/PoseStamped",
        ),
        service.publish_message(
            "/goal_pose",
            {"request": 2},
            "geometry_msgs/msg/PoseStamped",
        ),
    )

    assert results == [True, True]
    service.node.create_publisher.assert_called_once()
    assert publisher.publish.call_count == 2
    assert "/goal_pose" not in service.publishers
    service.node.destroy_publisher.assert_called_once_with(publisher)


@pytest.mark.asyncio
async def test_client_publisher_is_destroyed_on_disconnect(settings):
    service = Ros2Adapter(settings)
    application = RosApplication(settings, service, ConnectionManager())
    publisher = object()
    service.node = Mock()
    service.publishers["/goal_pose"] = {
        "publisher": publisher,
        "msg_class": object,
        "msg_type": "geometry_msgs/msg/PoseStamped",
        "owners": {"client-1"},
    }
    application.connection_manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        advertised_topics={
            "/goal_pose": "geometry_msgs/msg/PoseStamped",
        },
    )

    await application.cleanup_client("client-1")

    assert "/goal_pose" not in service.publishers
    service.node.destroy_publisher.assert_called_once_with(publisher)
