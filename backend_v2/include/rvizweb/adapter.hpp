#pragma once
#include "rvizweb/protocol.hpp"
#include <functional>
namespace rvizweb {
using Sink = std::function<void(FramePtr)>;
class RosPublisher {
 public:
  virtual ~RosPublisher() = default;
  virtual size_t subscribers() const = 0;
  // Returns after local middleware submission, not remote execution.
  virtual void publish(const Json::Value& message) = 0;
};
class RosAdapter {
 public:
  virtual ~RosAdapter() = default;
  virtual std::string middleware() const = 0;
  virtual bool ready() const = 0;
  virtual Json::Value topics() = 0;
  virtual Json::Value metrics() { return Json::Value(Json::objectValue); }
  virtual bool supports(const std::string& type) = 0;
  virtual std::shared_ptr<void> subscribe(const std::string& topic, const std::string& type,
                                         const std::string& reliability, const std::string& durability, Sink sink) = 0;
  virtual std::shared_ptr<RosPublisher> advertise(const std::string& topic, const std::string& type) = 0;
  virtual void stop() = 0;
};
std::shared_ptr<RosAdapter> make_adapter();
}  // namespace rvizweb
