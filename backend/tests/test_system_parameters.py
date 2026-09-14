"""系统参数不允许通过环境变量覆盖。"""

from app.core.config import Settings


def test_system_parameters_ignore_environment(monkeypatch):
    monkeypatch.setenv("ROS_POINTCLOUD_MAX_HZ", "120")
    monkeypatch.setenv("WEBSOCKET_MAX_REQUESTS_PER_SECOND", "999")
    monkeypatch.setenv("CONFIG_MAX_BYTES", "2048")
    monkeypatch.setenv("RTSP_TRANSPORT", "udp")
    monkeypatch.setenv("RTSP_ALLOW_PRIVATE_NETWORKS", "true")
    monkeypatch.setenv("FFMPEG_PATH", "/tmp/custom-ffmpeg")

    settings = Settings(_env_file=None)

    assert settings.ros_pointcloud_max_hz == 10.0
    assert settings.websocket_max_requests_per_second == 30
    assert settings.config_max_bytes == 1_048_576
    assert settings.rtsp_transport == "tcp"
    assert settings.rtsp_allow_private_networks is False
    assert settings.ffmpeg_path == "ffmpeg"


def test_system_parameters_are_not_settings_fields():
    system_names = {
        "max_connections",
        "message_buffer_size",
        "ros_max_subscriptions_per_client",
        "ros_max_publishers",
        "ros_graph_cache_ttl",
        "ros_pointcloud_max_bytes",
        "ros_pointcloud_max_hz",
        "ros_pointcloud_xyz_only",
        "ros_image_max_bytes",
        "websocket_max_message_bytes",
        "websocket_send_timeout",
        "websocket_outbound_queue_size",
        "websocket_max_outbound_message_bytes",
        "websocket_max_requests_per_second",
        "config_max_bytes",
        "config_name_max_length",
        "config_backup_max_files",
        "config_backup_max_bytes",
        "rtsp_transport",
        "rtsp_frame_rate",
        "rtsp_width",
        "rtsp_jpeg_quality",
        "rtsp_startup_timeout",
        "rtsp_session_ttl",
        "rtsp_max_sessions",
        "rtsp_max_streams",
        "rtsp_max_streams_per_session",
        "rtsp_allow_private_networks",
        "rtsp_allowed_hosts",
        "ffmpeg_path",
    }

    assert system_names.isdisjoint(Settings.model_fields)
