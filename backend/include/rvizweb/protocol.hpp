#pragma once
#include <json/json.h>
#include <atomic>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace rvizweb {
constexpr std::size_t max_frame_bytes = 16 * 1024 * 1024;
constexpr std::size_t max_request_bytes = 64 * 1024;
struct Frame {
  bool binary = false;
  std::string bytes;
  std::string topic;
  double conversion_ms = 0;
  bool conversion_error = false;
  bool throttled = false;
};
using FramePtr = std::shared_ptr<const Frame>;
std::string json(const Json::Value& value);
Json::Value parse(const std::string& text);
FramePtr text_frame(const Json::Value& value);
FramePtr pointcloud_frame(Json::Value metadata, const std::vector<uint8_t>& data);
Json::Value capabilities(const std::string& middleware);
bool supported_type(const std::string& type);

// One latest sample per topic; control responses have their own bounded FIFO.
// Frames in an active socket write are owned separately and never overwritten.
class Outbox {
 public:
  bool control(FramePtr frame);
  bool data(const std::string& topic, FramePtr frame,
            const std::shared_ptr<std::atomic_bool>& active);
  FramePtr pop();
  void erase(const std::string& topic);
  void clear();
  uint64_t dropped() const;
  Json::Value stats() const;
 private:
  mutable std::mutex mutex_;
  std::deque<FramePtr> control_;
  std::map<std::string, FramePtr> data_;
  std::deque<std::string> order_;
  std::size_t data_bytes_ = 0;
  std::size_t control_bytes_ = 0;
  uint64_t dropped_ = 0;
  uint64_t replaced_ = 0, evicted_ = 0, oversized_ = 0;
  std::map<std::string, uint64_t> topic_drops_;
};
}  // namespace rvizweb
