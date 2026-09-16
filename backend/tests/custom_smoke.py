"""ROS2 custom interface test: source tests/interfaces install before running."""
import asyncio
import json
import rclpy
from rvizweb_test_interfaces.msg import Telemetry
from display_smoke import Client
import websockets

async def run():
    rclpy.init()
    node = rclpy.create_node('rvizweb_custom_fixture')
    pub = node.create_publisher(Telemetry, '/v2_test/custom', 1)
    message = Telemetry(voltage=24.5, samples=[1.,2.,3.], flags=[True,False], label='自定义测试')
    message.velocity.x = -1.25
    try:
        async with websockets.connect('ws://127.0.0.1:18394/ws/v2/ros', proxy=None) as socket:
            client = Client(socket); await client.receive()
            result = await client.request('topics.subscribe', topic='/v2_test/custom', type='rvizweb_test_interfaces/msg/Telemetry')
            assert result['ok'], result
            for _ in range(20):
                pub.publish(message)
                await asyncio.sleep(.1)
            await client.collect(lambda e: '/v2_test/custom' in e)
            msg = client.events['/v2_test/custom']['msg']
            assert msg == {'voltage':24.5, 'velocity':{'x':-1.25,'y':0.,'z':0.},'samples':[1.,2.,3.],'flags':[True,False],'label':'自定义测试'}, msg
            print('ROS2 custom nested fields, variable arrays, bool sequence and UTF-8 passed')
    finally:
        node.destroy_node(); rclpy.shutdown()
asyncio.run(run())
