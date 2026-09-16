from types import SimpleNamespace

import pytest

from app import main
from app.api.v1 import system


@pytest.mark.asyncio
async def test_management_metrics_do_not_require_ros(monkeypatch):
    monkeypatch.setenv("RVIZWEB_ROS_BACKEND", "v2")
    monkeypatch.delenv("ROS_VERSION", raising=False)
    def forbidden():
        pytest.fail("Host metrics must not initialize ROS")
    monkeypatch.setattr(main, "get_ros_service", forbidden)
    monkeypatch.setattr(system.psutil, "cpu_percent", lambda interval: 17.5)
    monkeypatch.setattr(system.psutil, "virtual_memory", lambda: SimpleNamespace(percent=42.1))
    monkeypatch.setattr(system.psutil, "sensors_temperatures",
                        lambda: {"coretemp": [SimpleNamespace(current=51.2)],
                                 "nvme": [SimpleNamespace(current=80)]})
    async with main.lifespan(main.app):
        response = system.get_system_status()
    assert response.model_dump() == {"cpu_usage": 17.5, "memory_usage": 42.1, "cpu_temperature": 51.2}


def test_unavailable_metrics_remain_null_without_hiding_available_metrics(monkeypatch):
    def unavailable(**_kwargs):
        raise OSError("Unavailable")
    monkeypatch.setattr(system.psutil, "cpu_percent", unavailable)
    monkeypatch.setattr(system.psutil, "virtual_memory", lambda: SimpleNamespace(percent=31))
    monkeypatch.setattr(system.psutil, "sensors_temperatures",
                        lambda: {"nvme": [SimpleNamespace(current=80)]})
    monkeypatch.setattr(system.Path, "glob", lambda *_: [])
    assert system.get_system_status().model_dump() == {
        "cpu_usage": None, "memory_usage": 31, "cpu_temperature": None}
