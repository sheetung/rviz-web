"""Exercise the real ROS1 callback/drain without a ROS installation."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.config import Settings


@pytest.mark.asyncio
async def test_static_tf_replaces_parent_and_retains_latest(monkeypatch):
    subscriber = Mock(return_value=SimpleNamespace(unregister=Mock()))
    monkeypatch.setitem(sys.modules, "rospy", SimpleNamespace(Subscriber=subscriber))
    path = Path(__file__).resolve().parents[1] / "app/services/ros1/adapter.py"
    spec = importlib.util.spec_from_file_location(
        "app.services.ros1._static_tf_test_adapter", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_message_class", lambda _: SimpleNamespace)
    adapter = module.Ros1Adapter(Settings())
    adapter._converter = SimpleNamespace(
        to_dict=lambda msg: {
            "transforms": [
                (tf.header.frame_id, tf.child_frame_id, tf.x) for tf in msg.transforms
            ]
        }
    )
    delivered = asyncio.Queue()

    async def sink(topic, payload, kind):
        await delivered.put(payload)

    adapter.set_message_sink(sink)
    await adapter.subscribe_topic("/tf_static", "tf2_msgs/msg/TFMessage")
    callback = subscriber.call_args.args[2]

    def transform(parent, child, x):
        return SimpleNamespace(
            header=SimpleNamespace(frame_id=parent), child_frame_id=child, x=x
        )

    try:
        cases = [
            (
                [transform("map", "lidar", 1), transform("map", "camera", 2)],
                [("map", "lidar", 1), ("map", "camera", 2)],
            ),
            (
                [transform("map", "lidar", 3)],
                [("map", "lidar", 3), ("map", "camera", 2)],
            ),
            (
                [transform("odom", "lidar", 4)],
                [("odom", "lidar", 4), ("map", "camera", 2)],
            ),
            (
                [transform("map", "lidar", 5)],
                [("map", "lidar", 5), ("map", "camera", 2)],
            ),
        ]
        for updates, expected in cases:
            callback(SimpleNamespace(transforms=updates))
            payload = await asyncio.wait_for(delivered.get(), timeout=2)
            assert payload == {"transforms": expected}
            # RosApplication uses this snapshot to replay to new subscribers.
            assert adapter.get_retained_messages("/tf_static") == [payload]
    finally:
        await adapter.unsubscribe_topic("/tf_static")
    assert adapter.get_retained_messages("/tf_static") == []
    subscriber.return_value.unregister.assert_called_once()
