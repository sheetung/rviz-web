import asyncio
import json
from collections import OrderedDict
from datetime import datetime
from unittest.mock import AsyncMock
import pytest

from app.models.ros import ConnectionInfo
from app.services.connection_manager import ConnectionManager, _serialize_json_message


@pytest.mark.asyncio
async def test_slow_client_close_preserves_ownership_until_service_cleanup():
    manager = ConnectionManager(outbound_queue_size=1, send_timeout=0.01)
    websocket = AsyncMock()
    manager.active_connections["client-1"] = websocket
    manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        subscribed_topics=["/scan"],
        advertised_topics={"/goal_pose": "geometry_msgs/msg/PoseStamped"},
    )
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("already full")
    manager._send_queues["client-1"] = queue

    assert not await manager.send_to_client("client-1", {"op": "pong"})

    websocket.close.assert_awaited_once_with(
        code=1011,
        reason="Outbound queue timeout",
    )
    assert "client-1" in manager.connection_info
    assert manager.connection_info["client-1"].subscribed_topics == ["/scan"]


def test_websocket_json_replaces_non_finite_numbers_with_null():
    message_text = _serialize_json_message(
        {
            "op": "publish",
            "topic": "/fmu/out/vehicle_local_position",
            "msg": {
                "x": -0.003,
                "vxy_max": float("inf"),
                "ref_lat": float("nan"),
            },
        }
    )

    assert "NaN" not in message_text
    assert "Infinity" not in message_text
    assert json.loads(message_text)["msg"] == {
        "x": -0.003,
        "vxy_max": None,
        "ref_lat": None,
    }


@pytest.mark.asyncio
async def test_replaceable_topic_broadcast_keeps_only_latest_pending_update():
    manager = ConnectionManager()
    manager.active_connections["client-1"] = AsyncMock()
    manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        subscribed_topics=["/points"],
    )
    manager._send_queues["client-1"] = asyncio.Queue(maxsize=2)
    manager._ordered_topic_queues["client-1"] = asyncio.Queue(maxsize=2)
    manager._latest_topic_messages["client-1"] = OrderedDict()
    manager._sender_events["client-1"] = asyncio.Event()

    await manager.broadcast(
        {"op": "publish", "topic": "/points", "msg": {"sequence": 1}}
    )
    await manager.broadcast(
        {"op": "publish", "topic": "/points", "msg": {"sequence": 2}}
    )

    pending = manager._latest_topic_messages["client-1"]
    assert list(pending) == ["/points"]
    assert pending["/points"]["msg"]["sequence"] == 2
    assert manager._send_queues["client-1"].empty()
    assert manager._sender_events["client-1"].is_set()


@pytest.mark.asyncio
async def test_delta_topic_broadcast_preserves_message_order(monkeypatch):
    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    manager = ConnectionManager(outbound_queue_size=2)
    manager.active_connections["client-1"] = AsyncMock()
    manager.connection_info["client-1"] = ConnectionInfo(
        client_id="client-1",
        connected_at=datetime.now(),
        subscribed_topics=["/markers"],
    )
    manager._send_queues["client-1"] = asyncio.Queue(maxsize=2)
    manager._ordered_topic_queues["client-1"] = asyncio.Queue(maxsize=2)
    manager._latest_topic_messages["client-1"] = OrderedDict()
    manager._sender_events["client-1"] = asyncio.Event()

    await manager.broadcast(
        {"op": "publish", "topic": "/markers", "msg": {"action": "ADD"}},
        coalesce_topic=False,
    )
    await manager.broadcast(
        {"op": "publish", "topic": "/markers", "msg": {"action": "DELETE"}},
        coalesce_topic=False,
    )

    queue = manager._ordered_topic_queues["client-1"]
    assert json.loads(queue.get_nowait())["msg"]["action"] == "ADD"
    assert json.loads(queue.get_nowait())["msg"]["action"] == "DELETE"
    assert manager._send_queues["client-1"].empty()
    assert manager._latest_topic_messages["client-1"] == {}


@pytest.mark.asyncio
async def test_slow_sender_skips_intermediate_replaceable_frames(monkeypatch):
    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)
    manager = ConnectionManager()
    websocket = AsyncMock()
    first_send_started = asyncio.Event()
    release_first_send = asyncio.Event()
    latest_send_finished = asyncio.Event()
    sent_sequences = []

    async def send_text(message_text):
        sequence = json.loads(message_text)["msg"]["sequence"]
        sent_sequences.append(sequence)
        if len(sent_sequences) == 1:
            first_send_started.set()
            await release_first_send.wait()
        else:
            latest_send_finished.set()

    websocket.send_text.side_effect = send_text
    assert await manager.connect(websocket, "client-1")
    manager.connection_info["client-1"].subscribed_topics.append("/points")

    await manager.broadcast(
        {"op": "publish", "topic": "/points", "msg": {"sequence": 1}}
    )
    await asyncio.wait_for(first_send_started.wait(), timeout=1)
    await manager.broadcast(
        {"op": "publish", "topic": "/points", "msg": {"sequence": 2}}
    )
    await manager.broadcast(
        {"op": "publish", "topic": "/points", "msg": {"sequence": 3}}
    )

    release_first_send.set()
    await asyncio.wait_for(latest_send_finished.wait(), timeout=1)
    await manager.close_all()

    assert sent_sequences == [1, 3]
