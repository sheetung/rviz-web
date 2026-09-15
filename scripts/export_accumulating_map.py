#!/usr/bin/env python3
"""Accumulate original Mid360 scans using an offline GLIM lidar trajectory.

Per-point poses use linear translation and quaternion SLERP between saved poses.
This approximates deskewing; it is not GLIM's internal IMU deskewer or online SLAM.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hz", type=float, default=5)
    parser.add_argument("--voxel", type=float, default=0.1)
    args = parser.parse_args()
    if not all(np.isfinite(v) and v > 0 for v in (args.hz, args.voxel)):
        parser.error("hz and voxel must be positive and finite")
    trajectory = np.loadtxt(args.trajectory)
    if (
        trajectory.ndim != 2
        or trajectory.shape[1] != 8
        or not np.isfinite(trajectory).all()
        or not np.all(np.diff(trajectory[:, 0]) > 0)
    ):
        parser.error("Invalid trajectory")
    if not np.allclose(np.linalg.norm(trajectory[:, 4:], axis=1), 1, atol=1e-4):
        parser.error("Invalid trajectory quaternions")
    t0 = trajectory[0, 0]
    times = trajectory[:, 0] - t0
    rotations = Slerp(times, Rotation.from_quat(trajectory[:, 4:]))

    import rosbag2_py as rb
    from rclpy.serialization import deserialize_message, serialize_message
    from sensor_msgs.msg import PointCloud2, PointField

    reader = rb.SequentialReader()
    reader.open(
        rb.StorageOptions(uri=str(args.bag), storage_id="sqlite3"),
        rb.ConverterOptions("", ""),
    )
    reader.set_filter(rb.StorageFilter(topics=["/mid360/livox/lidar"]))
    args.output.mkdir(parents=True, exist_ok=False)
    writer = rb.SequentialWriter()
    writer.open(
        rb.StorageOptions(uri=str(args.output / "map_bag"), storage_id="sqlite3"),
        rb.ConverterOptions("", ""),
    )
    writer.create_topic(
        rb.TopicMetadata(
            name="/mapping/map_points",
            type="sensor_msgs/msg/PointCloud2",
            serialization_format="cdr",
        )
    )
    voxels = {}
    scans = skipped = snapshots = 0
    last_output = -float("inf")
    last_stamp = None
    counts = []

    def emit(stamp):
        points = np.asarray(list(voxels.values()), dtype="<f4")
        if points.nbytes > 8 * 1024 * 1024:
            raise ValueError(
                "Map exceeds 8 MiB budget; rerun with larger --voxel and a new output directory"
            )
        msg = PointCloud2()
        msg.header.frame_id = "map"
        msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, 10**9)
        msg.height, msg.width = 1, len(points)
        msg.point_step, msg.row_step = 12, points.nbytes
        msg.is_dense = True
        msg.fields = [
            PointField(name=n, offset=i * 4, datatype=PointField.FLOAT32, count=1)
            for i, n in enumerate(("x", "y", "z"))
        ]
        msg.data = points.tobytes()
        writer.write("/mapping/map_points", serialize_message(msg), stamp)
        counts.append(len(points))
        return points

    while reader.has_next():
        _, data, _ = reader.read_next()
        msg = deserialize_message(data, PointCloud2)
        fields = {f.name: f for f in msg.fields}
        if (
            msg.is_bigendian
            or msg.height != 1
            or any(
                n not in fields or fields[n].datatype != kind
                for n, kind in [("x", 7), ("y", 7), ("z", 7), ("timestamp", 8)]
            )
        ):
            raise ValueError("Unexpected Mid360 point layout")

        def field(name, dtype):
            return np.ndarray(
                (msg.width,),
                dtype=dtype,
                buffer=msg.data,
                offset=fields[name].offset,
                strides=(msg.point_step,),
            )

        xyz = np.column_stack([field(n, "<f4") for n in ("x", "y", "z")])
        point_times = field("timestamp", "<f8") * 1e-9 - t0
        valid = (
            np.isfinite(xyz).all(axis=1)
            & np.isfinite(point_times)
            & (point_times >= 0)
            & (point_times <= times[-1])
            & (np.linalg.norm(xyz, axis=1) >= 0.5)
        )
        if not valid.any():
            skipped += 1
            continue
        xyz, pt = xyz[valid], point_times[valid]
        positions = np.column_stack(
            [np.interp(pt, times, trajectory[:, i]) for i in (1, 2, 3)]
        )
        world = rotations(pt).apply(xyz) + positions
        keys = np.floor(world / args.voxel).astype(np.int64)
        _, indices = np.unique(keys, axis=0, return_index=True)
        for index in indices:
            voxels.setdefault(tuple(keys[index]), world[index].astype("<f4"))
        scans += 1
        # Publish only after the points in this scan have been acquired.
        stamp = int(round((t0 + pt.max()) * 1e9))
        last_stamp = stamp
        if stamp / 1e9 - last_output >= 1 / args.hz - 0.005:
            emit(stamp)
            last_output = stamp / 1e9
            snapshots += 1
        if scans % 100 == 0:
            print(
                f"scans={scans}, voxels={len(voxels)}, snapshots={snapshots}",
                flush=True,
            )
    if last_stamp is None:
        raise ValueError("No scans overlap trajectory")
    if last_stamp / 1e9 > last_output:
        points = emit(last_stamp)
        snapshots += 1
    else:
        points = np.asarray(list(voxels.values()), dtype="<f4")
    writer = None
    with (args.output / "map.ply").open("xb") as stream:
        stream.write(
            (
                f"ply\nformat binary_little_endian 1.0\nelement vertex {len(points)}\n"
                "property float x\nproperty float y\nproperty float z\nend_header\n"
            ).encode()
        )
        stream.write(points.tobytes())
    report = dict(
        scans=scans,
        skipped_scans=skipped,
        snapshots=snapshots,
        points=len(points),
        point_bytes=points.nbytes,
        target_hz=args.hz,
        voxel_metres=args.voxel,
        snapshot_points=counts,
        method="Offline GLIM trajectory; per-point linear/SLERP interpolation, not online SLAM",
    )
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print({k: v for k, v in report.items() if k != "snapshot_points"})


if __name__ == "__main__":
    main()
