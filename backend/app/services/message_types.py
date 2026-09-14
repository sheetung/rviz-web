"""
ROS2 消息类型注册表与解析
将消息类型字符串解析为对应的 Python 类
"""

import importlib
import logging

from ..core.ros_types import canonical_message_type

logger = logging.getLogger(__name__)

# 常用消息类型注册表
MESSAGE_TYPE_REGISTRY: dict[str, tuple[str, str]] = {
    # 标准消息类型
    "std_msgs/msg/String": ("std_msgs.msg", "String"),
    "std_msgs/msg/Float64": ("std_msgs.msg", "Float64"),
    "std_msgs/msg/Float32": ("std_msgs.msg", "Float32"),
    "std_msgs/msg/Int32": ("std_msgs.msg", "Int32"),
    "std_msgs/msg/Bool": ("std_msgs.msg", "Bool"),
    # 传感器消息类型
    "sensor_msgs/msg/PointCloud2": ("sensor_msgs.msg", "PointCloud2"),
    "sensor_msgs/msg/LaserScan": ("sensor_msgs.msg", "LaserScan"),
    "sensor_msgs/msg/Image": ("sensor_msgs.msg", "Image"),
    "sensor_msgs/msg/CompressedImage": ("sensor_msgs.msg", "CompressedImage"),
    "sensor_msgs/msg/CameraInfo": ("sensor_msgs.msg", "CameraInfo"),
    "sensor_msgs/msg/Imu": ("sensor_msgs.msg", "Imu"),
    "sensor_msgs/msg/JointState": ("sensor_msgs.msg", "JointState"),
    "sensor_msgs/msg/PointField": ("sensor_msgs.msg", "PointField"),
    "sensor_msgs/msg/NavSatFix": ("sensor_msgs.msg", "NavSatFix"),
    "sensor_msgs/msg/NavSatStatus": ("sensor_msgs.msg", "NavSatStatus"),
    # 几何消息类型
    "geometry_msgs/msg/Twist": ("geometry_msgs.msg", "Twist"),
    "geometry_msgs/msg/Pose": ("geometry_msgs.msg", "Pose"),
    "geometry_msgs/msg/PoseStamped": ("geometry_msgs.msg", "PoseStamped"),
    "geometry_msgs/msg/PoseWithCovariance": ("geometry_msgs.msg", "PoseWithCovariance"),
    "geometry_msgs/msg/PoseWithCovarianceStamped": (
        "geometry_msgs.msg",
        "PoseWithCovarianceStamped",
    ),
    "geometry_msgs/msg/Point": ("geometry_msgs.msg", "Point"),
    "geometry_msgs/msg/Vector3": ("geometry_msgs.msg", "Vector3"),
    "geometry_msgs/msg/Quaternion": ("geometry_msgs.msg", "Quaternion"),
    "geometry_msgs/msg/Transform": ("geometry_msgs.msg", "Transform"),
    "geometry_msgs/msg/TransformStamped": ("geometry_msgs.msg", "TransformStamped"),
    # 导航消息类型
    "nav_msgs/msg/OccupancyGrid": ("nav_msgs.msg", "OccupancyGrid"),
    "nav_msgs/msg/Path": ("nav_msgs.msg", "Path"),
    "nav_msgs/msg/Odometry": ("nav_msgs.msg", "Odometry"),
    "nav_msgs/msg/MapMetaData": ("nav_msgs.msg", "MapMetaData"),
    "nav_msgs/msg/GridCells": ("nav_msgs.msg", "GridCells"),
    # 可视化消息类型
    "visualization_msgs/msg/Marker": ("visualization_msgs.msg", "Marker"),
    "visualization_msgs/msg/MarkerArray": ("visualization_msgs.msg", "MarkerArray"),
    "visualization_msgs/msg/InteractiveMarker": (
        "visualization_msgs.msg",
        "InteractiveMarker",
    ),
    "visualization_msgs/msg/InteractiveMarkerUpdate": (
        "visualization_msgs.msg",
        "InteractiveMarkerUpdate",
    ),
    # TF和诊断消息
    "tf2_msgs/msg/TFMessage": ("tf2_msgs.msg", "TFMessage"),
    "diagnostic_msgs/msg/DiagnosticArray": ("diagnostic_msgs.msg", "DiagnosticArray"),
    # 轨迹消息
    "trajectory_msgs/msg/JointTrajectory": ("trajectory_msgs.msg", "JointTrajectory"),
    "trajectory_msgs/msg/MultiDOFJointTrajectory": (
        "trajectory_msgs.msg",
        "MultiDOFJointTrajectory",
    ),
    # Action和状态消息
    "actionlib_msgs/msg/GoalStatus": ("actionlib_msgs.msg", "GoalStatus"),
    "rosgraph_msgs/msg/Log": ("rosgraph_msgs.msg", "Log"),
}

# 可选的消息类型（可能不存在的包）
OPTIONAL_MESSAGE_TYPES: dict[str, tuple[str, str]] = {
    "move_base_msgs/msg/MoveBaseAction": ("move_base_msgs.msg", "MoveBaseAction"),
    "costmap_2d/msg/VoxelGrid": ("costmap_2d.msg", "VoxelGrid"),
    "map_msgs/msg/OccupancyGridUpdate": ("map_msgs.msg", "OccupancyGridUpdate"),
    "gps_msgs/msg/GPSStatus": ("gps_msgs.msg", "GPSStatus"),
    "gps_msgs/msg/GPSFix": ("gps_msgs.msg", "GPSFix"),
}


def get_message_class(msg_type: str):
    """解析 ROS2 消息类型字符串为对应的 Python 类"""
    try:
        msg_type = canonical_message_type(msg_type)
    except ValueError as error:
        logger.warning("Invalid ROS message type: %s", error)
        return None

    if msg_type in MESSAGE_TYPE_REGISTRY:
        module_name, class_name = MESSAGE_TYPE_REGISTRY[msg_type]
        try:
            module = __import__(module_name, fromlist=[class_name])
            return getattr(module, class_name)
        except ImportError as e:
            logger.error(f"Failed to import {module_name}.{class_name}: {e}")
            return None

    elif msg_type in OPTIONAL_MESSAGE_TYPES:
        module_name, class_name = OPTIONAL_MESSAGE_TYPES[msg_type]
        try:
            module = __import__(module_name, fromlist=[class_name])
            return getattr(module, class_name)
        except ImportError:
            logger.warning(
                f"{module_name} not available, cannot use message type {msg_type}"
            )
            return None
    else:
        try:
            package_name, namespace, class_name = msg_type.split("/")
        except ValueError:
            logger.warning(f"Invalid ROS message type format: {msg_type}")
            return None

        if namespace != "msg":
            logger.warning(f"Unsupported ROS interface namespace for {msg_type}")
            return None

        module_name = f"{package_name}.msg"
        try:
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            logger.warning(
                f"Cannot import message type {msg_type} from {module_name}: {e}"
            )
        return None
