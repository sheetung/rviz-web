"""Convert TIERS mapping inputs using the sourced ROS2 native writer.

Requires rosbag2_py (source ROS2) and rosbags in a separate tool environment.
Preserves recording/header timestamps; never invents calibration or a map.
"""

import argparse
from bisect import bisect_left
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

import rosbag2_py
from rosbags.rosbag1 import Reader
from rosbags.typesys import Stores, get_typestore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--pose-topic", default="/vrpn_client_node/unitree_b1/pose")
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("Destination exists; refusing to overwrite")
    source_types = get_typestore(Stores.ROS1_NOETIC)
    target_types = get_typestore(Stores.ROS2_HUMBLE)
    samples = defaultdict(list)
    offsets = defaultdict(list)
    stats = {}
    poses = []
    pose_topic = args.pose_topic
    with Reader(args.source) as reader:
        required = {
            pose_topic,
            "/avia/livox/lidar",
            "/mid360/livox/lidar",
            "/ouster/points",
        }
        if not required.issubset({c.topic for c in reader.connections}):
            raise ValueError("Expected TIERS LiDAR and selected reference pose topics")
        # The audited dataset uses only these structurally compatible standard
        # types. Humble serialization omits ROS1 Header.seq, retains other fields.
        supported = {
            "sensor_msgs/msg/PointCloud2",
            "sensor_msgs/msg/Imu",
            "geometry_msgs/msg/PoseStamped",
        }
        if any(c.msgtype not in supported for c in reader.connections):
            raise ValueError("Unsupported message type; inspect before converting")
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        writer = rosbag2_py.SequentialWriter()
        writer.open(
            rosbag2_py.StorageOptions(uri=str(args.destination), storage_id="sqlite3"),
            rosbag2_py.ConverterOptions("cdr", "cdr"),
        )
        for connection in reader.connections:
            topic = connection.topic
            if topic in stats:
                raise ValueError("Multiple source connections per topic require review")
            writer.create_topic(
                rosbag2_py.TopicMetadata(
                    name=topic, type=connection.msgtype, serialization_format="cdr"
                )
            )
            stats[topic] = dict(
                type=connection.msgtype,
                expected=connection.msgcount,
                count=0,
                frames=[],
                timestamp_reversals=0,
            )
        for connection, bag_time, raw in reader.messages():
            topic = connection.topic
            message = source_types.deserialize_ros1(raw, connection.msgtype)
            stamp = message.header.stamp.sec + message.header.stamp.nanosec / 1e9
            stat = stats[topic]
            if samples[topic] and stamp < samples[topic][-1]:
                stat["timestamp_reversals"] += 1
            samples[topic].append(stamp)
            offsets[topic].append(stamp - bag_time / 1e9)
            if message.header.frame_id not in stat["frames"]:
                stat["frames"].append(message.header.frame_id)
            if stat["count"] == 0 and hasattr(message, "fields"):
                stat["fields"] = [field.name for field in message.fields]
                stat["first_points"] = message.width * message.height
            if topic == pose_topic:
                p, q = message.pose.position, message.pose.orientation
                poses.append((p.x, p.y, p.z))
                norm = math.sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
                if not math.isfinite(norm) or abs(norm - 1) > 0.01:
                    stat["invalid_quaternions"] = stat.get("invalid_quaternions", 0) + 1
            # Roundtrip correctness is separately checked with native ROS2 readers.
            cdr = target_types.serialize_cdr(message, connection.msgtype)
            writer.write(topic, bytes(cdr), bag_time)
            stat["count"] += 1
        del writer  # Native writer finalizes metadata.yaml on destruction.
    for topic, stat in stats.items():
        times = samples[topic]
        stat.update(
            header_start=min(times),
            header_end=max(times),
            header_minus_bag_median_s=statistics.median(offsets[topic]),
        )
        assert stat["count"] == stat["expected"]
    pose_times = sorted(samples[pose_topic])
    alignment = {}
    for topic in ("/avia/livox/lidar", "/mid360/livox/lidar", "/ouster/points"):
        distances = []
        for stamp in samples[topic]:
            index = bisect_left(pose_times, stamp)
            neighbours = pose_times[max(0, index - 1) : min(len(pose_times), index + 1)]
            distances.append(min(abs(stamp - t) for t in neighbours))
        alignment[topic] = dict(
            nearest_pose_median_ms=statistics.median(distances) * 1000,
            nearest_pose_max_ms=max(distances) * 1000,
        )
    report = dict(
        source=str(args.source),
        destination=str(args.destination),
        reference_pose_topic=pose_topic,
        topics=stats,
        pose_xyz_min=[min(p[i] for p in poses) for i in range(3)],
        pose_xyz_max=[max(p[i] for p in poses) for i in range(3)],
        lidar_to_pose_header_alignment=alignment,
        calibration="No extrinsics applied; calibration required before map generation",
    )
    (args.destination / "mapping_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
