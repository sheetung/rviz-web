"""Live phase-3 control tests; run ONLY with an isolated ROS graph and control_fixture."""
import argparse
import asyncio
import copy
import json
import time
from pathlib import Path
import websockets

GOAL = 'geometry_msgs/msg/PoseStamped'
INITIAL = 'geometry_msgs/msg/PoseWithCovarianceStamped'
TWIST = 'geometry_msgs/msg/Twist'
POSE = {'header': {'frame_id': 'map', 'stamp': {'sec': 777, 'nanosec': 1234}},
        'pose': {'position': {'x': 1.25, 'y': -2.5, 'z': 3},
                 'orientation': {'x': 0, 'y': 0, 'z': 0, 'w': 1}}}

class Client:
    def __init__(self, socket):
        self.socket = socket
        self.responses = {}
    async def receive(self):
        event = json.loads(await asyncio.wait_for(self.socket.recv(), 5))
        if 'id' in event:
            self.responses[event['id']] = event
        return event
    async def send(self, method, request_id=None, **params):
        request_id = request_id or str(time.monotonic_ns())
        await self.socket.send(json.dumps(dict(version=2, id=request_id, method=method, params=params)))
        return request_id
    async def response(self, request_id):
        while request_id not in self.responses:
            await self.receive()
        return self.responses.pop(request_id)
    async def request(self, method, **params):
        return await self.response(await self.send(method, **params))

def records(capture):
    return [json.loads(line) for line in Path(capture).read_text().splitlines() if line.startswith('{')]

def messages(capture, topic):
    return [event['msg'] for event in records(capture) if event.get('topic') == topic]

async def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'Expected receiver condition not reached'
        await asyncio.sleep(.05)

async def run(url, middleware, capture, late_flag):
    async with websockets.connect(url, proxy=None) as socket:
        c = Client(socket)
        hello = await c.receive()
        assert hello['capabilities']['stage'] >= 3 and not hello['capabilities']['read_only']
        assert hello['capabilities']['middleware'] == middleware
        assert set(hello['capabilities']['publish_types']) == {GOAL,INITIAL,TWIST}
        denied = await c.request('topics.publish', topic='/forbidden', type=GOAL, msg=POSE)
        assert denied['error']['code'] == 'topic_not_allowed'
        invalid = copy.deepcopy(POSE); invalid['pose']['orientation']['w'] = 0
        assert (await c.request('topics.publish', topic='/v3_test/goal', type=GOAL, msg=invalid))['error']['code'] == 'invalid_request'
        assert (await c.request('session.stats'))['result']['publishers'] == 0
        assert (await c.request('topics.publish', topic='/v3_test/goal', type='nav_msgs/msg/Odometry', msg=POSE))['error']['code'] == 'unsupported_type'
        result = await c.request('topics.publish', request_id='goal-exact', topic='/v3_test/goal', type=GOAL, msg=POSE)
        assert result['ok'] and result['result'] == {'topic':'/v3_test/goal','status':'submitted','execution':'unknown'}, result
        await wait_for(lambda: len(messages(capture, '/v3_test/goal')) == 1)
        assert messages(capture, '/v3_test/goal')[0] == POSE
        # Same id and body returns its receipt without sending another ROS message.
        repeated = await c.request('topics.publish', request_id='goal-exact', topic='/v3_test/goal', type=GOAL, msg=POSE)
        assert repeated == result
        changed = copy.deepcopy(POSE); changed['pose']['position']['x'] = 100
        assert (await c.request('topics.publish', request_id='goal-exact', topic='/v3_test/goal', type=GOAL, msg=changed))['error']['code'] == 'request_id_conflict'
        await asyncio.sleep(.2)
        assert len(messages(capture, '/v3_test/goal')) == 1
        initial = {'header': POSE['header'], 'pose': {'pose': POSE['pose'], 'covariance': [0.25 if i % 7 == 0 else 0 for i in range(36)]}}
        assert (await c.request('topics.publish', topic='/v3_test/initialpose', type=INITIAL, msg=initial))['ok']
        await wait_for(lambda: len(messages(capture, '/v3_test/initialpose')) == 1)
        assert messages(capture, '/v3_test/initialpose')[0] == initial
        assert (await c.request('topics.advertise', topic='/v3_test/cmd_vel', type=TWIST))['ok']
        await asyncio.sleep(.5)
        twist = {'linear': {'x':.2, 'y':0, 'z':0}, 'angular': {'x':0, 'y':0, 'z':-.1}}
        assert (await c.request('topics.publish', topic='/v3_test/cmd_vel', type=TWIST, msg=twist))['ok']
        await wait_for(lambda: len(messages(capture, '/v3_test/cmd_vel')) == 1)
        assert messages(capture, '/v3_test/cmd_vel')[0] == twist
        # Missing timestamp uses the backend's ROS clock.
        unstamped = copy.deepcopy(POSE); del unstamped['header']['stamp']
        assert (await c.request('topics.publish', topic='/v3_test/goal', type=GOAL, msg=unstamped))['ok']
        await wait_for(lambda: len(messages(capture, '/v3_test/goal')) == 2)
        assert abs(messages(capture, '/v3_test/goal')[-1]['header']['stamp']['sec'] - time.time()) < 10
        # Discovery wait does not block ping or accept another command on the same topic.
        pending = await c.send('topics.publish', topic='/v3_test/absent', type=GOAL, msg=POSE)
        start = time.monotonic(); assert (await c.request('ping'))['ok']; assert time.monotonic() - start < .5
        assert (await c.request('topics.publish', topic='/v3_test/absent', type=GOAL, msg=POSE))['error']['code'] == 'publish_busy'
        assert (await c.response(pending))['error']['code'] == 'no_subscribers'
        cancelled = await c.send('topics.publish', topic='/v3_test/cancelled', type=GOAL, msg=POSE)
        assert (await c.request('topics.unadvertise', topic='/v3_test/cancelled'))['ok']
        assert (await c.response(cancelled))['error']['code'] == 'cancelled'
        # Publishers belong to their session; another client's unadvertise cannot revoke ours.
        async with websockets.connect(url, proxy=None) as second:
            d = Client(second); await d.receive()
            assert (await d.request('topics.advertise', topic='/v3_test/goal', type=GOAL))['ok']
            assert (await c.request('topics.unadvertise', topic='/v3_test/goal'))['ok']
            assert (await d.request('topics.publish', topic='/v3_test/goal', type=GOAL, msg=POSE))['ok']
            await wait_for(lambda: len(messages(capture, '/v3_test/goal')) == 3)
            assert (await d.request('session.stats'))['result']['publishers'] == 1
        # A pending command is discarded on disconnect, even if a receiver appears next.
        await c.send('topics.publish', topic='/v3_test/late', type=GOAL, msg=POSE)
        assert (await c.request('session.stats'))['result']['pending_publications'] == 1
    Path(late_flag).touch()
    await asyncio.sleep(2)
    assert messages(capture, '/v3_test/late') == []
    async with websockets.connect(url, proxy=None) as socket:
        c = Client(socket); await c.receive()
        stats = (await c.request('session.stats'))['result']
        assert stats['publishers'] == stats['pending_publications'] == stats['subscriptions'] == 0
        assert stats['connections'] == 1, stats
        assert len(messages(capture, '/v3_test/goal')) == 3
    await wait_for(lambda: [x for x in records(capture) if x.get('kind') == 'graph'][-1]['goal_publishers'] == 0)
    try:
        async with websockets.connect(url, proxy=None, origin='https://foreign.invalid'):
            raise AssertionError('Foreign origin accepted')
    except websockets.exceptions.InvalidStatus as e:
        assert e.response.status_code == 403
    print(f'{middleware}: exact goal/initial pose/velocity reception, ROS clock, policy, validation, dedup, async discovery, cancellation, isolation and resource release passed')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--middleware', required=True, choices=['ros1','ros2'])
    parser.add_argument('--capture', required=True)
    parser.add_argument('--late-flag', required=True)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args.url, args.middleware, args.capture, args.late_flag), 45))
