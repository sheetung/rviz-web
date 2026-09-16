import sys
from unittest.mock import AsyncMock
import pytest
from app import main

@pytest.mark.asyncio
async def test_management_is_always_independent_of_ros(monkeypatch):
    monkeypatch.delenv("ROS_VERSION", raising=False)
    monkeypatch.delenv("RVIZWEB_ROS_BACKEND", raising=False)
    shutdown = AsyncMock()
    monkeypatch.setattr(main.video, "shutdown_video_streams", shutdown)
    before = {name for name in sys.modules if name.startswith(("rclpy", "rospy"))}
    async with main.lifespan(main.app):
        assert (await main.health_check())["ros_backend"] == "native"
        assert (await main.version_info())["service"] == "rvizweb-management"
    assert {name for name in sys.modules if name.startswith(("rclpy", "rospy"))} == before
    shutdown.assert_awaited_once()


def test_legacy_ros_routes_are_absent():
    paths = set(main.app.openapi()["paths"]) | {route.path for route in main.app.routes if hasattr(route, "path")}
    assert not any(path.startswith(("/ws", "/ros1/", "/ros2/", "/api/v1/ros")) for path in paths)
    assert {"/api/v1/system/status", "/health", "/api/v1/version"} <= paths
