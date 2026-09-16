"""
应用配置管理
"""

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 后端服务配置
    backend_host: str = Field(default="127.0.0.1", description="后端服务主机")
    debug: bool = Field(default=False, description="调试模式")

    # 安全配置
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="允许访问 API 的前端来源",
    )
    # Management resource limits are code-owned, not environment overrides.
    config_max_bytes: ClassVar[int] = 1_048_576
    config_name_max_length: ClassVar[int] = 96
    config_backup_max_files: ClassVar[int] = 50
    config_backup_max_bytes: ClassVar[int] = 52_428_800
    rtsp_transport: ClassVar[Literal["tcp", "udp"]] = "tcp"
    rtsp_frame_rate: ClassVar[int] = 12
    rtsp_width: ClassVar[int] = 640
    rtsp_jpeg_quality: ClassVar[int] = 5
    rtsp_startup_timeout: ClassVar[float] = 10.0
    rtsp_session_ttl: ClassVar[int] = 300
    rtsp_max_sessions: ClassVar[int] = 4
    rtsp_max_streams: ClassVar[int] = 4
    rtsp_max_streams_per_session: ClassVar[int] = 1
    rtsp_allow_private_networks: ClassVar[bool] = False
    rtsp_allowed_hosts: ClassVar[str] = ""
    ffmpeg_path: ClassVar[str] = "ffmpeg"


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例"""
    return Settings()
