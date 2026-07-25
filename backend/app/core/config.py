"""
应用配置管理
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    backend_port: int = Field(default=8000, description="后端服务端口")
    debug: bool = Field(default=False, description="调试模式")

    # ROS2 配置
    ros_domain_id: int = Field(default=0, description="ROS2 Domain ID")
    max_connections: int = Field(default=100, description="最大连接数")
    ros_max_subscriptions_per_client: int = Field(default=64, ge=1, le=1024)
    ros_max_publishers: int = Field(default=32, ge=1, le=1024)
    message_buffer_size: int = Field(default=10000, description="消息缓冲区大小")
    ros_graph_cache_ttl: float = Field(default=2.0, ge=0.1, le=30.0)
    ros_pointcloud_max_bytes: int = Field(
        default=8_388_608,
        ge=1_048_576,
        le=268_435_456,
    )
    ros_pointcloud_max_hz: float = Field(default=10.0, ge=0.0, le=120.0)
    ros_pointcloud_xyz_only: bool = Field(default=True)
    ros_image_max_bytes: int = Field(
        default=8_388_608,
        ge=262_144,
        le=67_108_864,
    )

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
    ros_publish_type_allowlist: str = Field(
        default=(
            "geometry_msgs/msg/PoseStamped,"
            "geometry_msgs/msg/PoseWithCovarianceStamped,"
            "geometry_msgs/msg/Twist,"
            "geometry_msgs/msg/Pose"
        ),
        description="允许发布的 ROS 消息类型，逗号分隔",
    )
    websocket_max_message_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
    )
    websocket_send_timeout: float = Field(default=2.0, ge=0.1, le=30.0)
    websocket_outbound_queue_size: int = Field(default=8, ge=1, le=1024)
    websocket_max_outbound_message_bytes: int = Field(
        default=16_777_216,
        ge=1024,
        le=268_435_456,
    )
    websocket_max_requests_per_second: int = Field(
        default=30,
        ge=1,
        le=1000,
    )
    config_max_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    config_name_max_length: int = Field(default=96, ge=8, le=200)
    config_backup_max_files: int = Field(default=50, ge=0, le=1000)
    config_backup_max_bytes: int = Field(
        default=52_428_800,
        ge=0,
        le=1_073_741_824,
    )

    # RTSP 视频转流配置
    rtsp_transport: Literal["tcp", "udp"] = Field(default="tcp")
    rtsp_frame_rate: int = Field(default=12, ge=1, le=30)
    rtsp_width: int = Field(default=640, ge=160, le=1920)
    rtsp_jpeg_quality: int = Field(default=5, ge=2, le=31)
    rtsp_startup_timeout: float = Field(default=10.0, ge=2.0, le=30.0)
    rtsp_session_ttl: int = Field(default=300, ge=30, le=3600)
    rtsp_max_sessions: int = Field(default=4, ge=1, le=64)
    rtsp_max_streams: int = Field(default=4, ge=1, le=64)
    rtsp_max_streams_per_session: int = Field(default=1, ge=1, le=8)
    rtsp_allow_private_networks: bool = Field(
        default=False,
        description="是否允许 RTSP 连接 RFC1918/ULA 私网地址",
    )
    rtsp_allowed_hosts: str = Field(
        default="",
        description="额外允许的 RTSP 主机名或 IP，逗号分隔",
    )
    ffmpeg_path: str = Field(default="ffmpeg", description="FFmpeg 可执行文件路径")


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例"""
    return Settings()
