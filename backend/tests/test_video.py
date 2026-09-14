import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import video


def _settings(**overrides):
    values = {
        "rtsp_transport": "tcp",
        "rtsp_frame_rate": 12,
        "rtsp_width": 640,
        "rtsp_jpeg_quality": 5,
        "rtsp_startup_timeout": 10.0,
        "rtsp_session_ttl": 300,
        "rtsp_max_sessions": 4,
        "rtsp_max_streams": 4,
        "rtsp_max_streams_per_session": 1,
        "rtsp_allow_private_networks": True,
        "rtsp_allowed_hosts": "",
        "ffmpeg_path": "ffmpeg",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def clear_video_state():
    video._video_sessions.clear()
    video._active_stream_processes.clear()
    video._pending_probes = 0
    yield
    video._video_sessions.clear()
    video._active_stream_processes.clear()
    video._pending_probes = 0


def test_ffmpeg_command_uses_configured_rtsp_source(monkeypatch):
    monkeypatch.setattr(video.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    command = video._build_ffmpeg_command(
        _settings(),
        "rtsp://192.168.1.66:8554/1",
    )

    assert command[0] == "/usr/bin/ffmpeg"
    assert command[command.index("-i") + 1] == "rtsp://192.168.1.66:8554/1"
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert "fps=12,scale=640:-2:force_original_aspect_ratio=decrease" in command
    assert command[-2:] == ["image2pipe", "pipe:1"]
    assert "-rw_timeout" not in command

    probe_command = video._build_ffmpeg_command(
        _settings(),
        "rtsp://192.168.1.66:8554/1",
        frame_limit=1,
    )
    assert probe_command[probe_command.index("-frames:v") + 1] == "1"
    assert "-rw_timeout" not in probe_command


def test_jpeg_frames_are_extracted_without_losing_remainder():
    first = b"\xff\xd8first\xff\xd9"
    second = b"\xff\xd8second\xff\xd9"
    buffer = bytearray(b"noise" + first + second)

    assert video._pop_jpeg_frame(buffer) == first
    assert video._pop_jpeg_frame(buffer) == second
    assert video._pop_jpeg_frame(buffer) is None


def test_non_rtsp_source_is_rejected():
    with pytest.raises(ValueError):
        video._validated_rtsp_url("http://192.168.1.66/video")


@pytest.mark.asyncio
async def test_private_rtsp_destination_is_blocked_by_default():
    with pytest.raises(ValueError, match="私网地址未被系统策略允许"):
        await video._validated_rtsp_destination(
            _settings(rtsp_allow_private_networks=False),
            "rtsp://192.168.1.66/live",
        )


@pytest.mark.asyncio
async def test_loopback_rtsp_destination_is_blocked_even_when_private_is_enabled():
    with pytest.raises(ValueError, match="不允许访问"):
        await video._validated_rtsp_destination(
            _settings(rtsp_allow_private_networks=True),
            "rtsp://127.0.0.1/live",
        )


@pytest.mark.asyncio
async def test_rtsp_domain_is_pinned_to_the_validated_address(monkeypatch):
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (
                    None,
                    None,
                    None,
                    None,
                    ("8.8.8.8", 554),
                )
            ]
        ),
    )

    destination = await video._validated_rtsp_destination(
        _settings(rtsp_allow_private_networks=False),
        "rtsp://user:secret@camera.example:8554/live?profile=1",
    )

    assert destination == "rtsp://user:secret@8.8.8.8:8554/live?profile=1"


@pytest.mark.asyncio
async def test_video_status_does_not_expose_rtsp_url(monkeypatch):
    monkeypatch.setattr(video, "get_settings", lambda: _settings())
    monkeypatch.setattr(video.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    status = await video.get_video_status()

    assert status.ready is True
    assert "192.168.1.66" not in status.model_dump_json()


@pytest.mark.asyncio
async def test_video_session_uses_an_opaque_stream_path(monkeypatch):
    monkeypatch.setattr(video, "get_settings", lambda: _settings())
    monkeypatch.setattr(video.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    async def successful_probe(_settings, _source_url):
        return None

    monkeypatch.setattr(video, "_probe_rtsp_source", successful_probe)

    session = await video.create_video_session(
        video.VideoSessionRequest(source_url="rtsp://192.168.1.66:8554/1")
    )

    assert "192.168.1.66" not in session.stream_path
    assert session.session_id in session.stream_path


@pytest.mark.asyncio
async def test_video_session_is_not_created_when_probe_fails(monkeypatch):
    monkeypatch.setattr(video, "get_settings", lambda: _settings())
    monkeypatch.setattr(video.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    async def failed_probe(_settings, _source_url):
        raise RuntimeError("no video stream")

    monkeypatch.setattr(video, "_probe_rtsp_source", failed_probe)

    with pytest.raises(video.HTTPException) as error:
        await video.create_video_session(
            video.VideoSessionRequest(source_url="rtsp://192.168.1.66:8554/1")
        )

    assert error.value.status_code == 504
    assert "未检测到可用视频流" in error.value.detail


@pytest.mark.asyncio
async def test_video_session_limit_is_enforced(monkeypatch):
    settings = _settings(rtsp_max_sessions=1)
    monkeypatch.setattr(video, "get_settings", lambda: settings)
    monkeypatch.setattr(video.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video, "_probe_rtsp_source", AsyncMock(return_value=None))

    await video.create_video_session(
        video.VideoSessionRequest(source_url="rtsp://192.168.1.66/live")
    )
    with pytest.raises(video.HTTPException) as error:
        await video.create_video_session(
            video.VideoSessionRequest(source_url="rtsp://192.168.1.67/live")
        )

    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_deleting_session_stops_its_active_streams(monkeypatch):
    session_id = "active-session"
    process = object()
    stop_process = AsyncMock()
    monkeypatch.setattr(video, "_stop_process", stop_process)
    video._video_sessions[session_id] = ("rtsp://127.0.0.1/live", 999999.0)
    video._active_stream_processes[session_id] = {process}

    await video.delete_video_session(session_id)

    assert session_id not in video._video_sessions
    assert session_id not in video._active_stream_processes
    stop_process.assert_awaited_once_with(process)


def test_touching_session_renews_its_expiration(monkeypatch):
    session_id = "playing-session"
    video._video_sessions[session_id] = ("rtsp://127.0.0.1/live", 10.0)
    monkeypatch.setattr(video.time, "monotonic", lambda: 100.0)

    video._touch_video_session(session_id, 300)

    assert video._video_sessions[session_id] == (
        "rtsp://127.0.0.1/live",
        400.0,
    )
    video._video_sessions.pop(session_id)
