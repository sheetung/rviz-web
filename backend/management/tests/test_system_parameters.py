"""系统参数不允许通过环境变量覆盖。"""

from app.core.config import Settings


def test_system_parameters_ignore_environment(monkeypatch):
    monkeypatch.setenv("CONFIG_MAX_BYTES", "2048")
    monkeypatch.setenv("RTSP_TRANSPORT", "udp")
    monkeypatch.setenv("RTSP_ALLOW_PRIVATE_NETWORKS", "true")
    monkeypatch.setenv("FFMPEG_PATH", "/tmp/custom-ffmpeg")

    settings = Settings(_env_file=None)

    assert settings.config_max_bytes == 1_048_576
    assert settings.rtsp_transport == "tcp"
    assert settings.rtsp_allow_private_networks is False
    assert settings.ffmpeg_path == "ffmpeg"


def test_system_parameters_are_not_settings_fields():
    system_names = {
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
