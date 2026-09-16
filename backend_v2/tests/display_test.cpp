#include "rvizweb/display.hpp"
#include "rvizweb/ros1_dynamic.hpp"
#include <iostream>
using namespace rvizweb;
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
int main() {
  DisplayEncoder tf("/tf_static", "tf2_msgs/msg/TFMessage");
  Json::Value input; input["transforms"][0]["child_frame_id"] = "a";
  tf.encode(input); input["transforms"][0]["child_frame_id"] = "b";
  auto merged = tf.encode(input);
  check(parse(merged->bytes)["msg"]["transforms"].size() == 2, "TF edges survive coalescing");
  ReplayStream replay; replay.publish(merged);
  FramePtr received; auto handle = replay.attach([&](FramePtr frame) { received = frame; });
  check(received == merged, "late static subscriber gets snapshot"); handle.reset();
  received.reset(); replay.publish(merged); check(!received, "detached subscriber released");
  DisplayEncoder markers("/markers", "visualization_msgs/msg/Marker");
  Json::Value m; m["id"] = 1; m["ns"] = "test"; m["action"] = 0;
  markers.encode(m); m["id"] = 2;
  auto snapshot = parse(markers.encode(m)->bytes);
  check(snapshot["display_snapshot"].size() == 3 && snapshot["display_snapshot"][0]["action"] == 3, "ADDs survive replaced frames");
  check(snapshot["msg"]["id"] == 2, "original fields retained for charts");
  m["action"] = 2;
  check(parse(markers.encode(m)->bytes)["display_snapshot"].size() == 2, "DELETE removes only one marker");
  m["action"] = 3;
  check(parse(markers.encode(m)->bytes)["display_snapshot"].size() == 1, "DELETEALL clears cache");
  Ros1Dynamic decoder("test/Telemetry", "uint32 count\nfloat64[] values\nHeader header\nInner inner\n===\nMSG: std_msgs/Header\nuint32 seq\ntime stamp\nstring frame_id\n===\nMSG: test/Inner\nint8 state\n");
  std::vector<uint8_t> bytes;
  auto append = [&](const auto& value) { const auto* p = reinterpret_cast<const uint8_t*>(&value); bytes.insert(bytes.end(), p, p + sizeof(value)); };
  append(uint32_t(7)); append(uint32_t(2)); append(double(1.25)); append(double(-2.5));
  append(uint32_t(0)); append(uint32_t(777)); append(uint32_t(3)); append(uint32_t(0)); append(int8_t(-1));
  auto decoded = decoder.decode(bytes);
  check(decoded["count"].asUInt() == 7 && decoded["values"][1] == -2.5 && decoded["inner"]["state"] == -1, "custom nested ROS1 fields decoded");
  check(decoded["header"]["stamp"]["nanosec"].asUInt() == 3, "ROS1 time normalized");
  bytes.pop_back(); bool rejected = false; try { decoder.decode(bytes); } catch (...) { rejected = true; }
  check(rejected, "truncated dynamic message rejected");
  check(capabilities("ros2")["stage"].asInt() >= 2, "stage 2 capabilities");
  std::cout << "TF replay, Marker state and generic ROS1 decoding passed\n";
}
