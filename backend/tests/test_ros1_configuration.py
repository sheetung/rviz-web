import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.ros_runtime import selected_middleware
from app.services.ros1.message_converter import MessageConverter

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("version,expected", [("1", "ros1"), ("2", "ros2")])
def test_runtime_version(monkeypatch, version, expected):
    monkeypatch.setenv("ROS_VERSION", version)
    assert selected_middleware() == expected


@pytest.mark.parametrize("version", ["", "3", "ros1"])
def test_invalid_runtime(monkeypatch, version):
    monkeypatch.setenv("ROS_VERSION", version)
    with pytest.raises(RuntimeError):
        selected_middleware()


def test_setup_missing_and_mixed_versions(tmp_path):
    one = tmp_path / "one.bash"
    two = tmp_path / "two.bash"
    one.write_text("export ROS_VERSION=1 ROS_DISTRO=first\n")
    two.write_text("export ROS_VERSION=2 ROS_DISTRO=second\n")
    env = {
        k: v for k, v in os.environ.items() if k not in ("ROS_VERSION", "ROS_DISTRO")
    }
    for paths, success in [
        (str(one), True),
        (f"{one} {two}", False),
        (str(tmp_path / "absent"), False),
    ]:
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{ROOT}/scripts/ros-environment.sh"; load_ros_environment',
            ],
            env={**env, "ROS_SETUP_PATHS": paths},
            capture_output=True,
        )
        assert (result.returncode == 0) == success


@pytest.mark.asyncio
async def test_ws_version_mismatch_and_origin(monkeypatch):
    import app.main as main

    monkeypatch.setattr(
        main, "get_ros_service", lambda: SimpleNamespace(middleware="ros1")
    )
    ws = SimpleNamespace(
        headers={}, accept=AsyncMock(), send_json=AsyncMock(), close=AsyncMock()
    )
    await main.websocket_endpoint(ws, "ros2")
    assert ws.send_json.call_args.args[0]["code"] == "middleware_mismatch"
    ws.close.assert_awaited_with(code=1008, reason="middleware_mismatch")
    ws.headers = {"origin": "https://untrusted.invalid"}
    ws.accept.reset_mock()
    await main.websocket_endpoint(ws, "ros1")
    ws.accept.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_version_mismatch(monkeypatch):
    import app.main as main

    monkeypatch.setattr(
        main, "get_ros_service", lambda: SimpleNamespace(middleware="ros1")
    )
    await main.require_middleware(
        SimpleNamespace(url=SimpleNamespace(path="/ros1/api/v1/ros/topics"))
    )
    with pytest.raises(main.HTTPException) as error:
        await main.require_middleware(
            SimpleNamespace(url=SimpleNamespace(path="/ros2/api/v1/version"))
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "kind,value",
    [
        ("bool", 1),
        ("uint8", 256),
        ("int8", -129),
        ("float32", float("nan")),
        ("string", 1),
    ],
)
def test_ros1_invalid_scalar(kind, value):
    with pytest.raises(ValueError):
        MessageConverter(Settings(_env_file=None))._value(kind, value)


def test_ros1_preserves_integer_and_boolean():
    conv = MessageConverter(Settings(_env_file=None))
    assert conv._value("uint64", 2**64 - 1) == 2**64 - 1
    assert conv.to_dict([True, 2**63]) == [True, 2**63]


def test_ros1_time_normalization():
    conv = MessageConverter(Settings(_env_file=None))
    stamp = SimpleNamespace(secs=1, nsecs=7)
    assert conv.to_dict(stamp) == {"sec": 1, "nanosec": 7}
    conv._assign(stamp, {"sec": 3, "nanosec": 9})
    assert (stamp.secs, stamp.nsecs) == (3, 9)
    with pytest.raises(ValueError):
        conv._assign(stamp, {"sec": 1, "nanosec": 10**9})


def test_ros1_padded_bigendian_pointcloud():
    import struct

    fields = [SimpleField(n, i * 4) for i, n in enumerate(("x", "y", "z"))]
    msg = SimpleNamespace(
        width=1,
        height=2,
        point_step=16,
        row_step=20,
        data=struct.pack(">fff", 1, 2, 3)
        + b"x" * 8
        + struct.pack(">fff", 4, 5, 6)
        + b"x" * 8,
        fields=fields,
        header={"frame_id": "map"},
        is_bigendian=True,
        is_dense=True,
    )
    result = MessageConverter(Settings(_env_file=None)).pointcloud(msg)
    assert result["data"] == struct.pack(">ffffff", 1, 2, 3, 4, 5, 6)
    assert (
        result["is_bigendian"]
        and result["point_step"] == 12
        and result["row_step"] == 12
    )
    msg.data = b""
    with pytest.raises(ValueError):
        MessageConverter(Settings(_env_file=None)).pointcloud(msg)


class SimpleField:
    __slots__ = ("name", "offset", "datatype", "count")

    def __init__(self, name, offset):
        self.name, self.offset, self.datatype, self.count = name, offset, 7, 1
