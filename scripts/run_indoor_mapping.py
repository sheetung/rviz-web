#!/usr/bin/env python3
"""Run isolated GLIM CPU on audited TIERS Mid360 bags (source ROS2 Humble first).

Validated inputs: IndoorOffice1 and OutdoorRoad_cut0. The historical filename is
retained; units and reference extrinsics must be audited for additional datasets.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path)
    parser.add_argument(
        "output", type=Path, help="New output directory; never overwritten"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = root / "local_data/glim_runtime/root"
    prefix = runtime / "opt/ros/humble"
    executable = prefix / "lib/glim_ros/glim_rosbag"
    if not executable.is_file() or not (args.bag / "metadata.yaml").is_file():
        parser.error("GLIM runtime or input ROS2 bag is missing")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = output / "config"
    config.mkdir()
    overrides = {
        "config.json": {
            "global": {
                "config_odometry": "config_odometry_cpu.json",
                "config_sub_mapping": "config_sub_mapping_passthrough.json",
                "config_global_mapping": "config_global_mapping_pose_graph.json",
            }
        },
        "config_ros.json": {
            "glim_ros": {
                "imu_topic": "/mid360/livox/imu",
                "points_topic": "/mid360/livox/lidar",
                "acc_scale": 9.80665,
                "extension_modules": [],
            }
        },
        "config_sensors.json": {
            "sensors": {
                # Inverse of FAST-LIO official mid360.yaml T_imu_lidar.
                # Reference extrinsic, NOT a dataset-specific calibration result.
                "T_lidar_imu": [0.011, 0.02329, -0.04412, 0, 0, 0, 1],
                "autoconf_perpoint_times": False,
                "perpoint_relative_time": False,
                "perpoint_time_scale": 1e-9,
            }
        },
        "config_logging.json": {"logging": {"log_dir": str(output / "logs")}},
    }
    for src in (prefix / "share/glim/config").glob("*.json"):
        # Official templates are JSON with comments; this handles their current format.
        data = json.loads(
            re.sub(r"/\*.*?\*/|//[^\n]*", "", src.read_text(), flags=re.S)
        )
        for section, changes in overrides.get(src.name, {}).items():
            data[section].update(changes)
        (config / src.name).write_text(json.dumps(data, indent=2) + "\n")
    (output / "logs").mkdir()
    env = os.environ.copy()
    env.update(
        ROS_LOG_DIR=str(output / "logs"), ROS_DOMAIN_ID="87", ROS_LOCALHOST_ONLY="1"
    )
    env["AMENT_PREFIX_PATH"] = str(prefix) + ":/opt/ros/humble"
    libs = [
        runtime / "usr/lib/x86_64-linux-gnu",
        runtime / "usr/lib",
        runtime / "usr/local/lib",
        prefix / "lib",
    ]
    env["LD_LIBRARY_PATH"] = (
        ":".join(map(str, libs)) + ":" + env.get("LD_LIBRARY_PATH", "")
    )
    command = [str(executable), str(args.bag.resolve())]
    command += [
        "--ros-args",
        "-p",
        f"config_path:={config}",
        "-p",
        f"dump_path:={output / 'dump'}",
        "-p",
        "auto_quit:=true",
    ]
    print("Running:", " ".join(command), flush=True)
    with (output / "run.log").open("x") as log:
        result = subprocess.run(
            command, env=env, cwd=output, stdout=log, stderr=subprocess.STDOUT
        )
    print(f"Exit {result.returncode}; log: {output / 'run.log'}", flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
