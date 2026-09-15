#!/usr/bin/env python3
"""Copy a map bag and merge timestamped GLIM lidar Odometry and TF.

Pose-only visualization output: twist and covariance are not estimated.
The child frame is the lidar, not an uncalibrated robot base frame.
"""

import argparse
from decimal import Decimal
import math
from pathlib import Path


def load_trajectory(path):
    poses = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) != 8:
            raise ValueError("Expected TUM timestamp + XYZ + XYZW")
        stamp = int(Decimal(fields[0]) * 10**9)
        pose = [float(x) for x in fields[1:]]
        if not all(math.isfinite(x) for x in pose):
            raise ValueError("Nonfinite pose")
        if abs(sum(x * x for x in pose[3:]) - 1) > 1e-4:
            raise ValueError("Invalid quaternion")
        if poses and stamp <= poses[-1][0]:
            raise ValueError("Nonmonotonic trajectory")
        poses.append((stamp, pose))
    if not poses:
        raise ValueError("Empty trajectory")
    return poses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("output", type=Path, help="New ROS2 bag directory")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; refusing to overwrite")
    poses = load_trajectory(args.trajectory)
    import rosbag2_py as rb
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from tf2_msgs.msg import TFMessage
    from rclpy.serialization import serialize_message

    reader = rb.SequentialReader()
    reader.open(
        rb.StorageOptions(uri=str(args.bag), storage_id="sqlite3"),
        rb.ConverterOptions("", ""),
    )
    topics = reader.get_all_topics_and_types()
    if any(t.name in ("/tf", "/mapping/odom") for t in topics):
        parser.error("Input already contains tracking topics")
    writer = rb.SequentialWriter()
    writer.open(
        rb.StorageOptions(uri=str(args.output), storage_id="sqlite3"),
        rb.ConverterOptions("", ""),
    )
    for topic in topics:
        writer.create_topic(topic)
    for name, kind in [
        ("/tf", "tf2_msgs/msg/TFMessage"),
        ("/mapping/odom", "nav_msgs/msg/Odometry"),
    ]:
        writer.create_topic(
            rb.TopicMetadata(name=name, type=kind, serialization_format="cdr")
        )

    def write_tracking(stamp, pose):
        odom = Odometry()
        odom.header.frame_id = "map"
        odom.header.stamp.sec, odom.header.stamp.nanosec = divmod(stamp, 10**9)
        odom.child_frame_id = "mapping_lidar"
        (
            odom.pose.pose.position.x,
            odom.pose.pose.position.y,
            odom.pose.pose.position.z,
        ) = pose[:3]
        q = odom.pose.pose.orientation
        q.x, q.y, q.z, q.w = pose[3:]
        tf = TransformStamped()
        tf.header = odom.header
        tf.child_frame_id = odom.child_frame_id
        (
            tf.transform.translation.x,
            tf.transform.translation.y,
            tf.transform.translation.z,
        ) = pose[:3]
        tf.transform.rotation = q
        writer.write("/tf", serialize_message(TFMessage(transforms=[tf])), stamp)
        writer.write("/mapping/odom", serialize_message(odom), stamp)

    index = count = 0
    while reader.has_next():
        topic, data, stamp = reader.read_next()
        while index < len(poses) and poses[index][0] <= stamp:
            write_tracking(*poses[index])
            index += 1
        writer.write(topic, data, stamp)
        count += 1
    for pose in poses[index:]:
        write_tracking(*pose)
    writer = None
    print(
        f"Copied {count} messages; added {len(poses)} Odometry and {len(poses)} TF messages"
    )


if __name__ == "__main__":
    main()
