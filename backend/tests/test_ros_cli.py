import subprocess
from unittest.mock import Mock

from app.services.ros2_service import Ros2Service


def test_topic_discovery_does_not_use_ros2_daemon(settings, monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="/points [sensor_msgs/msg/PointCloud2]\n",
            stderr="",
        )
    )
    monkeypatch.setattr("app.services.ros2_service.subprocess.run", run)
    service = Ros2Service(settings)

    topics = service._get_topics_from_cli_sync()

    command = run.call_args.args[0]
    assert command == ["ros2", "topic", "list", "-t", "--no-daemon"]
    assert [(topic.name, topic.message_type) for topic in topics] == [
        ("/points", "sensor_msgs/msg/PointCloud2"),
    ]
