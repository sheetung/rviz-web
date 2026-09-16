#pragma once
#include "rvizweb/protocol.hpp"
#include <cmath>
#include <stdexcept>
namespace rvizweb {
inline Json::Value number(double value) { return std::isfinite(value) ? Json::Value(value) : Json::Value(); }
template<class T> Json::Value vector(const T& p) {
  Json::Value j; j["x"] = number(p.x); j["y"] = number(p.y); j["z"] = number(p.z); return j;
}
template<class T> Json::Value quaternion(const T& p) { auto j = vector(p); j["w"] = number(p.w); return j; }
template<class T> Json::Value numbers(const T& values) {
  Json::Value j(Json::arrayValue); for (const auto value : values) j.append(number(value)); return j;
}
inline Json::Value stamp(int64_t sec, uint32_t nanosec) {
  Json::Value j; j["sec"] = Json::Int64(sec); j["nanosec"] = nanosec; return j;
}
template<class T> FramePtr odometry(const T& m, const std::string& topic, const Json::Value& time) {
  Json::Value event;
  event["version"] = 2; event["event"] = "topic.message"; event["topic"] = topic;
  event["type"] = "nav_msgs/msg/Odometry";
  auto& j = event["msg"];
  j["header"]["stamp"] = time; j["header"]["frame_id"] = m.header.frame_id;
  j["child_frame_id"] = m.child_frame_id;
  j["pose"]["pose"]["position"] = vector(m.pose.pose.position);
  j["pose"]["pose"]["orientation"] = quaternion(m.pose.pose.orientation);
  j["pose"]["covariance"] = numbers(m.pose.covariance);
  j["twist"]["twist"]["linear"] = vector(m.twist.twist.linear);
  j["twist"]["twist"]["angular"] = vector(m.twist.twist.angular);
  j["twist"]["covariance"] = numbers(m.twist.covariance);
  return text_frame(event);
}
template<class T> FramePtr pointcloud(const T& m, const std::string& topic, const Json::Value& time) {
  if (uint64_t(m.row_step) * m.height != m.data.size() || uint64_t(m.width) * m.point_step > m.row_step)
    throw std::invalid_argument("Invalid PointCloud2 dimensions");
  if (m.data.size() > max_frame_bytes) throw std::length_error("PointCloud2 exceeds frame limit");
  Json::Value event;
  event["topic"] = topic; event["type"] = "sensor_msgs/msg/PointCloud2";
  auto& j = event["msg"];
  j["header"]["stamp"] = time; j["header"]["frame_id"] = m.header.frame_id;
  j["height"] = m.height; j["width"] = m.width;
  j["is_bigendian"] = bool(m.is_bigendian); j["is_dense"] = bool(m.is_dense);
  j["point_step"] = m.point_step; j["row_step"] = m.row_step;
  j["fields"] = Json::Value(Json::arrayValue);
  constexpr uint32_t sizes[] = {0, 1, 1, 2, 2, 4, 4, 4, 8};
  for (const auto& f : m.fields) {
    if (f.datatype < 1 || f.datatype > 8 || f.count == 0 ||
        uint64_t(f.offset) + uint64_t(f.count) * sizes[f.datatype] > m.point_step)
      throw std::invalid_argument("Invalid PointCloud2 field");
    Json::Value field;
    field["name"] = f.name; field["offset"] = f.offset;
    field["datatype"] = f.datatype; field["count"] = f.count;
    j["fields"].append(field);
  }
  return pointcloud_frame(event, m.data);
}
}  // namespace rvizweb
