#!/usr/bin/env python3
"""Infinite UAV patrol and goal tracking with lidar sampled from local real maps."""
import argparse
import fcntl
import hashlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import signal
import time

import numpy as np
from simulation.scene import Flight, Patrol, World, load_map

ROOT = Path(__file__).resolve().parents[1]
MAP_FRAME, BODY_FRAME, LIDAR_FRAME = "sim_map", "sim_uav/base_link", "sim_uav/lidar"
PREFIX = "/sim/uav"
LIDAR_OFFSET = np.array([0., 0., .18])


def make_config(patrol, filename):
    config = json.loads((ROOT / "rvizweb_configs/default.rvizweb").read_text())
    config["name"] = filename
    c = config["config"]
    c["fixedFrame"], c["followFrame"] = MAP_FRAME, BODY_FRAME
    start = patrol.points[0]
    c["scene"]["camera"] = {
        "position": dict(zip(("x", "y", "z"), map(float, start+[-13, -17, 12]))),
        "target": dict(zip(("x", "y", "z"), map(float, start))),
        "up": {"x": 0, "y": 0, "z": 1}, "zoom": 1, "projection": "perspective"}
    c["position"] = {"odomTopic": PREFIX+"/odom", "showRobotModel": False,
                     "showTrajectory": False, "trajectoryLength": 100}
    c["goal"] = {"topic": "/goal_pose", **dict(zip(("x", "y", "z"), map(float, start+[3, 2, 0])))}
    c["displays"] = [
        {"name": PREFIX+"/map", "messageType": "sensor_msgs/msg/PointCloud2", "visible": True,
         "config": {"renderStyle": "points", "pointSize": .045, "sparse": False}},
        {"name": PREFIX+"/points", "messageType": "sensor_msgs/msg/PointCloud2", "visible": True,
         "config": {"renderStyle": "points", "pointSize": .11, "sparse": False}},
        {"name": PREFIX+"/route", "messageType": "nav_msgs/msg/Path", "visible": True,
         "config": {"color": "#8a9bab", "lineWidth": 2}},
        {"name": PREFIX+"/trail", "messageType": "nav_msgs/msg/Path", "visible": True,
         "config": {"color": "#00d8ff", "lineWidth": 3}},
        {"name": PREFIX+"/markers", "messageType": "visualization_msgs/msg/MarkerArray", "visible": True,
         "config": {"opacity": 1}},
    ]
    c["laser"]["pointCloudTopic"] = ""
    c["layout"]["collapsedPanels"]["chart"] = True
    return config


class Ros:
    def __init__(self, name="rvizweb_uav_simulator"):
        self.version = os.environ.get("ROS_VERSION")
        if self.version == "2":
            import rclpy
            from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
            rclpy.init()
            self.api, self.node = rclpy, rclpy.create_node(name)
            self.qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
            self.static_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        elif self.version == "1":
            import rospy
            rospy.init_node(name, anonymous=True, disable_signals=True)
            self.api = rospy
        else:
            raise ValueError("Source a ROS 1 or ROS 2 environment")
        self.subscriptions = []

    def publisher(self, kind, topic, static=False):
        if self.version == "2":
            return self.node.create_publisher(kind, topic, self.static_qos if static else self.qos)
        return self.api.Publisher(topic, kind, queue_size=1, latch=static)

    def subscribe(self, kind, topic, callback):
        # ROS1 callbacks arrive on transport threads: queue commands for the main loop.
        if self.version == "2":
            sub = self.node.create_subscription(kind, topic, callback, 10)
        else:
            sub = self.api.Subscriber(topic, kind, callback, queue_size=1)
        self.subscriptions.append(sub)

    def stamp(self):
        return self.node.get_clock().now().to_msg() if self.version == "2" else self.api.Time.now()

    def spin(self):
        if self.version == "2":
            self.api.spin_once(self.node, timeout_sec=0)

    def close(self):
        if self.version == "2":
            self.node.destroy_node()
            self.api.shutdown()
        else:
            self.api.signal_shutdown("Simulator stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=("outdoor", "indoor"), default="outdoor")
    parser.add_argument("--rate", type=float, default=10, help="Lidar rate, 1..20 Hz")
    parser.add_argument("--speed", type=float, default=2, help="Patrol peak speed in m/s")
    parser.add_argument("--height", type=float, default=1.2, help="Height offset above recorded lidar route (not ground altitude)")
    parser.add_argument("--range", type=float, default=30, dest="radius")
    parser.add_argument("--noise", type=float, default=.01, help="Range noise standard deviation in metres")
    parser.add_argument("--duration", type=float, default=0, help="0 runs forever")
    parser.add_argument("--goal-topic", default="/goal_pose")
    parser.add_argument("--no-config", action="store_true", help="Do not create a view configuration")
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--resume", action="store_true", help="Ask the running simulator to resume patrol")
    command.add_argument("--stop", action="store_true", help="Stop the simulator in the configured ROS domain")
    args = parser.parse_args()
    if args.resume or args.stop:
        from std_msgs.msg import Empty
        ros = Ros("rvizweb_uav_sim_command")
        action = "resume" if args.resume else "stop"
        publisher = ros.publisher(Empty, PREFIX+"/"+action)
        try:
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                ros.spin()
                count = (publisher.get_subscription_count() if ros.version == "2"
                         else publisher.get_num_connections())
                if count:
                    publisher.publish(Empty())
                    for _ in range(30):
                        ros.spin()
                        time.sleep(.01)
                    print(f"Sent simulator {action} request.", flush=True)
                    return
                time.sleep(.05)
            parser.error("No simulator found in the configured ROS domain/Master")
        finally:
            ros.close()

    limits = {"rate": (1, 20), "speed": (.1, 8), "height": (0, 5), "radius": (2, 60),
              "noise": (0, .1), "duration": (0, 1e9)}
    for key, (low, high) in limits.items():
        if not math.isfinite(getattr(args, key)) or not low <= getattr(args, key) <= high:
            parser.error(f"{key} must be within {low}..{high}")
    scope = (os.environ.get("ROS_VERSION", "") + ":" +
             (os.environ.get("ROS_MASTER_URI", "") if os.environ.get("ROS_VERSION") == "1"
              else os.environ.get("ROS_DOMAIN_ID", "0")))
    lock_dir = ROOT / ".cache/uav-simulator"
    lock_dir.mkdir(parents=True, exist_ok=True)
    # Keep the file descriptor alive for the process lifetime; OS releases the lock on exit.
    lock = (lock_dir / (hashlib.sha256(scope.encode()).hexdigest()+".lock")).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("A simulator is already running for this ROS domain/Master")
    name = "OutdoorRoad_cut0" if args.scene == "outdoor" else "IndoorOffice1"
    cloud_path = ROOT / "local_data" / (name+"_accumulating_01") / "map.ply"
    trajectory_path = ROOT / "local_data" / (name+"_glim_cpu_01") / "dump/traj_lidar.txt"
    print(f"Loading {cloud_path}", flush=True)
    world = World(load_map(cloud_path))
    patrol = Patrol(trajectory_path, args.height, args.speed)
    flight = Flight(patrol, args.speed)
    if not args.no_config:
        filename = f"sim-uav-{args.scene}.rvizweb"
        destination = ROOT / "rvizweb_configs" / filename
        config = make_config(patrol, filename)
        config["config"]["goal"]["topic"] = args.goal_topic
        try:
            with destination.open("x") as stream:
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except FileExistsError:
            print(f"Keeping existing view config: {filename}", flush=True)
        print(f"In the web Settings tab, load {filename}", flush=True)

    from geometry_msgs.msg import Point, PoseStamped, TransformStamped
    from nav_msgs.msg import Odometry, Path as RosPath
    from sensor_msgs.msg import PointCloud2, PointField, Imu
    from std_msgs.msg import Empty, Float32, String
    from tf2_msgs.msg import TFMessage
    from visualization_msgs.msg import Marker, MarkerArray
    from queue import Queue, Empty as QueueEmpty, Full

    ros = Ros()
    pubs = {key: ros.publisher(kind, topic, static) for key, kind, topic, static in [
        ("map", PointCloud2, PREFIX+"/map", True), ("points", PointCloud2, PREFIX+"/points", False),
        ("odom", Odometry, PREFIX+"/odom", False), ("imu", Imu, PREFIX+"/imu", False),
        ("tf", TFMessage, "/tf", False), ("static_tf", TFMessage, "/tf_static", True),
        ("route", RosPath, PREFIX+"/route", True), ("trail", RosPath, PREFIX+"/trail", False),
        ("markers", MarkerArray, PREFIX+"/markers", False), ("status", String, PREFIX+"/status", True),
        ("speed", Float32, PREFIX+"/speed", False), ("height", Float32, PREFIX+"/height", False),
    ]}
    commands = Queue(maxsize=1)
    def enqueue(kind, message):
        try:
            commands.put_nowait((kind, message))
        except Full:
            try:
                commands.get_nowait()
            except QueueEmpty:
                pass
            try:
                commands.put_nowait((kind, message))
            except Full:
                pass
    ros.subscribe(PoseStamped, args.goal_topic, lambda msg: enqueue("goal", msg))
    ros.subscribe(Empty, PREFIX+"/resume", lambda msg: enqueue("resume", msg))
    ros.subscribe(Empty, PREFIX+"/stop", lambda msg: enqueue("stop", msg))

    def xyz(target, values):
        target.x, target.y, target.z = map(float, values)

    def pose(target, position, yaw):
        xyz(target.position, position)
        target.orientation.z, target.orientation.w = math.sin(yaw/2), math.cos(yaw/2)

    def cloud(points, frame, stamp):
        message = PointCloud2()
        message.header.frame_id, message.header.stamp = frame, stamp
        message.height, message.width = 1, len(points)
        fields = ("x", "y", "z", "intensity")[:points.shape[1]]
        message.fields = [PointField(name=n, offset=i*4, datatype=PointField.FLOAT32, count=1)
                          for i, n in enumerate(fields)]
        message.point_step, message.row_step = len(fields)*4, points.nbytes
        message.is_bigendian, message.is_dense, message.data = False, True, points.tobytes()
        return message

    def path_message(positions, stamp):
        message = RosPath()
        message.header.frame_id, message.header.stamp = MAP_FRAME, stamp
        for position in positions:
            item = PoseStamped()
            item.header = message.header
            pose(item.pose, position, 0)
            message.poses.append(item)
        return message

    static = TransformStamped()
    static.header.frame_id, static.child_frame_id = BODY_FRAME, LIDAR_FRAME
    xyz(static.transform.translation, LIDAR_OFFSET)
    static.transform.rotation.w = 1.
    map_cloud = cloud(world.points.astype("<f4"), MAP_FRAME, ros.stamp())
    trail = deque(maxlen=600)
    rng = np.random.default_rng(27)
    scanner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sim-lidar")
    scan_future = None
    scan_snapshot = None
    def sample_scan(sample_state):
        tick = time.monotonic()
        points = world.scan(sample_state.position+LIDAR_OFFSET, sample_state.yaw, args.radius,
                            noise=args.noise, rng=rng)
        return points, (time.monotonic()-tick)*1000
    stopped = False
    def stop(_sig, _frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def vehicle_markers(stamp, elapsed):
        result = MarkerArray()
        def marker(kind, position, scale, color, frame=BODY_FRAME):
            m = Marker()
            m.header.frame_id, m.header.stamp = frame, stamp
            m.ns, m.id, m.type, m.action = "uav_sim", len(result.markers), kind, Marker.ADD
            pose(m.pose, position, 0)
            xyz(m.scale, scale)
            m.color.r, m.color.g, m.color.b, m.color.a = map(float, color)
            result.markers.append(m)
            return m
        marker(Marker.CUBE, [0, 0, 0], [.55, .3, .16], [1, .48, .08, 1])
        marker(Marker.CUBE, [.23, 0, .09], [.15, .15, .08], [.05, .15, .2, 1])
        marker(Marker.CYLINDER, LIDAR_OFFSET, [.12, .12, .13], [0, .85, 1, 1])
        arms = marker(Marker.LINE_LIST, [0, 0, 0], [.055, 0, 0], [.55, .6, .65, 1])
        blades = marker(Marker.LINE_LIST, [0, 0, 0], [.035, 0, 0], [.05, .85, 1, 1])
        for x, y in [(-.38, -.38), (-.38, .38), (.38, -.38), (.38, .38)]:
            arms.points.extend([Point(x=0., y=0., z=0.), Point(x=x, y=y, z=.02)])
            marker(Marker.CYLINDER, [x, y, .045], [.3, .3, .015], [.2, .65, .85, .35])
            angle = elapsed*15 + (x+y)*3
            dx, dy = .17*math.cos(angle), .17*math.sin(angle)
            blades.points.extend([Point(x=x-dx, y=y-dy, z=.07), Point(x=x+dx, y=y+dy, z=.07)])
        label = marker(Marker.TEXT_VIEW_FACING, [0, 0, .85], [0, 0, .5], [1, .85, .45, 1])
        label.text = "UAV / " + flight.mode.upper()
        # Always send the target marker ID, with DELETE when no goal is active.
        target = marker(Marker.SPHERE, flight.goal.position if flight.goal else [0, 0, 0],
                        [.3, .3, .3], [1, .25, .35, .8], MAP_FRAME)
        if flight.goal is None:
            target.action = Marker.DELETE
        return result

    started = time.monotonic()
    next_pose = next_scan = next_static = next_status = 0.
    scan_count = 0
    scan_ms = 0.
    print(f"READY ROS{ros.version}: {len(world.points):,} map points; route {patrol.length:.1f}m, "
          f"cycle {patrol.period:.1f}s; lidar {args.rate:g}Hz; odometry/IMU 30Hz", flush=True)
    print(f"Goals: {args.goal_topic} (frame {MAP_FRAME}, or map alias); resume: {PREFIX}/resume. Ctrl+C stops.", flush=True)
    try:
        while not stopped and (not args.duration or time.monotonic()-started < args.duration):
            ros.spin()
            now = time.monotonic()-started
            try:
                kind, message = commands.get_nowait()
                if kind == "stop":
                    stopped = True
                    continue
                if kind == "resume":
                    flight.resume(now)
                else:
                    if message.header.frame_id not in (MAP_FRAME, "map"):
                        raise ValueError(f"Goal frame must be {MAP_FRAME} or map")
                    q = message.pose.orientation
                    qv = np.array([q.x, q.y, q.z, q.w])
                    if not np.isfinite(qv).all() or abs(np.dot(qv, qv)-1) > .001:
                        raise ValueError("Goal quaternion must be finite and normalized")
                    yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
                    p = message.pose.position
                    flight.command(np.array([p.x, p.y, p.z]), yaw, now, world.bounds)
                print(f"Command: {flight.last_event}", flush=True)
                next_status = 0
            except QueueEmpty:
                pass
            except ValueError as error:
                flight.last_event = f"Rejected goal: {error}"
                print(flight.last_event, flush=True)
                next_status = 0
            if now >= next_pose:
                state = flight.state(now)
                stamp = ros.stamp()
                odom = Odometry()
                odom.header.frame_id, odom.header.stamp, odom.child_frame_id = MAP_FRAME, stamp, BODY_FRAME
                pose(odom.pose.pose, state.position, state.yaw)
                c, s = math.cos(state.yaw), math.sin(state.yaw)
                rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
                xyz(odom.twist.twist.linear, state.velocity @ rotation)
                odom.twist.twist.angular.z = float(state.yaw_rate)
                transform = TransformStamped()
                transform.header, transform.child_frame_id = odom.header, BODY_FRAME
                xyz(transform.transform.translation, state.position)
                transform.transform.rotation = odom.pose.pose.orientation
                pubs["tf"].publish(TFMessage(transforms=[transform]))
                pubs["odom"].publish(odom)
                imu = Imu()
                imu.header.frame_id, imu.header.stamp = BODY_FRAME, stamp
                imu.orientation = odom.pose.pose.orientation
                imu.angular_velocity.z = float(state.yaw_rate)
                xyz(imu.linear_acceleration, (state.acceleration+[0, 0, 9.81]) @ rotation)
                pubs["imu"].publish(imu)
                next_pose = now+1/30
            if scan_future is not None and scan_future.done():
                points, scan_ms = scan_future.result()
                sampled_state, sampled_stamp, sampled_time = scan_snapshot
                pubs["points"].publish(cloud(points, LIDAR_FRAME, sampled_stamp))
                trail.append(sampled_state.position.copy())
                pubs["trail"].publish(path_message(trail, sampled_stamp))
                pubs["markers"].publish(vehicle_markers(sampled_stamp, sampled_time))
                pubs["speed"].publish(Float32(data=float(np.linalg.norm(sampled_state.velocity))))
                pubs["height"].publish(Float32(data=float(sampled_state.position[2])))
                scan_count, scan_future = len(points), None
            if now >= next_scan and scan_future is None:
                scan_snapshot = state, stamp, now
                scan_future = scanner.submit(sample_scan, state)
                next_scan = now+1/args.rate
            if now >= next_static:
                static.header.stamp = ros.stamp()
                pubs["static_tf"].publish(TFMessage(transforms=[static]))
                map_cloud.header.stamp = static.header.stamp
                pubs["map"].publish(map_cloud)
                pubs["route"].publish(path_message(patrol.points, static.header.stamp))
                next_static = now+5
            if now >= next_status:
                status = dict(mode=flight.mode, event=flight.last_event, elapsed=round(now, 1),
                              scan_points=scan_count, scan_ms=round(scan_ms, 1), scene=args.scene,
                              goal_topic=args.goal_topic, map_frame=MAP_FRAME)
                pubs["status"].publish(String(data=json.dumps(status)))
                print(json.dumps(status), flush=True)
                next_status = now+5
            time.sleep(.001)
    finally:
        scanner.shutdown(wait=True, cancel_futures=True)
        ros.close()
        print("Simulator stopped; publishers and subscribers released.", flush=True)


if __name__ == "__main__":
    main()
