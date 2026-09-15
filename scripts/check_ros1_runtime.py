#!/usr/bin/env python3
"""Native ROS1 + HTTP/WebSocket integration. Requires isolated ROS1 PYTHONPATH.

Runs a private Master on 11391 and backend on 18081, localhost only.
Do not run in a sourced ROS2 environment. No robot/master is contacted.
"""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time

os.environ.update(
    ROS_VERSION="1",
    ROS_MASTER_URI="http://127.0.0.1:11391",
    ROS_IP="127.0.0.1",
    ROS_HOSTNAME="127.0.0.1",
    DEBUG="false",
)
root = Path(__file__).resolve().parents[1]
os.environ["ROS_LOG_DIR"] = str(root / "local_data/ros1_runtime/logs")
sys.path.insert(0, str(root / "backend"))

import rospy  # noqa: E402
from rosmaster.master import Master  # noqa: E402
from geometry_msgs.msg import TransformStamped, Twist  # noqa: E402
from sensor_msgs.msg import PointCloud2, PointField  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from std_srvs.srv import Trigger, TriggerResponse  # noqa: E402
from tf2_msgs.msg import TFMessage  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402
import urllib.request  # noqa: E402
import urllib.error  # noqa: E402


async def receive(ws, predicate):
    async def read():
        while True:
            raw = await ws.recv()
            msg = raw if isinstance(raw, bytes) else json.loads(raw)
            if predicate(msg):
                return msg

    return await asyncio.wait_for(read(), 8)


async def request(ws, op, **kwargs):
    await ws.send(json.dumps(dict(op=op, id=op, **kwargs)))
    return await receive(ws, lambda m: isinstance(m, dict) and m.get("id") == op)


async def main():
    for port in (11391, 18081):
        with socket.socket() as check:
            check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            check.bind(("127.0.0.1", port))
    master = Master(11391)
    master.start()
    from app.main import app
    from app.services.dependencies import get_ros_service

    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=18081, ws="websockets", log_level="warning"
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                raise RuntimeError("Backend failed startup")
            await asyncio.sleep(0.05)
        assert server.started
        service = get_ros_service()
        assert service.middleware == "ros1"
        from visualization_msgs.msg import MarkerArray
        from sensor_msgs.msg import Image
        from genpy.dynamic import generate_dynamic

        converter = service.adapter._converter
        markers = converter.from_dict(
            MarkerArray, {"markers": [{"id": 7, "points": [{"x": 1.0}]}]}
        )
        assert converter.to_dict(markers)["markers"][0]["points"][0]["x"] == 1.0
        custom = generate_dynamic(
            "rvizweb_test/Sample", "int64 counter\nbool enabled\nfloat32[] values\n"
        )["rvizweb_test/Sample"]
        obj = converter.from_dict(
            custom, {"counter": 2**60, "enabled": True, "values": [1.5, 2.5]}
        )
        assert converter.to_dict(obj) == {
            "counter": 2**60,
            "enabled": True,
            "values": [1.5, 2.5],
        }
        assert converter.to_dict(Image(data=b"abc"))["data"] == "YWJj"
        cloud_pub = rospy.Publisher("/test/cloud", PointCloud2, queue_size=1)
        latch_pub = rospy.Publisher("/test/latched", String, latch=True, queue_size=1)
        tf_pub = rospy.Publisher("/tf_static", TFMessage, latch=True, queue_size=1)
        trigger = rospy.Service(
            "/test/trigger", Trigger, lambda _: TriggerResponse(True, "ok")
        )
        received = []
        cmd_sub = rospy.Subscriber("/cmd_vel", Twist, received.append)

        def get(path):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(
                    "http://127.0.0.1:18081" + path, timeout=5
                ) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, None

        assert (await asyncio.to_thread(get, "/ros2/api/v1/version"))[0] == 409
        assert (await asyncio.to_thread(get, "/ros1/api/v1/version"))[1][
            "middleware"
        ] == "ros1"
        async with websockets.connect(
            "ws://127.0.0.1:18081/ws/ros2", proxy=None
        ) as wrong:
            assert json.loads(await wrong.recv())["code"] == "middleware_mismatch"
        async with websockets.connect("ws://127.0.0.1:18081/ws/ros1", proxy=None) as ws:
            assert (await request(ws, "ping"))["op"] == "pong"
            assert (
                await request(
                    ws, "subscribe", topic="/test/cloud", type="sensor_msgs/PointCloud2"
                )
            )["success"]
            cloud = PointCloud2(
                height=1,
                width=1,
                point_step=12,
                row_step=12,
                is_dense=True,
                fields=[
                    PointField(n, i * 4, 7, 1) for i, n in enumerate(("x", "y", "z"))
                ],
                data=b"\x00" * 12,
            )
            cloud.header.frame_id = "map"
            await asyncio.sleep(0.3)
            cloud_pub.publish(cloud)
            frame = await receive(ws, lambda m: isinstance(m, bytes))
            assert frame[:4] == b"RVPC"
            if len(sys.argv) > 1:
                from rosbags.rosbag1 import Reader

                assert (
                    await request(
                        ws,
                        "subscribe",
                        topic="/test/bag_points",
                        type="sensor_msgs/PointCloud2",
                    )
                )["success"]
                bag_pub = rospy.Publisher("/test/bag_points", PointCloud2, queue_size=1)
                await asyncio.sleep(0.3)

                def replay():
                    count = 0
                    with Reader(Path(sys.argv[1])) as bag:
                        connections = [
                            c
                            for c in bag.connections
                            if c.topic == "/mid360/livox/lidar"
                        ]
                        for _, _, raw in bag.messages(connections=connections):
                            bag_pub.publish(PointCloud2().deserialize(raw))
                            count += 1
                            time.sleep(0.0125)
                            if count == 120:
                                break
                    return count

                playback = asyncio.create_task(asyncio.to_thread(replay))
                binary_frames = 0
                while not playback.done():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 0.2)
                        if isinstance(raw, bytes):
                            assert raw[:4] == b"RVPC"
                            binary_frames += 1
                    except asyncio.TimeoutError:
                        pass
                assert await playback == 120 and binary_frames > 0
                print(
                    f"PASS original ROS1 bag: 120 Mid360 scans at ~8x input, {binary_frames} binary snapshots"
                )
                bag_pub.unregister()
            for topic, kind in [
                ("/test/latched", "std_msgs/String"),
                ("/tf_static", "tf2_msgs/TFMessage"),
            ]:
                assert (await request(ws, "subscribe", topic=topic, type=kind))[
                    "success"
                ]
            await asyncio.sleep(0.3)
            latch_pub.publish(String("retained"))
            for child in ("lidar", "camera"):
                tf = TransformStamped(child_frame_id=child)
                tf.header.frame_id = "map"
                tf.transform.rotation.w = 1
                tf_pub.publish(TFMessage([tf]))
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.2)
            async with websockets.connect(
                "ws://127.0.0.1:18081/ws", proxy=None
            ) as second:
                # Retained data may precede subscribe_result; inspect both.
                for topic, kind in [
                    ("/test/latched", "std_msgs/String"),
                    ("/tf_static", "tf2_msgs/TFMessage"),
                ]:
                    await second.send(
                        json.dumps(
                            dict(op="subscribe", id="sub", topic=topic, type=kind)
                        )
                    )
                    msg = await receive(
                        second,
                        lambda m: isinstance(m, dict) and m.get("op") == "publish",
                    )
                    if topic == "/tf_static":
                        assert {
                            t["child_frame_id"] for t in msg["msg"]["transforms"]
                        } == {"lidar", "camera"}
                    else:
                        assert msg["msg"]["data"] == "retained"
            assert (
                await request(
                    ws, "advertise", topic="/cmd_vel", type="geometry_msgs/Twist"
                )
            )["success"]
            await asyncio.sleep(0.3)
            assert (
                await request(
                    ws, "publish", topic="/cmd_vel", msg={"linear": {"x": 0.25}}
                )
            )["success"]
            await asyncio.sleep(0.2)
            assert received and received[-1].linear.x == 0.25
            types = await service.get_service_types()
            assert types["/test/trigger"] == "std_srvs/Trigger"
            assert (await request(ws, "unsubscribe", topic="/test/cloud"))["success"]
            assert "/test/cloud" not in service.adapter._subscriptions
        await asyncio.sleep(0.2)
        assert not service.adapter._subscriptions
        assert not service.adapter._publishers
        cmd_sub.unregister()
        trigger.shutdown()
        print(
            "PASS ROS1: factory, Master graph, binary cloud, native publish, "
            "shared latch/static TF, WS/API version routing, cleanup"
        )
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        master.stop()


if __name__ == "__main__":
    asyncio.run(main())
