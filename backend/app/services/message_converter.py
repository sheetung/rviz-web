"""
ROS2 消息与字典的双向转换
处理消息序列化（ROS→dict）和反序列化（dict→ROS）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rosbridge import RosbridgeService

logger = logging.getLogger(__name__)


class MessageConverter:
    """ROS2 消息与 Python 字典的双向转换器"""

    _POINT_FIELD_BYTES = {
        1: 1,
        2: 1,
        3: 2,
        4: 2,
        5: 4,
        6: 4,
        7: 4,
        8: 8,
    }

    def __init__(self, service: RosbridgeService):
        self._svc = service

    def to_dict(self, msg) -> dict:
        """将 ROS 消息转换为字典"""
        try:
            import numpy as np
            from builtin_interfaces.msg import Time, Duration
            from geometry_msgs.msg import (
                Point,
                Pose,
                PoseWithCovariance,
                Quaternion,
            )
            from sensor_msgs.msg import PointCloud2, Image, CompressedImage
            from std_msgs.msg import Header

            # 特殊处理点云数据
            if isinstance(msg, PointCloud2):
                return self.process_pointcloud(msg)

            # 特殊处理图像数据
            if isinstance(msg, Image):
                return self.process_image(msg)

            # 特殊处理压缩图像数据
            if isinstance(msg, CompressedImage):
                return self.process_compressed_image(msg)

            if hasattr(msg, "__slots__"):
                result = {}
                for slot in msg.__slots__:
                    value = getattr(msg, slot)
                    field_name = slot.removeprefix("_")

                    # 处理时间类型
                    if isinstance(value, Time):
                        result[field_name] = {
                            "sec": int(value.sec),
                            "nanosec": int(value.nanosec),
                        }
                    elif isinstance(value, Duration):
                        result[field_name] = {
                            "sec": int(value.sec),
                            "nanosec": int(value.nanosec),
                        }
                    # 处理Header
                    elif isinstance(value, Header):
                        result[field_name] = {
                            "stamp": {
                                "sec": int(value.stamp.sec),
                                "nanosec": int(value.stamp.nanosec),
                            },
                            "frame_id": str(value.frame_id),
                        }
                    # 处理几何类型
                    elif isinstance(value, Point):
                        result[field_name] = {
                            "x": float(value.x),
                            "y": float(value.y),
                            "z": float(value.z),
                        }
                    elif isinstance(value, Quaternion):
                        result[field_name] = {
                            "x": float(value.x),
                            "y": float(value.y),
                            "z": float(value.z),
                            "w": float(value.w),
                        }
                    elif isinstance(value, Pose):
                        result[field_name] = {
                            "position": {
                                "x": float(value.position.x),
                                "y": float(value.position.y),
                                "z": float(value.position.z),
                            },
                            "orientation": {
                                "x": float(value.orientation.x),
                                "y": float(value.orientation.y),
                                "z": float(value.orientation.z),
                                "w": float(value.orientation.w),
                            },
                        }
                    elif isinstance(value, PoseWithCovariance):
                        result[field_name] = {
                            "pose": {
                                "position": {
                                    "x": float(value.pose.position.x),
                                    "y": float(value.pose.position.y),
                                    "z": float(value.pose.position.z),
                                },
                                "orientation": {
                                    "x": float(value.pose.orientation.x),
                                    "y": float(value.pose.orientation.y),
                                    "z": float(value.pose.orientation.z),
                                    "w": float(value.pose.orientation.w),
                                },
                            },
                            "covariance": (
                                [float(c) for c in value.covariance]
                                if hasattr(value, "covariance")
                                else []
                            ),
                        }
                    # 处理numpy数组
                    elif isinstance(value, np.ndarray):
                        if value.dtype == np.uint8:
                            result[field_name] = value.tolist()
                        else:
                            result[field_name] = value.astype(float).tolist()
                    # 处理bytes类型（点云数据等）
                    elif isinstance(value, bytes):
                        # 对于大型bytes数据，使用Base64编码
                        if len(value) > 1000:
                            import base64

                            result[field_name] = base64.b64encode(value).decode("ascii")
                            result[f"{field_name}_encoding"] = "base64"
                        else:
                            result[field_name] = list(value)  # 小数据直接转换为数组
                    # 处理嵌套消息
                    elif hasattr(value, "__slots__"):
                        result[field_name] = self.to_dict(value)
                    # 处理列表
                    elif isinstance(value, list):
                        result[field_name] = [
                            (
                                self.to_dict(item)
                                if hasattr(item, "__slots__")
                                else (
                                    float(item)
                                    if isinstance(item, (int, float, np.number))
                                    else item
                                )
                            )
                            for item in value
                        ]
                    # 处理基本数值类型
                    elif isinstance(value, (int, float, np.number)):
                        result[field_name] = (
                            float(value)
                            if isinstance(value, (float, np.floating))
                            else int(value)
                        )
                    # 处理字符串和其他类型
                    else:
                        result[field_name] = str(value) if value is not None else None

                return result
            else:
                return {"data": str(msg)}
        except Exception as e:
            logger.error(f"Failed to convert message to dict: {e}")
            return {"error": str(e), "message_type": type(msg).__name__}

    def from_dict(self, msg_class, data: dict):
        """将字典递归转换为ROS消息实例（按公开属性名赋值，兼容私有__slots__）。"""
        try:
            msg = msg_class()

            def assign_by_public_fields(obj, value_dict):
                if not isinstance(value_dict, dict):
                    return
                for key, val in value_dict.items():
                    if not hasattr(obj, key):
                        raise ValueError(f"{type(obj).__name__} 不包含消息字段 {key}")
                    current_attr = getattr(obj, key)

                    # 嵌套消息对象
                    if hasattr(current_attr, "__slots__") and isinstance(val, dict):
                        assign_by_public_fields(current_attr, val)
                        continue

                    # 若需要新建子对象（极少情况）
                    if isinstance(val, dict) and hasattr(
                        type(current_attr), "__slots__"
                    ):
                        try:
                            sub = type(current_attr)()
                            assign_by_public_fields(sub, val)
                            setattr(obj, key, sub)
                            continue
                        except Exception:
                            pass

                    # 列表/数组字段（如covariance）
                    if isinstance(val, list):
                        # 特殊处理协方差：必须是长度36的float序列
                        if key == "covariance":
                            if len(val) != 36:
                                raise ValueError("covariance 必须包含 36 个数值")
                            floats = [float(x) for x in val]
                            try:
                                setattr(obj, key, floats)
                            except Exception as error:
                                raise ValueError(
                                    f"无法设置 {type(obj).__name__}.{key}"
                                ) from error
                            continue

                        # 其他列表，尽量转float（数值型）后设置
                        try:
                            coerced = [
                                float(x) if isinstance(x, (int, float)) else x
                                for x in val
                            ]
                            setattr(obj, key, coerced)
                        except Exception as error:
                            raise ValueError(
                                f"无法设置 {type(obj).__name__}.{key}"
                            ) from error
                        continue

                    # 基本类型
                    try:
                        if isinstance(current_attr, float) and isinstance(
                            val, (int, float)
                        ):
                            val = float(val)
                        setattr(obj, key, val)
                    except Exception as error:
                        raise ValueError(
                            f"无法设置 {type(obj).__name__}.{key}"
                        ) from error

            # 顶层赋值（包含header/pose等）
            assign_by_public_fields(msg, data)
            return msg
        except Exception as e:
            logger.error(
                f"Failed to build message {msg_class.__name__}: {e}", exc_info=True
            )
            return None

    @classmethod
    def _compact_pointcloud_data(
        cls,
        pointcloud_msg,
        fields: list[dict],
        xyz_only: bool,
    ) -> tuple[bytes | object, list[dict], int]:
        """保留全部点，并可只保留浏览器渲染需要的 XYZ 字段。"""
        import numpy as np

        width = max(0, int(pointcloud_msg.width))
        height = max(0, int(pointcloud_msg.height))
        point_step = max(0, int(pointcloud_msg.point_step))
        row_step = max(0, int(pointcloud_msg.row_step))
        total_points = width * height
        raw_data = pointcloud_msg.data

        if total_points == 0 or point_step == 0:
            return raw_data, fields, point_step

        minimum_row_step = width * point_step
        effective_row_step = (
            row_step if row_step >= minimum_row_step else minimum_row_step
        )
        required_bytes = (height - 1) * effective_row_step + minimum_row_step
        if len(raw_data) < required_bytes:
            raise ValueError(
                f"PointCloud2 数据长度 {len(raw_data)} 小于布局要求 {required_bytes}"
            )

        selected_fields = fields
        if xyz_only:
            by_name = {field.get("name"): field for field in fields}
            xyz_fields = [by_name.get(name) for name in ("x", "y", "z")]
            if all(xyz_fields):
                next_offset = 0
                compact_fields = []
                for field in xyz_fields:
                    datatype_bytes = cls._POINT_FIELD_BYTES.get(field["datatype"], 0)
                    field_bytes = datatype_bytes * max(1, int(field.get("count", 1)))
                    if (
                        field_bytes <= 0
                        or field["offset"] < 0
                        or field["offset"] + field_bytes > point_step
                    ):
                        compact_fields = []
                        break
                    compact_fields.append(
                        {
                            **field,
                            "offset": next_offset,
                            "_source_offset": field["offset"],
                            "_field_bytes": field_bytes,
                        }
                    )
                    next_offset += field_bytes
                if compact_fields:
                    selected_fields = compact_fields

        compact_xyz = selected_fields is not fields
        if not compact_xyz and effective_row_step == minimum_row_step:
            return raw_data, fields, point_step

        raw_bytes = np.frombuffer(raw_data, dtype=np.uint8)
        rows_are_compact = effective_row_step == minimum_row_step
        if rows_are_compact:
            records = raw_bytes[: total_points * point_step].reshape(
                total_points,
                point_step,
            )
            selected_records = records
            if compact_xyz:
                chunks = [
                    selected_records[
                        :,
                        field["_source_offset"] : field["_source_offset"]
                        + field["_field_bytes"],
                    ]
                    for field in selected_fields
                ]
                output = np.concatenate(chunks, axis=1).tobytes()
            else:
                output = selected_records.tobytes()
        else:
            point_indices = np.arange(total_points, dtype=np.int64)
            source_offsets = (point_indices // width) * effective_row_step + (
                point_indices % width
            ) * point_step
            output = bytearray(
                total_points
                * (
                    sum(field["_field_bytes"] for field in selected_fields)
                    if compact_xyz
                    else point_step
                )
            )
            destination_offset = 0
            source_view = memoryview(raw_data).cast("B")
            for source_offset in source_offsets:
                if compact_xyz:
                    for field in selected_fields:
                        field_start = int(source_offset) + field["_source_offset"]
                        field_end = field_start + field["_field_bytes"]
                        field_bytes = source_view[field_start:field_end]
                        output[
                            destination_offset : destination_offset + len(field_bytes)
                        ] = field_bytes
                        destination_offset += len(field_bytes)
                else:
                    record = source_view[
                        int(source_offset) : int(source_offset) + point_step
                    ]
                    output[destination_offset : destination_offset + point_step] = (
                        record
                    )
                    destination_offset += point_step
            output = bytes(output)

        clean_fields = [
            {key: value for key, value in field.items() if not key.startswith("_")}
            for field in selected_fields
        ]
        output_point_step = (
            sum(field["_field_bytes"] for field in selected_fields)
            if compact_xyz
            else point_step
        )
        return output, clean_fields, output_point_step

    def process_pointcloud(self, pointcloud_msg) -> dict:
        """在保留全部点的前提下紧凑 PointCloud2 点记录。"""
        try:
            # 解析点云字段
            fields = []
            for field in pointcloud_msg.fields:
                fields.append(
                    {
                        "name": field.name,
                        "offset": field.offset,
                        "datatype": field.datatype,
                        "count": field.count,
                    }
                )

            # 基本信息
            result = {
                "header": self.to_dict(pointcloud_msg.header),
                "height": pointcloud_msg.height,
                "width": pointcloud_msg.width,
                "fields": fields,
                "is_bigendian": pointcloud_msg.is_bigendian,
                "point_step": pointcloud_msg.point_step,
                "row_step": pointcloud_msg.row_step,
                "is_dense": pointcloud_msg.is_dense,
            }

            # 处理点云数据
            if len(pointcloud_msg.data) > 0:
                max_bytes = self._svc.settings.ros_pointcloud_max_bytes
                if len(pointcloud_msg.data) > max_bytes:
                    return {
                        **result,
                        "error": (
                            f"PointCloud2 数据为 {len(pointcloud_msg.data)} 字节，"
                            f"超过上限 {max_bytes} 字节"
                        ),
                        "data": [],
                        "data_encoding": "array",
                    }
                logger.debug(
                    "Processing pointcloud data - Total bytes: %s, Point step: %s",
                    len(pointcloud_msg.data),
                    pointcloud_msg.point_step,
                )

                total_points = pointcloud_msg.width * pointcloud_msg.height

                logger.debug(
                    "Pointcloud info - Width: %s, Height: %s, Total points: %s",
                    pointcloud_msg.width,
                    pointcloud_msg.height,
                    total_points,
                )

                point_data, output_fields, output_point_step = (
                    self._compact_pointcloud_data(
                        pointcloud_msg,
                        fields,
                        self._svc.settings.ros_pointcloud_xyz_only,
                    )
                )
                compact_xyz = (
                    output_fields != fields
                    or output_point_step != pointcloud_msg.point_step
                )
                result["fields"] = output_fields
                result["point_step"] = output_point_step
                result["row_step"] = result["width"] * output_point_step

                # 大型数据使用 Base64；只压缩点记录，不减少点数。
                if len(point_data) > 10000:
                    import base64

                    result["data"] = base64.b64encode(point_data).decode("ascii")
                    result["data_encoding"] = "base64"
                    logger.debug(
                        "Pointcloud transmission - %s -> %s bytes, %s points retained",
                        len(pointcloud_msg.data),
                        len(point_data),
                        total_points,
                    )
                else:
                    result["data"] = list(point_data)
                    result["data_encoding"] = "array"

                result["sampled"] = False
                result["original_points"] = total_points
                result["sample_step"] = 1
                result["xyz_only"] = compact_xyz
                result["original_bytes"] = len(pointcloud_msg.data)
            else:
                result["data"] = []
                result["data_encoding"] = "array"
                result["sampled"] = False
                logger.warning("Pointcloud data is empty")

            return result

        except Exception as e:
            logger.error(f"Failed to process pointcloud data: {e}")
            return {
                "header": self.to_dict(pointcloud_msg.header),
                "error": str(e),
                "data": [],
            }

    def process_image(self, image_msg) -> dict:
        """处理图像数据，进行压缩优化"""
        try:
            result = {
                "header": self.to_dict(image_msg.header),
                "height": image_msg.height,
                "width": image_msg.width,
                "encoding": image_msg.encoding,
                "is_bigendian": image_msg.is_bigendian,
                "step": image_msg.step,
            }

            data_size = len(image_msg.data)
            max_bytes = self._svc.settings.ros_image_max_bytes
            if data_size > max_bytes:
                result["error"] = (
                    f"Image 数据为 {data_size} 字节，超过上限 {max_bytes} 字节"
                )
                result["data"] = []
                result["data_encoding"] = "array"
            elif data_size > 10_000:
                import base64

                result["data"] = base64.b64encode(image_msg.data).decode("ascii")
                result["data_encoding"] = "base64"
            else:
                result["data"] = list(image_msg.data)
                result["data_encoding"] = "array"

            return result

        except Exception as e:
            logger.error(f"Failed to process image data: {e}")
            return {
                "header": self.to_dict(image_msg.header),
                "error": str(e),
                "data": [],
            }

    def process_compressed_image(self, image_msg) -> dict:
        """处理压缩图像数据"""
        try:
            result = {
                "header": self.to_dict(image_msg.header),
                "format": image_msg.format,
                "compressed": True,
            }

            data_size = len(image_msg.data)
            max_bytes = self._svc.settings.ros_image_max_bytes
            if data_size > max_bytes:
                result["error"] = (
                    f"CompressedImage 数据为 {data_size} 字节，"
                    f"超过上限 {max_bytes} 字节"
                )
                result["data"] = []
                result["data_encoding"] = "array"
            elif data_size > 10000:
                import base64

                result["data"] = base64.b64encode(image_msg.data).decode("ascii")
                result["data_encoding"] = "base64"
            else:
                result["data"] = list(image_msg.data)
                result["data_encoding"] = "array"

            return result

        except Exception as e:
            logger.error(f"Failed to process compressed image data: {e}")
            return {
                "header": self.to_dict(image_msg.header),
                "error": str(e),
                "data": [],
            }
