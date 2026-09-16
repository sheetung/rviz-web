"""ROS2 isolated live checks. Owns all child processes; never uses project .env.

source /opt/ros/humble/setup.bash
backend/.venv/bin/python backend_v2/tests/stage5_smoke.py --duration 180
Use --duration 3600 for an hour-long simulator/multi-client soak.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import time
import urllib.request

import psutil
import websockets

ROOT = Path(__file__).resolve().parents[2]
CHILDREN = []
LOGS = []
PORT = 18752
URL = f'ws://127.0.0.1:{PORT}/ws/v2/ros'
HTTP = f'http://127.0.0.1:{PORT}/api/v2/ros'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(path):
    with OPENER.open(f'{HTTP}/{path}', timeout=3) as response:
        return json.load(response)


def start(name, args, env):
    log = open(f'/tmp/rviz-stage5-{name}.log', 'w')
    LOGS.append(log)
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    CHILDREN.append(process)
    return process


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


async def ready(process):
    for _ in range(100):
        assert process.poll() is None, 'Native process exited; see /tmp/rviz-stage5-*.log'
        try:
            if http('health')['ready']:
                return
        except OSError:
            pass
        await asyncio.sleep(.1)
    raise AssertionError('Native service did not become ready')


async def connect():
    ws = await websockets.connect(URL, proxy=None, max_size=20*1024*1024, max_queue=1)
    assert json.loads(await ws.recv())['capabilities']['stage'] == 5
    return ws


async def request(ws, method, **params):
    rid = str(time.monotonic_ns())
    await ws.send(json.dumps(dict(version=2, id=rid, method=method, params=params)))
    while True:
        frame = await asyncio.wait_for(ws.recv(), 5)
        if isinstance(frame, str):
            event = json.loads(frame)
            if event.get('id') == rid:
                assert event['ok'], event
                return event['result']


async def subscribe(ws, topic, kind='sensor_msgs/msg/PointCloud2'):
    return await request(ws, 'topics.subscribe', topic=topic, type=kind)


async def cloud(ws):
    while True:
        frame = await asyncio.wait_for(ws.recv(), 5)
        if isinstance(frame, bytes):
            n = struct.unpack_from('<I', frame, 8)[0]
            return json.loads(frame[12:12+n]), frame[(12+n+3)&~3:]


async def run(args):
    # Do not inherit a real robot's domain or processing settings.
    env = {k:v for k,v in os.environ.items() if not k.startswith('RVIZWEB_POINTCLOUD_')}
    env.update(ROS_DOMAIN_ID='197', ROS_LOCALHOST_ONLY='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    os.environ.update(ROS_DOMAIN_ID='197', ROS_LOCALHOST_ONLY='1')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", PORT))  # Refuse an occupied test port.
    native_path = str(ROOT/'backend_v2/build/ros2/rvizweb_native')
    native = start('native', [native_path, '--port', str(PORT)], env)
    await ready(native)
    fixture = start('fixture', [str(ROOT/'backend_v2/build/ros2/ros_fixture')], env)
    # Existing byte-fidelity, control, unsubscribe and origin checks.
    smoke = start('baseline', [str(ROOT/'backend/.venv/bin/python'), 'backend_v2/tests/smoke.py', '--url', URL, '--middleware', 'ros2'], env)
    deadline = time.monotonic()+60
    while smoke.poll() is None:
        assert time.monotonic()<deadline, 'Baseline smoke timed out'
        await asyncio.sleep(.1)
    assert smoke.returncode == 0, 'Baseline smoke failed'
    first, second = await connect(), await connect()
    await subscribe(first, '/v2_test/points')
    await cloud(first)
    await subscribe(second, '/v2_test/points')
    await cloud(second)
    streams = http('metrics')['streams']
    assert len(streams) == 1 and streams[0]['clients'] == 2, streams
    import rclpy
    from sensor_msgs.msg import PointCloud2, PointField
    rclpy.init()
    node = rclpy.create_node('rvizweb_stage5_observer')
    for _ in range(30):
        rclpy.spin_once(node, timeout_sec=.05)
        if node.count_subscribers('/v2_test/points') == 1:
            break
    assert node.count_subscribers('/v2_test/points') == 1, 'Duplicate DDS subscriptions'
    await first.close()
    await cloud(second)
    await second.close()
    # A malformed sample emits a bounded error and a valid subsequent sample recovers.
    publisher = node.create_publisher(PointCloud2, '/v2_test/invalid', 1)
    client = await connect()
    await subscribe(client, '/v2_test/invalid')
    bad = PointCloud2(height=1, width=1, point_step=12, row_step=12, data=b'x')
    good = PointCloud2(height=1, width=1, point_step=12, row_step=12, data=bytes(12))
    good.fields = [PointField(name=n, offset=i*4, datatype=7, count=1) for i,n in enumerate('xyz')]
    for _ in range(30):
        rclpy.spin_once(node, timeout_sec=.05)
        if publisher.get_subscription_count():
            break
    publisher.publish(bad)
    event = json.loads(await asyncio.wait_for(client.recv(), 5))
    assert event['event'] == 'topic.error' and event['error']['code'] == 'conversion_failed'
    publisher.publish(good)
    await cloud(client)
    assert http('metrics')['streams'][0]['conversion_errors'] == 1
    await client.close()
    node.destroy_node()
    rclpy.shutdown()
    stop(fixture)
    stop(native)
    # Explicit filtering and rate limiting, retaining intensity and original timestamp.
    filtered_env = dict(env, RVIZWEB_POINTCLOUD_MAX_HZ='2', RVIZWEB_POINTCLOUD_VOXEL_SIZE='1',
                        RVIZWEB_POINTCLOUD_CROP='0,0,0,3,3,3', RVIZWEB_POINTCLOUD_TOPICS='/v2_test/points')
    native = start('filtered', [native_path, '--port', str(PORT)], filtered_env)
    await ready(native)
    fixture = start('fixture-filtered', [str(ROOT/'backend_v2/build/ros2/ros_fixture')], env)
    client = await connect()
    await subscribe(client, '/v2_test/points')
    metadata, data = await cloud(client)
    assert metadata['msg']['width'] == 1 and metadata['msg']['row_step'] == 16
    assert data == struct.pack('<4f', 1,2,3,42)
    assert metadata['msg']['header']['stamp'] == {'sec':777, 'nanosec':1234}
    await asyncio.sleep(2)
    metrics = http('metrics')['streams'][0]
    assert metrics['throttled'] > 0 and metrics['encoded'] <= 6, metrics
    await client.close()
    stop(fixture)
    stop(native)
    # Actual map simulation: three reading clients and one deliberately stalled socket.
    native = start('soak-native', [native_path, '--port', str(PORT)], env)
    await ready(native)
    simulator = start('simulator', [str(ROOT/'backend/.venv/bin/python'), 'scripts/simulate_uav.py', '--no-config'], env)
    clients = [await connect() for _ in range(3)]
    for ws in clients:
        await subscribe(ws, '/sim/uav/points')
        await subscribe(ws, '/sim/uav/odom', 'nav_msgs/msg/Odometry')
    slow = await connect()
    slow.transport.get_extra_info('socket').setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    await subscribe(slow, '/sim/uav/points')
    counts = [0]*3
    async def reader(index):
        async for frame in clients[index]:
            if isinstance(frame, bytes):
                counts[index] += 1
    tasks = [asyncio.create_task(reader(i)) for i in range(3)]
    observer = await connect()
    memory, pings = [], []
    started = time.monotonic()
    while time.monotonic()-started < args.duration:
        assert native.poll() is None and simulator.poll() is None
        assert all(not task.done() for task in tasks)
        memory.append(psutil.Process(native.pid).memory_info().rss)
        t = time.monotonic()
        await request(observer, 'ping')
        pings.append((time.monotonic()-t)*1000)
        await asyncio.sleep(1)
    metrics = http('metrics')
    points = next(s for s in metrics['streams'] if s['topic']=='/sim/uav/points')
    assert len(metrics['streams']) == 2 and points['clients'] in (3,4), metrics
    assert all(n > args.duration*3 for n in counts), counts
    assert points['conversion_errors'] == 0 and max(pings) < 2000, metrics
    report = dict(duration_seconds=args.duration, fast_client_clouds=counts, shared_streams=metrics,
                  rss_min_mb=min(memory)/2**20, rss_max_mb=max(memory)/2**20,
                  ping_max_ms=max(pings), ping_p95_ms=sorted(pings)[int(.95*(len(pings)-1))],
                  dds_subscription_count_verified=1, baseline_passed=True, error_recovery_passed=True,
                  filtering_passed=True, rate_limit_passed=True)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for ws in clients+[observer]:
        await ws.close()
    slow.transport.abort()
    await asyncio.sleep(.5)
    assert http('metrics')['shared_streams'] == 0, 'Stream leak after disconnect'
    report['all_streams_released'] = True
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=180)
    parser.add_argument('--output', default='/tmp/rviz-stage5-results.json')
    args = parser.parse_args()
    if args.duration < 10:
        parser.error('duration must be at least 10 seconds')
    try:
        asyncio.run(run(args))
    finally:
        for process in reversed(CHILDREN):
            stop(process)
        for log in LOGS:
            log.close()
