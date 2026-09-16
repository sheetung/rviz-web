#pragma once
#include "rvizweb/protocol.hpp"
#include <chrono>
#include <stdexcept>

namespace rvizweb {
// Capture conversion failures without killing the ROS executor. Errors use the
// same bounded topic lane as samples, never the command acknowledgement queue.
template<class F> FramePtr converted(const std::string& topic, F encode) {
  const auto start = std::chrono::steady_clock::now();
  std::shared_ptr<Frame> frame;
  try { frame = std::const_pointer_cast<Frame>(encode()); }
  catch (const std::exception& e) {
    Json::Value event;
    event["version"] = 2; event["event"] = "topic.error"; event["topic"] = topic;
    event["error"]["code"] = dynamic_cast<const std::length_error*>(&e) ? "conversion_limit" : "conversion_failed";
    event["error"]["message"] = std::string(e.what()).substr(0, 512);
    frame = std::const_pointer_cast<Frame>(text_frame(event));
    frame->conversion_error = true;
  }
  frame->topic = topic;
  frame->conversion_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
  return frame;
}
} // namespace rvizweb
