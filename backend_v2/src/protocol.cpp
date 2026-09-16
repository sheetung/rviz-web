#include "rvizweb/protocol.hpp"
#include <algorithm>
#include <stdexcept>

namespace rvizweb {
std::string json(const Json::Value& value) {
  Json::StreamWriterBuilder writer;
  writer["indentation"] = "";
  writer["useSpecialFloats"] = false;
  return Json::writeString(writer, value);
}
Json::Value parse(const std::string& text) {
  Json::CharReaderBuilder builder;
  builder["rejectDupKeys"] = true;
  builder["failIfExtra"] = true;
  builder["allowComments"] = false;
  builder["stackLimit"] = 32;
  auto reader = std::unique_ptr<Json::CharReader>(builder.newCharReader());
  Json::Value result;
  std::string error;
  if (!reader->parse(text.data(), text.data() + text.size(), &result, &error) || !result.isObject())
    throw std::invalid_argument("Expected a JSON object");
  return result;
}
FramePtr text_frame(const Json::Value& value) {
  return std::make_shared<Frame>(Frame{false, json(value), {}});
}
FramePtr pointcloud_frame(Json::Value metadata, const std::vector<uint8_t>& data) {
  metadata["op"] = "publish"; // Existing RVPC decoder contract, not a rosbridge dependency.
  metadata["version"] = 2;
  metadata["msg"]["data_encoding"] = "pointcloud-binary-v1";
  metadata["msg"].removeMember("data");
  const auto header = json(metadata);
  const std::size_t offset = (12 + header.size() + 3) & ~std::size_t(3);
  if (offset + data.size() > max_frame_bytes) throw std::length_error("PointCloud2 exceeds frame limit");
  std::string wire(offset, '\0');
  wire.replace(0, 4, "RVPC");
  wire[4] = 1;
  for (unsigned i = 0; i < 4; ++i) wire[8 + i] = static_cast<char>((header.size() >> (8 * i)) & 0xff);
  wire.replace(12, header.size(), header);
  if (!data.empty()) wire.append(reinterpret_cast<const char*>(data.data()), data.size());
  return std::make_shared<Frame>(Frame{true, std::move(wire), {}});
}
bool supported_type(const std::string& type) {
  for (const auto* item : {"sensor_msgs/msg/PointCloud2", "nav_msgs/msg/Odometry", "tf2_msgs/msg/TFMessage",
      "sensor_msgs/msg/LaserScan", "nav_msgs/msg/Path", "visualization_msgs/msg/Marker",
      "visualization_msgs/msg/MarkerArray", "nav_msgs/msg/OccupancyGrid"}) if (type == item) return true;
  return false;
}
Json::Value capabilities(const std::string& middleware) {
  Json::Value value(Json::objectValue);
  value["protocol_version"] = 2;
  value["backend_version"] = "2.0.0-dev.5";
  value["middleware"] = middleware;
  value["stage"] = 5;
  value["shared_subscriptions"] = true;
  value["max_shared_streams"] = 64;
  value["pointcloud_processing_config"] = "environment";
  value["topic_error_events"] = true;
  value["read_only"] = false;
  value["max_frame_bytes"] = Json::UInt64(max_frame_bytes);
  value["max_subscriptions"] = 32;
  value["transports"].append("json");
  value["transports"].append("pointcloud-binary-v1");
  value["message_types"].append("sensor_msgs/msg/PointCloud2");
  for (const auto* type : {"nav_msgs/msg/Odometry", "tf2_msgs/msg/TFMessage", "sensor_msgs/msg/LaserScan",
      "nav_msgs/msg/Path", "visualization_msgs/msg/Marker", "visualization_msgs/msg/MarkerArray", "nav_msgs/msg/OccupancyGrid"}) value["message_types"].append(type);
  for (const auto* type : {"geometry_msgs/msg/PoseStamped", "geometry_msgs/msg/PoseWithCovarianceStamped", "geometry_msgs/msg/Twist"}) value["publish_types"].append(type);
  value["publish_ack"] = "local_submission";
  value["command_replay"] = false;
  value["max_publishers"] = 16;
  value["dynamic_messages"] = true;
  value["static_tf_snapshot"] = true;
  value["marker_snapshots"] = true;
  value["durability"].append("auto"); value["durability"].append("volatile");
  if (middleware == "ros2") value["durability"].append("transient_local");
  for (const auto* method : {"ping", "capabilities", "topics.list", "topics.subscribe", "topics.unsubscribe", "topics.advertise", "topics.unadvertise", "topics.publish", "session.stats", "streams.stats"})
    value["methods"].append(method);
  value["reliability"].append("auto");
  if (middleware == "ros2") {
    value["reliability"].append("best_effort");
    value["reliability"].append("reliable");
  }
  return value;
}
bool Outbox::control(FramePtr frame) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (control_.size() >= 32 || frame->bytes.size() + control_bytes_ > 1024 * 1024) return false;
  control_bytes_ += frame->bytes.size();
  control_.push_back(std::move(frame));
  return true;
}
bool Outbox::data(const std::string& topic, FramePtr frame,
                  const std::shared_ptr<std::atomic_bool>& active) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!active->load()) return false;
  if (frame->bytes.size() > max_frame_bytes) { ++dropped_; ++oversized_; ++topic_drops_[topic]; return false; }
  const auto old = data_.find(topic);
  if (old != data_.end()) {
    data_bytes_ -= old->second->bytes.size();
    data_.erase(old);
    order_.erase(std::find(order_.begin(), order_.end(), topic));
    ++dropped_; ++replaced_; ++topic_drops_[topic];
  }
  while (!order_.empty() && (data_.size() >= 8 || data_bytes_ + frame->bytes.size() > 32 * 1024 * 1024)) {
    ++topic_drops_[order_.front()];
    data_bytes_ -= data_.at(order_.front())->bytes.size();
    data_.erase(order_.front());
    order_.pop_front();
    ++dropped_; ++evicted_;
  }
  data_bytes_ += frame->bytes.size();
  data_[topic] = std::move(frame);
  order_.push_back(topic);
  return true;
}
FramePtr Outbox::pop() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!control_.empty()) {
    auto result = control_.front();
    control_.pop_front();
    control_bytes_ -= result->bytes.size();
    return result;
  }
  if (order_.empty()) return {};
  const auto topic = order_.front();
  order_.pop_front();
  auto result = data_.at(topic);
  data_bytes_ -= result->bytes.size();
  data_.erase(topic);
  return result;
}
void Outbox::erase(const std::string& topic) {
  std::lock_guard<std::mutex> lock(mutex_);
  topic_drops_.erase(topic);
  auto found = data_.find(topic);
  if (found == data_.end()) return;
  data_bytes_ -= found->second->bytes.size();
  data_.erase(found);
  order_.erase(std::find(order_.begin(), order_.end(), topic));
}
void Outbox::clear() {
  std::lock_guard<std::mutex> lock(mutex_);
  control_.clear(); data_.clear(); order_.clear(); topic_drops_.clear();
  data_bytes_ = control_bytes_ = 0;
}
uint64_t Outbox::dropped() const { std::lock_guard<std::mutex> lock(mutex_); return dropped_; }
Json::Value Outbox::stats() const {
  std::lock_guard<std::mutex> lock(mutex_);
  Json::Value j;
  j["data_bytes"] = Json::UInt64(data_bytes_); j["control_bytes"] = Json::UInt64(control_bytes_);
  j["data_topics"] = Json::UInt64(data_.size()); j["control_messages"] = Json::UInt64(control_.size());
  j["replaced_frames"] = Json::UInt64(replaced_); j["evicted_frames"] = Json::UInt64(evicted_);
  j["oversized_frames"] = Json::UInt64(oversized_);
  j["dropped_by_topic"] = Json::Value(Json::objectValue);
  for (const auto& item : topic_drops_) j["dropped_by_topic"][item.first] = Json::UInt64(item.second);
  j["pending_bytes_by_topic"] = Json::Value(Json::objectValue);
  for (const auto& item : data_) j["pending_bytes_by_topic"][item.first] = Json::UInt64(item.second->bytes.size());
  return j;
}
}  // namespace rvizweb
