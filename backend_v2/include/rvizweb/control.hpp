#pragma once
#include "rvizweb/protocol.hpp"
#include <cmath>
#include <stdexcept>
namespace rvizweb {
inline bool publish_type(const std::string& type) {
  return type == "geometry_msgs/msg/PoseStamped" || type == "geometry_msgs/msg/PoseWithCovarianceStamped" || type == "geometry_msgs/msg/Twist";
}
inline double finite_field(const Json::Value& value) {
  if (!value.isNumeric() || !std::isfinite(value.asDouble())) throw std::invalid_argument("Expected a finite numeric control field");
  return value.asDouble();
}
inline void validate_vector(const Json::Value& value) {
  for (const auto* axis : {"x", "y", "z"}) finite_field(value[axis]);
}
inline void validate_control(const std::string& type, const Json::Value& message) {
  if (!publish_type(type)) throw std::invalid_argument("Unsupported publish type");
  if (!message.isObject()) throw std::invalid_argument("msg must be an object");
  if (type == "geometry_msgs/msg/Twist") {
    validate_vector(message["linear"]); validate_vector(message["angular"]); return;
  }
  const auto& header = message["header"];
  if (!header.isObject() || !header["frame_id"].isString() || header["frame_id"].asString().empty() ||
      header["frame_id"].asString().size() > 256 || header["frame_id"].asString().find_first_of(" \t\r\n\0", 0, 5) != std::string::npos)
    throw std::invalid_argument("header.frame_id must be a nonempty frame name");
  if (header.isMember("stamp")) {
    const auto& time = header["stamp"];
    if (!time.isObject() || !time["sec"].isInt64() || time["sec"].asInt64() < 0 || time["sec"].asInt64() > 2147483647 ||
        !time["nanosec"].isUInt() || time["nanosec"].asUInt() >= 1000000000)
      throw std::invalid_argument("Invalid ROS timestamp");
  }
  const auto& pose = type == "geometry_msgs/msg/PoseStamped" ? message["pose"] : message["pose"]["pose"];
  validate_vector(pose["position"]); validate_vector(pose["orientation"]);
  double norm = 0;
  for (const auto* axis : {"x", "y", "z", "w"}) { const auto x = finite_field(pose["orientation"][axis]); norm += x * x; }
  if (!std::isfinite(norm) || std::abs(norm - 1.0) > 0.001) throw std::invalid_argument("Orientation must be a unit quaternion");
  if (type == "geometry_msgs/msg/PoseWithCovarianceStamped") {
    const auto& covariance = message["pose"]["covariance"];
    if (!covariance.isArray() || covariance.size() != 36) throw std::invalid_argument("Covariance must contain 36 finite numbers");
    for (const auto& value : covariance) finite_field(value);
    for (unsigned i = 0; i < 6; ++i) if (covariance[i * 7].asDouble() < 0) throw std::invalid_argument("Covariance diagonal must be nonnegative");
  }
}
template<class T> void fill_vector(T& target, const Json::Value& source) {
  target.x = source["x"].asDouble(); target.y = source["y"].asDouble(); target.z = source["z"].asDouble();
}
template<class T> void fill_pose(T& target, const Json::Value& source) {
  fill_vector(target.position, source["position"]); fill_vector(target.orientation, source["orientation"]);
  target.orientation.w = source["orientation"]["w"].asDouble();
}
} // namespace rvizweb
