import pytest

from app.core.ros_types import canonical_message_type, ros1_message_type
from app.models.ros import TopicInfo
from app.services.ros_contract import RosService
from app.services.ros2_service import Ros2Service


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sensor_msgs/msg/PointCloud2", "sensor_msgs/msg/PointCloud2"),
        ("sensor_msgs/PointCloud2", "sensor_msgs/msg/PointCloud2"),
        (" geometry_msgs/PoseStamped ", "geometry_msgs/msg/PoseStamped"),
        ("unknown", "unknown"),
    ],
)
def test_message_types_are_normalized_at_the_protocol_boundary(source, expected):
    assert canonical_message_type(source) == expected


@pytest.mark.parametrize(
    "message_type",
    ["", "sensor_msgs", "sensor_msgs/srv/GetMap", "/msg/Pose", "bad-name/Pose"],
)
def test_invalid_message_types_are_rejected(message_type):
    with pytest.raises(ValueError):
        canonical_message_type(message_type)


def test_canonical_type_can_be_rendered_for_ros1():
    assert ros1_message_type("geometry_msgs/msg/Twist") == "geometry_msgs/Twist"


def test_topic_model_never_exposes_ros1_type_format():
    topic = TopicInfo(name="/points", message_type="sensor_msgs/PointCloud2")

    assert topic.message_type == "sensor_msgs/msg/PointCloud2"


def test_ros2_service_implements_application_contract(settings):
    service = Ros2Service(settings)

    assert isinstance(service, RosService)
    assert service.middleware == "ros2"
