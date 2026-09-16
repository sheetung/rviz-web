"""Isolated live ROS stage-2 verification. Start display_fixture and native service first."""
import argparse
import asyncio
import json
import time
import websockets

TYPES = {
    '/tf': 'tf2_msgs/msg/TFMessage', '/tf_static': 'tf2_msgs/msg/TFMessage',
    '/v2_test/scan': 'sensor_msgs/msg/LaserScan', '/v2_test/path': 'nav_msgs/msg/Path',
    '/v2_test/map': 'nav_msgs/msg/OccupancyGrid', '/v2_test/map_volatile': 'nav_msgs/msg/OccupancyGrid',
    '/v2_test/marker': 'visualization_msgs/msg/Marker', '/v2_test/markers': 'visualization_msgs/msg/MarkerArray',
    '/v2_test/numbers': 'std_msgs/msg/Float64MultiArray',
}

class Client:
    def __init__(self, socket):
        self.socket = socket
        self.events = {}

    async def receive(self):
        event = json.loads(await asyncio.wait_for(self.socket.recv(), 5))
        if 'topic' in event:
            self.events[event['topic']] = event
        return event

    async def request(self, method, **params):
        request_id = str(time.monotonic_ns())
        await self.socket.send(json.dumps(dict(version=2, id=request_id, method=method, params=params)))
        while True:
            event = await self.receive()
            if event.get('id') == request_id:
                return event

    async def collect(self, predicate):
        deadline = time.monotonic() + 15
        while not predicate(self.events):
            assert time.monotonic() < deadline, list(self.events)
            await self.receive()

async def run(url, middleware, output):
    async with websockets.connect(url, proxy=None, max_size=20*1024*1024) as socket:
        client = Client(socket)
        hello = await client.receive()
        assert hello['capabilities']['stage'] >= 2
        assert hello['capabilities']['dynamic_messages']
        assert hello['capabilities']['middleware'] == middleware
        if middleware == 'ros2':
            TYPES['/v2_test/map_best_effort'] = 'nav_msgs/msg/OccupancyGrid'
        if middleware == 'ros1':
            TYPES['/v2_test/custom'] = 'rvizweb_test_interfaces/msg/Telemetry'
        for topic, msg_type in TYPES.items():
            response = await client.request('topics.subscribe', topic=topic, type=msg_type)
            assert response['ok'], response
        await client.collect(lambda e: set(TYPES) <= set(e)
                             and len(e['/tf']['msg']['transforms']) == 2
                             and len(e['/tf_static']['msg']['transforms']) == 2
                             and len(e['/v2_test/marker']['display_snapshot']) == 3)
        e = client.events
        assert e['/v2_test/scan']['msg']['ranges'] == [1,2,None,None,3]
        assert e['/v2_test/scan']['msg']['intensities'] == [10,20,30,40,50]
        assert e['/v2_test/path']['msg']['poses'][1]['pose']['position']['x'] == 2
        for topic in ['/v2_test/map','/v2_test/map_volatile']:
            assert e[topic]['msg']['data'] == [-1,0,50,100]
            assert e[topic]['msg']['info']['resolution'] == 0.5
        if middleware == 'ros1':
            custom = e['/v2_test/custom']['msg']
            assert custom['voltage'] == 24.5 and custom['velocity']['x'] == -1.25
            assert custom['samples'] == [1,2,3] and custom['flags'] == [True,False]
            assert custom['label'] == '自定义测试'
        assert e['/v2_test/numbers']['msg']['data'] == [1.25,-2.5,42]
        assert e['/v2_test/numbers']['msg']['layout']['dim'][0]['label'] == 'voltage'
        assert e['/v2_test/markers']['display_snapshot'][0]['action'] == 3
        assert {t['child_frame_id'] for t in e['/tf_static']['msg']['transforms']} == {'static_a','static_b'}
        # Invalid QoS and changed QoS are rejected without replacing existing handles.
        assert not (await client.request('topics.subscribe', topic='/v2_test/scan', type=TYPES['/v2_test/scan'], durability='invalid'))['ok']
        if middleware == 'ros2':
            assert not (await client.request('topics.subscribe', topic='/v2_test/scan', type=TYPES['/v2_test/scan'], reliability='reliable'))['ok']
        if output:
            from pathlib import Path
            Path(output).write_text(json.dumps(e, indent=2))
        for topic in TYPES:
            assert (await client.request('topics.unsubscribe', topic=topic))['ok']
        assert (await client.request('session.stats'))['result']['subscriptions'] == 0
    # Reconnect and get static transforms immediately; the fixture publishes static TF only once.
    async with websockets.connect(url, proxy=None) as socket:
        client = Client(socket); await client.receive()
        assert (await client.request('topics.subscribe', topic='/tf_static', type=TYPES['/tf_static']))['ok']
        await client.collect(lambda e: '/tf_static' in e)
        assert len(client.events['/tf_static']['msg']['transforms']) == 2
    print(f'{middleware}: all stage-2 displays, dynamic fields, static TF replay, QoS and unsubscribe passed')

async def replay_only(url):
    async with websockets.connect(url, proxy=None) as socket:
        client = Client(socket); await client.receive()
        assert (await client.request('topics.subscribe', topic='/tf_static', type=TYPES['/tf_static']))['ok']
        await client.collect(lambda e: '/tf_static' in e)
        assert {t['child_frame_id'] for t in client.events['/tf_static']['msg']['transforms']} == {'static_a','static_b'}
    print('Static TF replay after all publishers exited passed')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='ws://127.0.0.1:18392/ws/v2/ros')
    parser.add_argument('--middleware', choices=['ros1','ros2'], required=True)
    parser.add_argument('--output')
    parser.add_argument('--replay-only', action='store_true')
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for((replay_only(args.url) if args.replay_only else run(args.url, args.middleware, args.output)), 45))
