#!/usr/bin/env python3
"""Export a GLIM 1.2.2 dump as PLY and cumulative ROS2 map snapshots.

Requires system numpy and sourced ROS2 Humble. Map poses come from GLIM's
optimized T_world_origin, not MoCap. Submap snapshots are an offline replay,
not a claim to reproduce live loop-closure timing.
"""

import argparse
from decimal import Decimal
import json
from pathlib import Path

import numpy as np


def read_submap(directory):
    lines = (directory / "data.txt").read_text().splitlines()
    start = lines.index("T_world_origin: ") + 1
    transform = np.array(
        [[float(x) for x in line.split()] for line in lines[start : start + 4]]
    )
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError(f"Invalid transform: {directory}")
    if not np.allclose(transform[3], [0, 0, 0, 1]):
        raise ValueError(f"Invalid homogeneous transform: {directory}")
    rotation = transform[:3, :3]
    if (
        not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4)
        or np.linalg.det(rotation) < 0
    ):
        raise ValueError(f"Invalid rotation: {directory}")
    # gtsam_points::PointCloud::save_compact: contiguous Eigen::Vector3f.
    points = np.fromfile(directory / "points_compact.bin", dtype="<f4").reshape(-1, 3)
    if not len(points) or not np.isfinite(points).all():
        raise ValueError(f"Invalid points: {directory}")
    stamps = [
        int(Decimal(line.split()[1]) * 1_000_000_000)
        for line in lines
        if line.startswith("stamp:")
    ]
    if not stamps:
        raise ValueError(f"No frame timestamps: {directory}")
    return points @ rotation.T + transform[:3, 3], max(stamps)


def voxel_filter(points, size):
    if not np.isfinite(size) or size <= 0:
        raise ValueError("Voxel size must be positive and finite")
    keys = np.floor(points / size).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    return np.asarray(points[np.sort(indices)], dtype="<f4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--voxel", type=float, default=0.08, help="Output voxel size in metres"
    )
    args = parser.parse_args()
    if not np.isfinite(args.voxel) or args.voxel <= 0:
        parser.error("--voxel must be positive and finite")
    directories = sorted(
        p for p in args.dump.iterdir() if p.is_dir() and p.name.isdigit()
    )
    if not directories:
        parser.error("No GLIM submaps found")

    import rosbag2_py
    from geometry_msgs.msg import PoseStamped
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import PointCloud2, PointField

    args.output.mkdir(parents=True, exist_ok=False)
    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(
            uri=str(args.output / "map_bag"), storage_id="sqlite3"
        ),
        rosbag2_py.ConverterOptions("", ""),
    )
    for name, kind in [
        ("/mapping/map_points", "sensor_msgs/msg/PointCloud2"),
        ("/mapping/lidar_pose", "geometry_msgs/msg/PoseStamped"),
    ]:
        writer.create_topic(
            rosbag2_py.TopicMetadata(name=name, type=kind, serialization_format="cdr")
        )

    trajectory = []
    for line in (args.dump / "traj_lidar.txt").read_text().splitlines():
        values = line.split()
        stamp = int(Decimal(values[0]) * 1_000_000_000)
        pose = np.array([float(v) for v in values[1:]])
        if (
            pose.shape != (7,)
            or not np.isfinite(pose).all()
            or abs(np.linalg.norm(pose[3:]) - 1) > 1e-4
        ):
            raise ValueError("Invalid trajectory pose")
        trajectory.append((stamp, pose))
    if not trajectory or any(b[0] <= a[0] for a, b in zip(trajectory, trajectory[1:])):
        raise ValueError("Empty or nonmonotonic trajectory")

    def write_pose(stamp, pose):
        msg = PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
        msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = map(
            float, pose[:3]
        )
        (
            msg.pose.orientation.x,
            msg.pose.orientation.y,
            msg.pose.orientation.z,
            msg.pose.orientation.w,
        ) = map(float, pose[3:])
        writer.write("/mapping/lidar_pose", serialize_message(msg), stamp)

    points = np.empty((0, 3), dtype="<f4")
    counts, pose_index, last_stamp = [], 0, -1
    for directory in directories:
        new_points, stamp = read_submap(directory)
        if stamp <= last_stamp:
            raise ValueError("Nonmonotonic submap end timestamps")
        last_stamp = stamp
        points = voxel_filter(np.concatenate([points, new_points]), args.voxel)
        if points.nbytes > 8 * 1024 * 1024:
            raise ValueError("Map exceeds 8 MiB point data budget; increase --voxel")
        while pose_index < len(trajectory) and trajectory[pose_index][0] <= stamp:
            write_pose(*trajectory[pose_index])
            pose_index += 1
        msg = PointCloud2()
        msg.header.frame_id = "map"
        msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
        msg.height, msg.width, msg.point_step, msg.row_step = (
            1,
            len(points),
            12,
            points.nbytes,
        )
        msg.is_dense = True
        msg.fields = [
            PointField(name=name, offset=i * 4, datatype=PointField.FLOAT32, count=1)
            for i, name in enumerate(("x", "y", "z"))
        ]
        msg.data = points.tobytes()
        writer.write("/mapping/map_points", serialize_message(msg), stamp)
        counts.append(
            {"submap": directory.name, "stamp_ns": stamp, "points": len(points)}
        )
    for stamp, pose in trajectory[pose_index:]:
        write_pose(stamp, pose)
    writer = None  # Finalize native rosbag metadata before reporting success.
    header = (
        f"ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    )
    with (args.output / "map.ply").open("xb") as stream:
        stream.write(header.encode("ascii"))
        stream.write(points.tobytes())
    xyz = np.array([pose[:3] for _, pose in trajectory])
    stats = {
        "frame": "map",
        "voxel_metres": args.voxel,
        "snapshots": counts,
        "final_points": len(points),
        "final_point_bytes": points.nbytes,
        "bounds_min": points.min(0).tolist(),
        "bounds_max": points.max(0).tolist(),
        "trajectory_poses": len(trajectory),
        "trajectory_distance_metres": float(
            np.linalg.norm(np.diff(xyz, axis=0), axis=1).sum()
        ),
        "note": "Offline optimized submap replay; reference Mid360 extrinsic, not calibrated MoCap evaluation.",
    }
    (args.output / "summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
