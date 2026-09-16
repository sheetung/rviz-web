#include "rvizweb/control.hpp"
#include <iostream>
#include <limits>
using namespace rvizweb;
void require(bool ok) { if (!ok) throw std::runtime_error("control validation test failed"); }
int main() {
  auto pose = parse(R"({"header":{"frame_id":"map","stamp":{"sec":777,"nanosec":123}},"pose":{"position":{"x":1,"y":-2,"z":3},"orientation":{"x":0,"y":0,"z":0,"w":1}}})");
  const std::string type = "geometry_msgs/msg/PoseStamped";
  validate_control(type, pose);
  auto rejected = [&](Json::Value m) { try { validate_control(type, m); return false; } catch (const std::invalid_argument&) { return true; } };
  auto bad = pose; bad["pose"]["position"]["x"] = "1"; require(rejected(bad));
  bad = pose; bad["pose"]["orientation"]["w"] = 0; require(rejected(bad));
  bad = pose; bad["pose"]["position"]["x"] = std::numeric_limits<double>::infinity(); require(rejected(bad));
  bad = pose; bad["header"]["stamp"]["nanosec"] = 1000000000; require(rejected(bad));
  bad = pose; bad["header"]["frame_id"] = ""; require(rejected(bad));
  auto initial = pose; initial["pose"]["pose"] = pose["pose"]; initial["pose"]["covariance"] = Json::Value(Json::arrayValue);
  for (unsigned i = 0; i < 36; ++i) initial["pose"]["covariance"].append(i % 7 == 0 ? 0.25 : 0);
  validate_control("geometry_msgs/msg/PoseWithCovarianceStamped", initial);
  initial["pose"]["covariance"][0] = -1;
  bool invalid = false; try { validate_control("geometry_msgs/msg/PoseWithCovarianceStamped", initial); } catch (...) { invalid = true; }
  require(invalid);
  auto twist = parse(R"({"linear":{"x":0.2,"y":0,"z":0},"angular":{"x":0,"y":0,"z":-0.1}})");
  validate_control("geometry_msgs/msg/Twist", twist);
  std::cout << "finite fields, quaternion, covariance, frame and timestamps validated\n";
}
