"""ROS1 message normalization without ROS2 imports."""

import base64
import io
import math
import re

import numpy as np

from ...core.ros_types import canonical_message_type


def get_message_class(name):
    from roslib.message import get_message_class as resolve

    native = canonical_message_type(name).replace("/msg/", "/")
    cls = resolve(native)
    if cls is None:
        raise ValueError(f"ROS1 message class unavailable: {native}")
    return cls


class MessageConverter:
    def __init__(self, settings):
        self.settings = settings

    def to_dict(self, msg):
        if hasattr(msg, "secs") and hasattr(msg, "nsecs"):
            return {"sec": msg.secs, "nanosec": msg.nsecs}
        if getattr(msg, "_type", "") == "sensor_msgs/PointCloud2":
            return self.pointcloud(msg)
        if getattr(msg, "_type", "") in (
            "sensor_msgs/Image",
            "sensor_msgs/CompressedImage",
        ):
            if len(msg.data) > self.settings.ros_image_max_bytes:
                raise ValueError("Image exceeds size limit")
            result = {
                k: self.to_dict(getattr(msg, k)) for k in msg.__slots__ if k != "data"
            }
            result["data"] = base64.b64encode(bytes(msg.data)).decode("ascii")
            result["data_encoding"] = "base64"
            if msg._type.endswith("CompressedImage"):
                result["compressed"] = True
            return result
        if isinstance(msg, (bytes, bytearray)):
            return list(msg)
        if isinstance(msg, (list, tuple, np.ndarray)):
            return [self.to_dict(x) for x in msg]
        if hasattr(msg, "__slots__"):
            result = {
                k: self.to_dict(getattr(msg, k))
                for k in msg.__slots__
                if not (getattr(msg, "_type", "") == "std_msgs/Header" and k == "seq")
            }
            return result
        if isinstance(msg, np.generic):
            return msg.item()
        return msg

    def pointcloud(self, msg):
        if len(msg.data) > self.settings.ros_pointcloud_max_bytes:
            raise ValueError("PointCloud2 exceeds size limit")
        if (
            msg.row_step < msg.width * msg.point_step
            or len(msg.data) < msg.row_step * msg.height
        ):
            raise ValueError("Invalid PointCloud2 row layout")
        fields = [self.to_dict(f) for f in msg.fields]
        dtype_map = {
            1: "i1",
            2: "u1",
            3: "i2",
            4: "u2",
            5: "i4",
            6: "u4",
            7: "f4",
            8: "f8",
        }
        for field in fields:
            if (
                field["datatype"] not in dtype_map
                or field["count"] < 1
                or field["offset"] < 0
            ):
                raise ValueError("Invalid PointCloud2 field")
            size = np.dtype(dtype_map[field["datatype"]]).itemsize * field["count"]
            if field["offset"] + size > msg.point_step:
                raise ValueError("PointCloud2 field exceeds record")
        records = np.ndarray(
            (msg.height, msg.width, msg.point_step),
            dtype="u1",
            buffer=msg.data,
            strides=(msg.row_step, msg.point_step, 1),
        )
        selected = [
            next((f for f in fields if f["name"] == n), None) for n in ("x", "y", "z")
        ]
        compact = self.settings.ros_pointcloud_xyz_only and all(selected)
        if compact:
            parts, fields, offset = [], [], 0
            for f in selected:
                size = np.dtype(dtype_map[f["datatype"]]).itemsize * f["count"]
                parts.append(records[:, :, f["offset"] : f["offset"] + size])
                fields.append({**f, "offset": offset})
                offset += size
            data = np.concatenate(parts, axis=2).tobytes()
            step = offset
        else:
            data, step = records.tobytes(), msg.point_step
        return dict(
            header=self.to_dict(msg.header),
            width=msg.width,
            height=msg.height,
            fields=fields,
            point_step=step,
            row_step=step * msg.width,
            is_bigendian=msg.is_bigendian,
            is_dense=msg.is_dense,
            data=data,
            data_encoding="binary",
            sampled=False,
            original_points=msg.width * msg.height,
            sample_step=1,
            xyz_only=bool(compact),
            original_bytes=len(msg.data),
        )

    def from_dict(self, cls, data):
        msg = cls()
        self._assign(msg, data)
        # genpy performs final wire-level type/range validation.
        msg.serialize(io.BytesIO())
        return msg

    def _assign(self, msg, data):
        if not isinstance(data, dict):
            raise ValueError("Message must be an object")
        if hasattr(msg, "secs"):
            if set(data) - {"sec", "nanosec"}:
                raise ValueError("Use sec/nanosec for time")
            sec, ns = data.get("sec", 0), data.get("nanosec", 0)
            if type(sec) is not int or type(ns) is not int or not 0 <= ns < 10**9:
                raise ValueError("Invalid time")
            msg.secs, msg.nsecs = sec, ns
            return
        types = dict(zip(msg.__slots__, msg._slot_types))
        for name, value in data.items():
            if name not in types or name == "seq" and msg._type == "std_msgs/Header":
                raise ValueError(f"Unknown normalized message field: {name}")
            kind = types[name]
            array = re.fullmatch(r"(.+)\[(\d*)\]", kind)
            if array:
                if not isinstance(value, list):
                    raise ValueError(f"{name} must be an array")
                base, size = array.groups()
                if size and len(value) != int(size):
                    raise ValueError(f"Invalid array length: {name}")
                setattr(msg, name, [self._value(base, x) for x in value])
            elif hasattr(getattr(msg, name), "__slots__"):
                self._assign(getattr(msg, name), value)
            else:
                setattr(msg, name, self._value(kind, value))

    def _value(self, kind, value):
        if "/" in kind:
            return self.from_dict(get_message_class(kind), value)
        if kind in ("time", "duration"):
            import genpy

            obj = genpy.Time() if kind == "time" else genpy.Duration()
            self._assign(obj, value)
            return obj
        if kind == "bool":
            if type(value) is not bool:
                raise ValueError("Expected bool")
        elif kind == "string":
            if not isinstance(value, str):
                raise ValueError("Expected string")
        elif kind.startswith("float"):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Expected finite number")
            value = float(value)
        else:
            if type(value) is not int:
                raise ValueError("Expected integer")
            signed = kind.startswith("int") or kind == "byte"
            bits = (
                int(re.search(r"\d+", kind).group()) if re.search(r"\d+", kind) else 8
            )
            if (
                not -(2 ** (bits - 1) if signed else 0)
                <= value
                < 2 ** (bits - 1 if signed else bits)
            ):
                raise ValueError("Integer out of range")
        return value
