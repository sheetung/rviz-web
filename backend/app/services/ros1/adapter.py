"""Native rospy adapter. ROS callbacks never own browser connections."""

import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import os
import io
import socket
from urllib.parse import urlparse
import threading
import time
from xmlrpc.client import ServerProxy, Transport

import rospy

from ...core.ros_types import canonical_message_type
from ...models.ros import NodeInfo, TopicInfo
from .message_converter import MessageConverter, get_message_class

logger = logging.getLogger(__name__)


class TimeoutTransport(Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = 2
        return conn


class Ros1Adapter:
    middleware = "ros1"

    def __init__(self, settings):
        self.settings = settings
        self._converter = MessageConverter(settings)
        self._sink = None
        self._subscriptions = {}
        self._publishers = {}
        self._publisher_lock = asyncio.Lock()
        self._graph_lock = asyncio.Lock()
        self._graph_cache = None
        self._graph_at = 0
        self._ready = False

    def set_message_sink(self, sink):
        self._sink = sink

    def _master(self, method, *args):
        with ServerProxy(
            os.environ.get("ROS_MASTER_URI", "http://localhost:11311"),
            transport=TimeoutTransport(),
        ) as proxy:
            code, reason, value = getattr(proxy, method)("/rvizweb", *args)
            if code != 1:
                raise RuntimeError(reason)
            return value

    async def start(self):
        await asyncio.to_thread(self._master, "getUri")
        if rospy.core.is_initialized():
            raise RuntimeError(
                "ROS1 node already initialized; start a fresh backend process"
            )
        rospy.init_node("rvizweb", anonymous=True, disable_signals=True)
        self._ready = True

    async def stop(self):
        self._ready = False
        for topic in list(self._subscriptions):
            await self.unsubscribe_topic(topic)
        for pub in self._publishers.values():
            await asyncio.to_thread(pub["handle"].unregister)
        self._publishers.clear()
        if rospy.core.is_initialized():
            rospy.signal_shutdown("RVizWeb stopped")

    async def _graph(self):
        async with self._graph_lock:
            if (
                self._graph_cache is not None
                and time.monotonic() - self._graph_at
                < self.settings.ros_graph_cache_ttl
            ):
                return self._graph_cache
            try:
                state = await asyncio.to_thread(self._master, "getSystemState")
                types = await asyncio.to_thread(self._master, "getTopicTypes")
            except Exception:
                self._ready = False
                raise
            self._ready = True
            self._graph_cache = (state, dict(types))
            self._graph_at = time.monotonic()
            return self._graph_cache

    async def get_topics(self, include_details=True):
        state, types = await self._graph()
        pubs, subs = dict(state[0]), dict(state[1])
        result = []
        for topic, kind in sorted(types.items()):
            observed = self._subscriptions.get(topic)
            if observed:
                with observed["lock"]:
                    stamps = list(observed["times"])
            else:
                stamps = []
            now = time.monotonic()
            stamps = [t for t in stamps if now - t <= 5]
            frequency = (
                (len(stamps) - 1) / (stamps[-1] - stamps[0])
                if len(stamps) > 1 and stamps[-1] > stamps[0]
                else None
            )
            if observed and not stamps and now - observed["start"] > 5:
                frequency = 0.0
            result.append(
                TopicInfo(
                    name=topic,
                    message_type=kind,
                    publishers=pubs.get(topic, []) if include_details else [],
                    subscribers=subs.get(topic, []) if include_details else [],
                    frequency=frequency,
                    last_message_time=observed["last"] if observed else None,
                )
            )
        return result

    async def get_topic_info(self, topic_name):
        return next((t for t in await self.get_topics() if t.name == topic_name), None)

    async def get_topic_types(self):
        _, types = await self._graph()
        return {name: canonical_message_type(kind) for name, kind in types.items()}

    async def get_nodes(self):
        state, _ = await self._graph()
        names = sorted(
            {name for group in state for _, nodes in group for name in nodes}
        )
        return [
            NodeInfo(
                name=name,
                namespace=name.rsplit("/", 1)[0] or "/",
                publishers=[t for t, nodes in state[0] if name in nodes],
                subscribers=[t for t, nodes in state[1] if name in nodes],
                services=[t for t, nodes in state[2] if name in nodes],
            )
            for name in names
        ]

    async def get_node_info(self, node_name):
        return next((n for n in await self.get_nodes() if n.name == node_name), None)

    async def get_services(self):
        state, _ = await self._graph()
        return [name for name, _ in state[2]]

    async def get_service_types(self):
        # Master exposes URIs only. Probe TCPROS with bounded socket timeouts.
        result = {}
        for name in await self.get_services():
            try:
                result[name] = await asyncio.to_thread(self._service_type, name)
            except Exception:
                result[name] = None
        return {k: v for k, v in result.items() if v}

    def _service_type(self, name):
        from rosgraph.network import (
            write_ros_handshake_header,
            read_ros_handshake_header,
        )

        uri = urlparse(self._master("lookupService", name))
        with socket.create_connection((uri.hostname, uri.port), timeout=2) as sock:
            write_ros_handshake_header(
                sock,
                {"probe": "1", "md5sum": "*", "callerid": "/rvizweb", "service": name},
            )
            return read_ros_handshake_header(sock, io.BytesIO(), 2048).get("type")

    async def get_params(self):
        return await asyncio.to_thread(self._master, "getParamNames")

    async def get_topic_frequencies(self, sample_duration=None):
        # Only report observed subscription traffic, never invent a graph frequency.
        return {t.name: t.frequency for t in await self.get_topics(False)}

    async def subscribe_topic(self, topic_name, message_type=None):
        kind = (
            canonical_message_type(message_type)
            if message_type
            else (await self.get_topic_types()).get(topic_name)
        )
        if not kind:
            raise ValueError(f"Topic type unavailable: {topic_name}")
        existing = self._subscriptions.get(topic_name)
        if existing:
            if existing["kind"] != kind:
                raise ValueError("Topic already subscribed with a different type")
            return True
        cls = get_message_class(kind)
        replaceable = kind in {
            "sensor_msgs/msg/PointCloud2",
            "sensor_msgs/msg/Image",
            "sensor_msgs/msg/CompressedImage",
            "sensor_msgs/msg/LaserScan",
        }
        state = dict(
            kind=kind,
            lock=threading.Lock(),
            queue=deque(maxlen=1 if replaceable else 64),
            retained={},
            pending_latched={},
            static={},
            times=deque(maxlen=200),
            start=time.monotonic(),
            last=None,
            active=True,
            last_forward=0.0,
        )
        self._subscriptions[topic_name] = state

        def callback(msg):
            with state["lock"]:
                if not state["active"]:
                    return
                state["times"].append(time.monotonic())
                state["last"] = datetime.now(timezone.utc)
                header = getattr(msg, "_connection_header", {}) or {}
                if topic_name == "/tf_static":
                    for tf in msg.transforms:
                        key = (tf.header.frame_id, tf.child_frame_id)
                        if key in state["static"] or len(state["static"]) < 2048:
                            state["static"][key] = tf
                    state["pending_latched"]["tf"] = cls(
                        transforms=list(state["static"].values())
                    )
                elif header.get("latching") == "1":
                    key = header.get("callerid", "")
                    if (
                        key in state["pending_latched"]
                        or len(state["pending_latched"]) < 64
                    ):
                        state["pending_latched"][key] = msg
                else:
                    state["queue"].append(msg)

        try:
            state["handle"] = await asyncio.to_thread(
                rospy.Subscriber,
                topic_name,
                cls,
                callback,
                queue_size=1 if replaceable else 64,
                buff_size=max(
                    self.settings.ros_pointcloud_max_bytes,
                    self.settings.ros_image_max_bytes,
                )
                + 65536,
                tcp_nodelay=True,
            )
        except BaseException:
            self._subscriptions.pop(topic_name, None)
            state["active"] = False
            raise
        state["task"] = asyncio.create_task(self._drain(topic_name, state))
        return True

    async def _drain(self, topic, state):
        while state["active"]:
            item, retained_key = None, None
            with state["lock"]:
                if state["pending_latched"]:
                    retained_key = next(iter(state["pending_latched"]))
                    item = state["pending_latched"].pop(retained_key)
                elif state["queue"]:
                    hz = self.settings.ros_pointcloud_max_hz
                    due = (
                        state["kind"] != "sensor_msgs/msg/PointCloud2"
                        or hz <= 0
                        or time.monotonic() - state["last_forward"] >= 1 / hz
                    )
                    if due:
                        item = state["queue"].popleft()
            if item is None:
                await asyncio.sleep(0.002)
                continue
            try:
                payload = await asyncio.to_thread(self._converter.to_dict, item)
                if not state["active"] or self._subscriptions.get(topic) is not state:
                    return
                state["last_forward"] = time.monotonic()
                if retained_key is not None:
                    if retained_key in state["retained"] or len(state["retained"]) < 64:
                        state["retained"][retained_key] = payload
                if self._sink:
                    await self._sink(topic, payload, state["kind"])
            except Exception:
                logger.exception("ROS1 conversion/delivery failed for %s", topic)

    def get_retained_messages(self, topic):
        state = self._subscriptions.get(topic)
        return list(state["retained"].values()) if state else []

    async def unsubscribe_topic(self, topic_name):
        state = self._subscriptions.pop(topic_name, None)
        if not state:
            return False
        with state["lock"]:
            state["active"] = False
        state["task"].cancel()
        await asyncio.gather(state["task"], return_exceptions=True)
        await asyncio.to_thread(state["handle"].unregister)
        return True

    async def acquire_publisher(self, topic, msg_type, owner_id):
        async with self._publisher_lock:
            await self._acquire_publisher(topic, msg_type, owner_id)

    async def _acquire_publisher(self, topic, msg_type, owner_id):
        kind = canonical_message_type(msg_type)
        pub = self._publishers.get(topic)
        if pub and pub["kind"] != kind:
            raise ValueError("Publisher type mismatch")
        if pub is None:
            if len(self._publishers) >= self.settings.ros_max_publishers:
                raise RuntimeError("Publisher limit reached")
            cls = get_message_class(kind)
            handle = await asyncio.to_thread(
                rospy.Publisher, topic, cls, queue_size=8, tcp_nodelay=True
            )
            pub = dict(handle=handle, cls=cls, kind=kind, owners=set())
            self._publishers[topic] = pub
        pub["owners"].add(owner_id)

    async def release_publisher(self, topic, owner_id):
        async with self._publisher_lock:
            await self._release_publisher(topic, owner_id)

    async def _release_publisher(self, topic, owner_id):
        pub = self._publishers.get(topic)
        if pub:
            pub["owners"].discard(owner_id)
            if not pub["owners"]:
                self._publishers.pop(topic)
                await asyncio.to_thread(pub["handle"].unregister)

    def publish_prepared(self, topic, message):
        pub = self._publishers.get(topic)
        if not pub:
            raise ValueError("Publisher not acquired")
        pub["handle"].publish(self._converter.from_dict(pub["cls"], message))
        return pub["kind"]

    async def publish_message(self, topic_name, message, message_type=None):
        import uuid

        kind = message_type or (await self.get_topic_types()).get(topic_name)
        if not kind:
            raise ValueError("Message type required")
        owner = f"rest:{uuid.uuid4()}"
        await self.acquire_publisher(topic_name, kind, owner)
        try:
            # Allow a newly registered TCPROS publisher to establish transport.
            for _ in range(50):
                if self._publishers[topic_name]["handle"].get_num_connections():
                    break
                await asyncio.sleep(0.01)
            self.publish_prepared(topic_name, message)
            await asyncio.sleep(0.05)
            return True
        finally:
            await self.release_publisher(topic_name, owner)
