"""Compare stage-2 display payloads from v1/v2 for the same live fixture input."""
import argparse
import asyncio
import json
import math
import re
from pathlib import Path
import websockets
from display_smoke import TYPES

def clean(value):
    if isinstance(value, str) and re.fullmatch(r"array\('[A-Za-z]'\)", value):
        return []
    # v1 emits Python array repr for some ROS2 numeric sequences. Compare the
    # decoded values used by its frontend, without treating that encoding as v2's contract.
    if isinstance(value, str) and re.fullmatch(r"array\('[A-Za-z]', \[.*\]\)", value):
        data = value[value.index('['):-1]
        return json.loads(re.sub(r'-?\b(?:inf|nan)\b', 'null', data))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items() if k not in {"compressed", "data_encoding"}}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value

async def run(reference, url):
    expected = json.loads(Path(reference).read_text())
    topics = {t:v for t,v in TYPES.items() if t.startswith('/v2_test/') and t != '/v2_test/marker'}
    received = {}
    async with websockets.connect(url, proxy=None) as socket:
        for i, (topic, msg_type) in enumerate(topics.items()):
            await socket.send(json.dumps(dict(op='subscribe', id=str(i), topic=topic, type=msg_type)))
        while not set(topics) <= set(received):
            event = json.loads(await asyncio.wait_for(socket.recv(), 10))
            if event.get('op') == 'publish' and event.get('topic') in topics:
                received[event['topic']] = event['msg']
        for topic, message in received.items():
            assert clean(message) == clean(expected[topic]['msg']), (topic, message, expected[topic]['msg'])
    print('v1/v2 equivalent decoded values (legacy array strings normalized): LaserScan, Path, latched/volatile OccupancyGrid, MarkerArray, dynamic numeric array')
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', default='/tmp/stage2-ros2-events.json')
    parser.add_argument('--url', default='ws://127.0.0.1:18395/ws/ros2')
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args.reference, args.url), 40))
