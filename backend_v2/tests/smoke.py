"""End-to-end read-only checks against a running native service and ros_fixture.

Run in an isolated ROS_DOMAIN_ID (ROS2) or a dedicated ROS Master (ROS1).
"""
import argparse
import asyncio
import json
import struct
import time
import urllib.request

import websockets


async def receive(socket, timeout=5):
    return await asyncio.wait_for(socket.recv(), timeout)


async def request(socket, method, **params):
    request_id = str(time.monotonic_ns())
    await socket.send(json.dumps({"version": 2, "id": request_id, "method": method, "params": params}))
    while True:
        message = await receive(socket)
        if isinstance(message, bytes):
            continue
        response = json.loads(message)
        if response.get("id") == request_id:
            return response


def decode(frame):
    assert frame[:4] == b"RVPC" and frame[4] == 1
    length = struct.unpack_from("<I", frame, 8)[0]
    metadata = json.loads(frame[12:12 + length])
    offset = (12 + length + 3) & ~3
    assert metadata["version"] == 2
    assert metadata["msg"]["point_step"] == 16
    assert metadata["msg"]["row_step"] == 40
    assert metadata["msg"]["header"] == {"frame_id": "map", "stamp": {"sec": 777, "nanosec": 1234}}
    assert [f["name"] for f in metadata["msg"]["fields"]] == ["x", "y", "z", "intensity"]
    assert frame[offset:] == struct.pack("<8f", 1, 2, 3, 42, 4, 5, 6, 84) + b"\xa5" * 8
    return metadata


async def wait_cloud(socket):
    while True:
        message = await receive(socket)
        if isinstance(message, bytes):
            return decode(message)


async def run(url, middleware, denied_topic=None):
    endpoint = url.replace("ws://", "http://").replace("wss://", "https://").replace("/ws/v2/ros", "/api/v2/ros/health")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(endpoint, timeout=3) as response:
        assert json.load(response)["middleware"] == middleware
    async with websockets.connect(url, proxy=None, max_size=20 * 1024 * 1024) as first:
        hello = json.loads(await receive(first))
        assert hello["event"] == "hello" and hello["capabilities"]["stage"] >= 1
        assert hello["capabilities"]["protocol_version"] == 2
        assert hello["capabilities"]["middleware"] == middleware
        if denied_topic:
            denied = await request(first, "topics.subscribe", topic=denied_topic, type="nav_msgs/msg/Odometry")
            assert not denied["ok"] and denied["error"]["code"] == "topic_not_allowed"
            assert (await request(first, "session.stats"))["result"]["subscriptions"] == 0
        topics = []
        for _ in range(30):
            result = await request(first, "topics.list")
            assert result["ok"], result
            topics = result["result"]["topics"]
            if {"/v2_test/points", "/v2_test/odom"} <= {topic["name"] for topic in topics}:
                break
            await asyncio.sleep(0.2)
        assert {"/v2_test/points", "/v2_test/odom"} <= {topic["name"] for topic in topics}, topics
        assert (await request(first, "topics.subscribe", topic="/v2_test/points", type="sensor_msgs/msg/PointCloud2"))["ok"]
        assert (await request(first, "topics.subscribe", topic="/v2_test/odom", type="nav_msgs/msg/Odometry"))["ok"]
        await wait_cloud(first)
        for _ in range(60):
            message = await receive(first)
            if isinstance(message, str):
                event = json.loads(message)
                if event.get("topic") == "/v2_test/odom":
                    assert event["msg"]["pose"]["pose"]["position"] == {"x": 1.25, "y": -2.5, "z": 3.0}
                    assert len(event["msg"]["pose"]["covariance"]) == 36
                    break
        else:
            raise AssertionError("No odometry message")
        start = time.monotonic()
        assert (await request(first, "ping"))["ok"]
        assert time.monotonic() - start < 2
        assert (await request(first, "topics.publish", topic="/goal_pose"))["error"]["code"] == "unsupported_type"
        assert (await request(first, "topics.subscribe", topic="/tf", type="invalid"))["error"]["code"] == "unsupported_type"
        # Separate clients retain independent subscription ownership.
        async with websockets.connect(url, proxy=None) as second:
            await receive(second)
            assert (await request(second, "topics.subscribe", topic="/v2_test/points", type="sensor_msgs/msg/PointCloud2"))["ok"]
            await wait_cloud(second)
            assert (await request(first, "topics.unsubscribe", topic="/v2_test/points"))["ok"]
            await wait_cloud(second)
            assert (await request(first, "session.stats"))["result"]["subscriptions"] == 1
            # A cancelled stream cannot reappear after its acknowledgement.
            for _ in range(5):
                assert isinstance(await receive(first), str)
        assert (await request(first, "topics.unsubscribe", topic="/v2_test/odom"))["ok"]
        assert (await request(first, "session.stats"))["result"]["subscriptions"] == 0
    async with websockets.connect(url, proxy=None) as fresh:
        await receive(fresh)
        assert (await request(fresh, "session.stats"))["result"]["subscriptions"] == 0
    try:
        async with websockets.connect(url, proxy=None, origin="https://untrusted.invalid"):
            raise AssertionError("Foreign Origin accepted")
    except websockets.exceptions.InvalidStatus as error:
        assert error.response.status_code == 403
    print(f"{middleware}: discovery, exact PointCloud2 bytes/metadata, odometry, acknowledgements, isolation, reconnect and Origin checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8082/ws/v2/ros")
    parser.add_argument("--middleware", required=True, choices=["ros1", "ros2"])
    parser.add_argument("--denied-topic", help="Optional topic excluded by the server allowlist")
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args.url, args.middleware, args.denied_topic), timeout=45))
