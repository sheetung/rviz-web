"""
应用配置管理
"""

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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

    # ROS2 配置
    ros_domain_id: int = Field(default=0, description="ROS2 Domain ID")

    # 安全配置
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="允许访问 API 的前端来源",
    )
    ros_subscribe_topic_allowlist: str = Field(
        default="*",
        description="允许订阅的 ROS topic glob，逗号分隔",
    )
    ros_publish_topic_allowlist: str = Field(
        default="/goal_pose,/initialpose,/cmd_vel",
        description="允许发布的 ROS topic glob，逗号分隔",
    )

    # 系统参数：只能在代码中调整，不接受 .env 覆盖。
    max_connections: ClassVar[int] = 100
    message_buffer_size: ClassVar[int] = 10_000
    ros_max_subscriptions_per_client: ClassVar[int] = 64
    ros_max_publishers: ClassVar[int] = 32
    ros_graph_cache_ttl: ClassVar[float] = 2.0
    ros_pointcloud_max_bytes: ClassVar[int] = 8_388_608
    ros_pointcloud_max_hz: ClassVar[float] = 10.0
    ros_pointcloud_xyz_only: ClassVar[bool] = True
    ros_image_max_bytes: ClassVar[int] = 8_388_608
    websocket_max_message_bytes: ClassVar[int] = 1_048_576
    websocket_send_timeout: ClassVar[float] = 2.0
    websocket_outbound_queue_size: ClassVar[int] = 8
    websocket_max_outbound_message_bytes: ClassVar[int] = 16_777_216
    websocket_max_requests_per_second: ClassVar[int] = 30
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
