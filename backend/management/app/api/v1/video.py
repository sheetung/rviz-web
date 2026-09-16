"""RTSP 相机视频转流 API。"""

import asyncio
import contextlib
import ipaddress
import logging
import re
import secrets
import shutil
import socket
import time
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.config import Settings, get_settings

router = APIRouter()
logger = logging.getLogger(__name__)

JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"
MAX_JPEG_BUFFER_BYTES = 20 * 1024 * 1024
MJPEG_BOUNDARY = "frame"
RTSP_URL_IN_TEXT = re.compile(r"rtsps?://[^\s\"']+", re.IGNORECASE)


class VideoStatus(BaseModel):
    ready: bool
    transport: str
    frame_rate: int
    width: int
    detail: str


class VideoSessionRequest(BaseModel):
    source_url: str = Field(min_length=8, max_length=2048)


class VideoSessionResponse(BaseModel):
    session_id: str
    stream_path: str


_video_sessions: dict[str, tuple[str, float]] = {}
_active_stream_processes: dict[str, set[asyncio.subprocess.Process]] = {}
_video_state_lock = asyncio.Lock()
_pending_probes = 0


def _validated_rtsp_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("RTSP 端口无效") from error
    if (
        parsed.scheme not in {"rtsp", "rtsps"}
        or not parsed.hostname
        or any(character.isspace() for character in url)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("网络流地址必须是有效的 rtsp:// 或 rtsps:// 地址")
    return url


def _pin_rtsp_hostname(
    url: str,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str:
    """让 FFmpeg 使用已通过策略校验的地址，避免二次 DNS 解析被重绑定。"""
    parsed = urlsplit(url)
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = f"{parsed.netloc.rsplit('@', 1)[0]}@"
    host = f"[{address}]" if address.version == 6 else str(address)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (
            parsed.scheme,
            f"{userinfo}{host}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _redact_rtsp_details(detail: str, source_url: str) -> str:
    redacted = detail.replace(source_url, "<RTSP source>")
    return RTSP_URL_IN_TEXT.sub("<RTSP source>", redacted)


async def _validated_rtsp_destination(settings: Settings, value: str) -> str:
    """解析最终目标地址，避免 FFmpeg 被用作内网探测器。"""
    url = _validated_rtsp_url(value)
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    allowed_hosts = {
        item.strip().rstrip(".").lower()
        for item in settings.rtsp_allowed_hosts.split(",")
        if item.strip()
    }
    explicitly_allowed = hostname in allowed_hosts

    try:
        resolved = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            port = parsed.port or 554
            addresses = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    hostname,
                    port,
                    type=socket.SOCK_STREAM,
                ),
                timeout=3.0,
            )
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            raise ValueError(f"无法解析 RTSP 主机: {hostname}") from exc
        resolved = {
            ipaddress.ip_address(sockaddr[0]) for _, _, _, _, sockaddr in addresses
        }
    if not resolved:
        raise ValueError(f"RTSP 主机没有可用地址: {hostname}")

    for address in resolved:
        if explicitly_allowed:
            continue
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise ValueError(f"RTSP 目标地址不允许访问: {address}")
        if address.is_private and not settings.rtsp_allow_private_networks:
            raise ValueError("RTSP 私网地址未被系统策略允许")
        if not address.is_private and not address.is_global:
            raise ValueError(f"RTSP 目标地址不允许访问: {address}")
    # 即使域名第一次解析到了公网地址，也不能让 FFmpeg 再次解析并被
    # DNS rebinding 引导到内网。数字地址会被规范化为等价 URL。
    selected_address = sorted(resolved, key=lambda item: (item.version, str(item)))[0]
    return _pin_rtsp_hostname(url, selected_address)


def _ffmpeg_executable(settings: Settings) -> Optional[str]:
    return shutil.which(settings.ffmpeg_path.strip() or "ffmpeg")


def _build_ffmpeg_command(
    settings: Settings,
    source_url: str,
    frame_limit: Optional[int] = None,
) -> list[str]:
    rtsp_url = _validated_rtsp_url(source_url)
    executable = _ffmpeg_executable(settings)
    if not executable:
        raise FileNotFoundError(settings.ffmpeg_path)

    video_filter = (
        f"fps={settings.rtsp_frame_rate},"
        f"scale={settings.rtsp_width}:-2:force_original_aspect_ratio=decrease"
    )
    command = [
        executable,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-rtsp_transport",
        settings.rtsp_transport,
        "-i",
        rtsp_url,
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        video_filter,
        "-c:v",
        "mjpeg",
        "-q:v",
        str(settings.rtsp_jpeg_quality),
    ]
    if frame_limit is not None:
        command.extend(["-frames:v", str(frame_limit)])
    command.extend(["-f", "image2pipe", "pipe:1"])
    return command


def _pop_jpeg_frame(buffer: bytearray) -> Optional[bytes]:
    start = buffer.find(JPEG_START)
    if start < 0:
        if len(buffer) > 1:
            del buffer[:-1]
        return None
    if start > 0:
        del buffer[:start]

    end = buffer.find(JPEG_END, len(JPEG_START))
    if end < 0:
        if len(buffer) > MAX_JPEG_BUFFER_BYTES:
            raise RuntimeError("FFmpeg 输出的 JPEG 帧超过大小限制")
        return None

    frame_end = end + len(JPEG_END)
    frame = bytes(buffer[:frame_end])
    del buffer[:frame_end]
    return frame


async def _read_jpeg_frame(
    stream: asyncio.StreamReader,
    buffer: bytearray,
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while True:
        frame = _pop_jpeg_frame(buffer)
        if frame is not None:
            return frame

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError
        chunk = await asyncio.wait_for(
            stream.read(64 * 1024),
            timeout=remaining,
        )
        if not chunk:
            raise RuntimeError("FFmpeg 未输出视频帧")
        buffer.extend(chunk)


async def _collect_stderr(
    stream: asyncio.StreamReader,
    messages: list[str],
) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        message = line.decode("utf-8", errors="replace").strip()
        if message:
            messages.append(message)
            del messages[:-20]


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        await process.wait()
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _probe_rtsp_source(settings: Settings, source_url: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *_build_ffmpeg_command(settings, source_url, frame_limit=1),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        await _stop_process(process)
        raise RuntimeError("无法读取 FFmpeg 探测输出")

    stderr_messages: list[str] = []
    stderr_task = asyncio.create_task(_collect_stderr(process.stderr, stderr_messages))
    try:
        await _read_jpeg_frame(
            process.stdout,
            bytearray(),
            settings.rtsp_startup_timeout,
        )
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, RuntimeError) as error:
        reason = stderr_messages[-1] if stderr_messages else str(error)
        reason = reason or "等待视频首帧超时"
        reason = _redact_rtsp_details(reason, source_url)
        raise RuntimeError(reason) from error
    finally:
        await _stop_process(process)
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task


def _multipart_frame(frame: bytes) -> bytes:
    return (
        (
            f"--{MJPEG_BOUNDARY}\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame)}\r\n\r\n"
        ).encode("ascii")
        + frame
        + b"\r\n"
    )


@router.get("/video/status", response_model=VideoStatus)
async def get_video_status() -> VideoStatus:
    settings = get_settings()
    ffmpeg_ready = _ffmpeg_executable(settings) is not None

    if not ffmpeg_ready:
        detail = f"找不到 FFmpeg: {settings.ffmpeg_path}"
    else:
        detail = "RTSP 转流服务已就绪"

    return VideoStatus(
        ready=ffmpeg_ready,
        transport=settings.rtsp_transport,
        frame_rate=settings.rtsp_frame_rate,
        width=settings.rtsp_width,
        detail=detail,
    )


def _clear_expired_sessions(now: Optional[float] = None) -> list[str]:
    current_time = time.monotonic() if now is None else now
    expired_ids = [
        session_id
        for session_id, (_, expires_at) in _video_sessions.items()
        if expires_at <= current_time
    ]
    for session_id in expired_ids:
        _video_sessions.pop(session_id, None)
    return expired_ids


def _register_stream_process(
    session_id: str,
    process: asyncio.subprocess.Process,
) -> None:
    _active_stream_processes.setdefault(session_id, set()).add(process)


def _unregister_stream_process(
    session_id: str,
    process: asyncio.subprocess.Process,
) -> None:
    processes = _active_stream_processes.get(session_id)
    if not processes:
        return
    processes.discard(process)
    if not processes:
        _active_stream_processes.pop(session_id, None)


def _touch_video_session(session_id: str, ttl: int) -> None:
    session = _video_sessions.get(session_id)
    if session is None:
        return
    source_url, _ = session
    _video_sessions[session_id] = (source_url, time.monotonic() + ttl)


async def _stop_session_streams(session_id: str) -> None:
    processes = list(_active_stream_processes.pop(session_id, set()))
    if processes:
        await asyncio.gather(
            *(_stop_process(process) for process in processes),
            return_exceptions=True,
        )


async def shutdown_video_streams() -> None:
    session_ids = list(_active_stream_processes)
    if session_ids:
        await asyncio.gather(
            *(_stop_session_streams(session_id) for session_id in session_ids),
            return_exceptions=True,
        )
    _video_sessions.clear()


@router.post("/video/sessions", response_model=VideoSessionResponse)
async def create_video_session(
    payload: VideoSessionRequest,
) -> VideoSessionResponse:
    global _pending_probes

    settings = get_settings()
    status = await get_video_status()
    if not status.ready:
        raise HTTPException(status_code=503, detail=status.detail)

    try:
        source_url = await _validated_rtsp_destination(settings, payload.source_url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    async with _video_state_lock:
        expired_ids = _clear_expired_sessions()
        if len(_video_sessions) + _pending_probes >= settings.rtsp_max_sessions:
            raise HTTPException(status_code=429, detail="RTSP 视频会话数量已达上限")
        _pending_probes += 1
    for expired_id in expired_ids:
        await _stop_session_streams(expired_id)

    try:
        try:
            await _probe_rtsp_source(settings, source_url)
        except (FileNotFoundError, OSError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except RuntimeError as error:
            logger.warning("RTSP source probe failed: %s", error)
            raise HTTPException(
                status_code=504,
                detail=f"未检测到可用视频流: {error}",
            ) from error

        # 保留 pending 名额直到成功会话已经写入，避免“pending--”与插入
        # 之间被并发请求抢占并突破 rtsp_max_sessions。
        async with _video_state_lock:
            session_id = secrets.token_urlsafe(24)
            _video_sessions[session_id] = (
                source_url,
                time.monotonic() + settings.rtsp_session_ttl,
            )
    finally:
        async with _video_state_lock:
            _pending_probes -= 1

    return VideoSessionResponse(
        session_id=session_id,
        stream_path=f"/api/v1/video/stream/{session_id}",
    )


@router.delete("/video/sessions/{session_id}")
async def delete_video_session(session_id: str) -> dict[str, str]:
    async with _video_state_lock:
        _video_sessions.pop(session_id, None)
    await _stop_session_streams(session_id)
    return {"status": "deleted"}


@router.get("/video/stream/{session_id}")
async def stream_video(session_id: str, request: Request) -> StreamingResponse:
    settings = get_settings()
    async with _video_state_lock:
        expired_ids = _clear_expired_sessions()
        session = _video_sessions.get(session_id)
    for expired_id in expired_ids:
        await _stop_session_streams(expired_id)
    if session is None:
        raise HTTPException(status_code=404, detail="RTSP 视频会话不存在或已过期")
    source_url, _ = session

    async with _video_state_lock:
        total_streams = sum(
            len(processes) for processes in _active_stream_processes.values()
        )
        session_streams = len(_active_stream_processes.get(session_id, set()))
        if total_streams >= settings.rtsp_max_streams:
            raise HTTPException(status_code=429, detail="RTSP 转码进程数量已达上限")
        if session_streams >= settings.rtsp_max_streams_per_session:
            raise HTTPException(status_code=429, detail="该 RTSP 会话已有活动视频流")
        try:
            process = await asyncio.create_subprocess_exec(
                *_build_ffmpeg_command(settings, source_url),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        _register_stream_process(session_id, process)

    if process.stdout is None or process.stderr is None:
        await _stop_process(process)
        _unregister_stream_process(session_id, process)
        raise HTTPException(status_code=500, detail="无法读取 FFmpeg 输出")

    stderr_messages: list[str] = []
    stderr_task = asyncio.create_task(_collect_stderr(process.stderr, stderr_messages))
    buffer = bytearray()

    try:
        first_frame = await _read_jpeg_frame(
            process.stdout,
            buffer,
            settings.rtsp_startup_timeout,
        )
    except asyncio.CancelledError:
        await _stop_process(process)
        _unregister_stream_process(session_id, process)
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
        raise
    except (asyncio.TimeoutError, RuntimeError) as error:
        await _stop_process(process)
        _unregister_stream_process(session_id, process)
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
        reason = stderr_messages[-1] if stderr_messages else str(error)
        reason = _redact_rtsp_details(reason, source_url)
        logger.warning("RTSP stream startup failed: %s", reason)
        raise HTTPException(
            status_code=504,
            detail=f"RTSP 视频连接失败: {reason}",
        ) from error

    async def generate_frames():
        try:
            _touch_video_session(session_id, settings.rtsp_session_ttl)
            yield _multipart_frame(first_frame)
            while not await request.is_disconnected():
                try:
                    frame = await _read_jpeg_frame(process.stdout, buffer, 2.0)
                except asyncio.TimeoutError:
                    if process.returncode is not None:
                        break
                    continue
                except RuntimeError:
                    break
                _touch_video_session(session_id, settings.rtsp_session_ttl)
                yield _multipart_frame(frame)
        except asyncio.CancelledError:
            raise
        finally:
            await _stop_process(process)
            _unregister_stream_process(session_id, process)
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task

    return StreamingResponse(
        generate_frames(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
