#pragma once
#include "rvizweb/adapter.hpp"
#include <chrono>
#include <algorithm>
#include <map>
#include <mutex>

namespace rvizweb {
// Snapshot state before enqueueing: dropping an intermediate display frame must
// not drop a TF edge, a Marker ADD, or a DELETE. Each encoder is ROS-thread owned.
class DisplayEncoder {
 public:
  DisplayEncoder(std::string topic, std::string type) : topic_(std::move(topic)), type_(std::move(type)) {}
  FramePtr encode(Json::Value message) {
    const auto now = std::chrono::steady_clock::now();
    Json::Value snapshot;
    if (type_ == "tf2_msgs/msg/TFMessage") {
      for (const auto& transform : message["transforms"]) {
        const auto key = transform["child_frame_id"].asString();
        if (!state_.count(key) && state_.size() >= 1024) throw std::length_error("TF cache limit reached");
        const auto size = json(transform).size();
        const auto previous = sizes_.count(key) ? sizes_.at(key) : 0;
        if (bytes_ - previous + size > 8 * 1024 * 1024) throw std::length_error("TF cache byte limit reached");
        bytes_ = bytes_ - previous + size; sizes_[key] = size;
        state_[key] = transform;
      }
      message["transforms"] = Json::Value(Json::arrayValue);
      for (const auto& entry : state_) message["transforms"].append(entry.second);
    } else if (type_ == "visualization_msgs/msg/Marker" || type_ == "visualization_msgs/msg/MarkerArray") {
      for (auto it = expiry_.begin(); it != expiry_.end();) {
        if (it->second <= now) { auto key = it++->first; erase(key); } else ++it;
      }
      Json::Value markers(Json::arrayValue);
      if (type_ == "visualization_msgs/msg/Marker") markers.append(message);
      else markers = message["markers"];
      for (const auto& marker : markers) {
        const auto key = marker["ns"].asString() + ":" + marker["id"].asString();
        const int action = marker["action"].asInt();
        if (action == 3) { state_.clear(); expiry_.clear(); sizes_.clear(); bytes_ = 0; }
        else if (action == 2) erase(key);
        else if (action == 0) {
          const auto size = json(marker).size();
          const auto previous = sizes_.count(key) ? sizes_.at(key) : 0;
          if ((!state_.count(key) && state_.size() >= 2048) || bytes_ - previous + size > 8 * 1024 * 1024)
            throw std::length_error("Marker cache limit reached");
          bytes_ = bytes_ - previous + size; sizes_[key] = size; state_[key] = marker;
          const auto& life = marker["lifetime"];
          const double seconds = life.get("sec", 0).asDouble() + life.get("nanosec", 0).asDouble() * 1e-9;
          if (seconds > 0) expiry_[key] = now + std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(seconds));
          else expiry_.erase(key);
        }
      }
      for (auto it = expiry_.begin(); it != expiry_.end();) {
        if (it->second <= now) { auto key = it++->first; erase(key); } else ++it;
      }
      snapshot = Json::Value(Json::arrayValue);
      auto& result = snapshot;
      Json::Value clear; clear["action"] = 3; result.append(clear);
      for (const auto& [key, value] : state_) {
        auto marker = value;
        if (expiry_.count(key)) {
          auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(expiry_.at(key) - now).count();
          marker["lifetime"]["sec"] = Json::Int64(ns / 1000000000);
          marker["lifetime"]["nanosec"] = Json::Int64(ns % 1000000000);
        }
        result.append(marker);
      }
    }
    Json::Value event; event["version"] = 2; event["event"] = "topic.message";
    event["topic"] = topic_; event["type"] = type_; event["msg"] = std::move(message);
    if (!snapshot.isNull()) event["display_snapshot"] = std::move(snapshot);
    auto frame = text_frame(event);
    if (frame->bytes.size() > max_frame_bytes) throw std::length_error("Display message exceeds frame limit");
    return frame;
  }
 private:
  void erase(const std::string& key) {
    state_.erase(key); expiry_.erase(key);
    auto it = sizes_.find(key); if (it != sizes_.end()) { bytes_ -= it->second; sizes_.erase(it); }
  }
  std::string topic_, type_;
  std::map<std::string, Json::Value> state_;
  std::map<std::string, std::chrono::steady_clock::time_point> expiry_;
  std::map<std::string, size_t> sizes_;
  size_t bytes_ = 0;
};
// The adapter retains /tf_static for its lifetime, including between WebSocket
// sessions. One merged snapshot contains edges from all static broadcasters.
class ReplayStream {
 public:
  std::shared_ptr<void> attach(Sink sink) {
    auto slot = std::make_shared<Sink>(std::move(sink));
    std::lock_guard<std::mutex> guard(mutex_);
    sinks_.erase(std::remove_if(sinks_.begin(), sinks_.end(), [](const auto& s) { return s.expired(); }), sinks_.end());
    sinks_.push_back(slot);
    if (last_) (*slot)(last_);
    return slot;
  }
  void publish(FramePtr frame) {
    std::lock_guard<std::mutex> guard(mutex_);
    if (!frame->conversion_error && !frame->throttled) last_ = frame;
    for (const auto& weak : sinks_) if (auto sink = weak.lock()) (*sink)(frame);
  }
 private:
  std::mutex mutex_;
  FramePtr last_;
  std::vector<std::weak_ptr<Sink>> sinks_;
};
} // namespace rvizweb
