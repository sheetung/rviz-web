#!/usr/bin/env python3
"""Publish a synthetic ROS1 PointCloud2 scene without a lidar or bag file."""
import argparse
import math
import time

import numpy as np


def scene():
    x, y = np.meshgrid(np.linspace(-6, 6, 101), np.linspace(-6, 6, 101))
    floor = np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size)))
    angle, height = np.meshgrid(np.linspace(0, 2 * math.pi, 60), np.linspace(0, 2.5, 30))
    pillars = [np.column_stack((cx + 0.35 * np.cos(angle.ravel()),
                               cy + 0.35 * np.sin(angle.ravel()), height.ravel()))
               for cx, cy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]]
    longitude, latitude = np.meshgrid(np.linspace(0, 2 * math.pi, 80), np.linspace(0, math.pi, 40))
    sphere = np.column_stack((
        0.7 * np.sin(latitude.ravel()) * np.cos(longitude.ravel()),
        0.7 * np.sin(latitude.ravel()) * np.sin(longitude.ravel()),
        1.2 + 0.7 * np.cos(latitude.ravel()),
    ))
    return np.concatenate([floor, *pillars, sphere]).astype('<f4')


def lidar_pose(elapsed):
    angle = elapsed * 0.2
    return np.array([2 * math.cos(angle), 2 * math.sin(angle), 1.2]), angle + math.pi / 2


def scan(world, position, yaw, max_range):
    """Approximate a 32-channel lidar by retaining the closest surface sample per ray."""
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    local = (world - position) @ rotation
    ranges = np.linalg.norm(local, axis=1)
    elevation = np.arctan2(local[:, 2], np.linalg.norm(local[:, :2], axis=1))
    visible = (ranges > 0.15) & (ranges <= max_range) & (elevation >= np.deg2rad(-30)) & (elevation <= np.deg2rad(15))
    local, ranges, elevation = local[visible], ranges[visible], elevation[visible]
    if not len(local):
        return np.empty((0, 3), dtype='<f4')
    azimuth = np.arctan2(local[:, 1], local[:, 0])
    columns = (np.floor((azimuth + math.pi) / (2 * math.pi) * 720).astype(int) % 720)
    rows = np.clip(np.floor((elevation - np.deg2rad(-30)) / np.deg2rad(45) * 32).astype(int), 0, 31)
    rays = rows * 720 + columns
    order = np.lexsort((ranges, rays))
    nearest = order[np.r_[True, np.diff(rays[order]) != 0]]
    return local[nearest].astype('<f4')


def main():
    import rospy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import PointCloud2, PointField
    from std_msgs.msg import Header
    from tf2_msgs.msg import TFMessage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', default='/demo/points')
    parser.add_argument('--odom-topic', default='/demo/odom')
    parser.add_argument('--frame', default='map', help='World / odometry parent frame')
    parser.add_argument('--sensor-frame', default='demo_lidar')
    parser.add_argument('--range', type=float, default=8, dest='max_range')
    parser.add_argument('--rate', type=float, default=5)
    parser.add_argument('--duration', type=float, default=0, help='Seconds; 0 runs until Ctrl+C')
    args = parser.parse_args()
    if not math.isfinite(args.rate) or not 0 < args.rate <= 30:
        parser.error('--rate must be between 0 (exclusive) and 30 Hz')
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error('--duration must be nonnegative')
    if not math.isfinite(args.max_range) or args.max_range <= 0.15:
        parser.error('--range must exceed 0.15 meters')
    if not args.frame or not args.sensor_frame or args.frame == args.sensor_frame:
        parser.error('World and sensor frames must be nonempty and different')
    rospy.init_node('rvizweb_demo_pointcloud', anonymous=True)
    publisher = rospy.Publisher(args.topic, PointCloud2, queue_size=1)
    odom_publisher = rospy.Publisher(args.odom_topic, Odometry, queue_size=1)
    tf_publisher = rospy.Publisher('/tf', TFMessage, queue_size=1)
    fields = [PointField(name=name, offset=index * 4, datatype=PointField.FLOAT32, count=1)
              for index, name in enumerate(('x', 'y', 'z'))]
    world = scene()
    started = time.monotonic()
    print(f'Publishing moving lidar at {args.rate:g} Hz: {args.topic} + {args.odom_topic}', flush=True)
    print(f'TF: {args.frame} -> {args.sensor_frame}; Fixed Frame={args.frame}. Ctrl+C stops the demo.', flush=True)
    while not rospy.is_shutdown():
        elapsed = time.monotonic() - started
        if args.duration and elapsed >= args.duration:
            break
        position, yaw = lidar_pose(elapsed)
        points = scan(world, position, yaw, args.max_range)
        stamp = rospy.Time.now()
        odom = Odometry(header=Header(stamp=stamp, frame_id=args.frame), child_frame_id=args.sensor_frame)
        odom.pose.pose.position.x, odom.pose.pose.position.y, odom.pose.pose.position.z = map(float, position)
        odom.pose.pose.orientation.z = math.sin(yaw / 2)
        odom.pose.pose.orientation.w = math.cos(yaw / 2)
        odom.twist.twist.linear.x = 0.4
        odom.twist.twist.angular.z = 0.2
        transform = TransformStamped(header=odom.header, child_frame_id=args.sensor_frame)
        transform.transform.translation.x = float(position[0])
        transform.transform.translation.y = float(position[1])
        transform.transform.translation.z = float(position[2])
        transform.transform.rotation = odom.pose.pose.orientation
        tf_publisher.publish(TFMessage(transforms=[transform]))
        odom_publisher.publish(odom)
        publisher.publish(PointCloud2(
            header=Header(stamp=stamp, frame_id=args.sensor_frame),
            height=1, width=len(points), fields=fields, is_bigendian=False,
            point_step=12, row_step=len(points) * 12,
            data=points.tobytes(), is_dense=True,
        ))
        # Wall time also works when a ROS bag enables /use_sim_time but is paused.
        time.sleep(1 / args.rate)


if __name__ == '__main__':
    import rospy
    try:
        main()
    except (KeyboardInterrupt, rospy.ROSInterruptException):
        pass
