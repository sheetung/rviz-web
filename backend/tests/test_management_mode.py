import sys
from unittest.mock import AsyncMock

import pytest

from app import main
from app.services.dependencies import get_ros_service
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_management_mode_never_initializes_ros(monkeypatch):
    monkeypatch.setenv("RVIZWEB_ROS_BACKEND", "v2")
    monkeypatch.delenv("ROS_VERSION", raising=False)

    def forbidden():
        pytest.fail("Management mode must not construct a ROS service")

    monkeypatch.setattr(main, "get_ros_service", forbidden)
    monkeypatch.setattr(main, "get_ros_gateway", forbidden)
    shutdown = AsyncMock()
    monkeypatch.setattr(main.video, "shutdown_video_streams", shutdown)
    before = {name for name in sys.modules if name.startswith(("rclpy", "rospy"))}
    async with main.lifespan(main.app):
        health = await main.health_check()
        assert health["ros_backend"] == "v2"
        version = await main.version_info()
        assert version["middleware"] == "external"
        with pytest.raises(HTTPException) as error:
            get_ros_service()
        assert error.value.status_code == 503
    assert {name for name in sys.modules if name.startswith(("rclpy", "rospy"))} == before
    shutdown.assert_awaited_once()
