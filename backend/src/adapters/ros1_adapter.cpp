#include <geometry_msgs/PoseStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/Twist.h>
#include "rvizweb/adapter.hpp"
#include "rvizweb/messages.hpp"
#include "rvizweb/conversion.hpp"
#include "rvizweb/pointcloud_processing.hpp"
#include "rvizweb/control.hpp"
#include "rvizweb/display.hpp"
#include "ros1_dynamic.hpp"
#include <topic_tools/shape_shifter.h>
#include <regex>
#include <ros/ros.h>
#include <ros/master.h>
#include <sensor_msgs/PointCloud2.h>
#include <nav_msgs/Odometry.h>
#include <iostream>

namespace rvizweb {

class Ros1Publisher final : public RosPublisher {
 public:
  Ros1Publisher(ros::NodeHandle& node, const std::string& topic, std::string type) : type_(std::move(type)) {
    if (type_ == "geometry_msgs/msg/PoseStamped") publisher_ = node.advertise<geometry_msgs::PoseStamped>(topic, 1, false);
    else if (type_ == "geometry_msgs/msg/PoseWithCovarianceStamped") publisher_ = node.advertise<geometry_msgs::PoseWithCovarianceStamped>(topic, 1, false);
    else publisher_ = node.advertise<geometry_msgs::Twist>(topic, 1, false);
  }
  size_t subscribers() const override { return publisher_.getNumSubscribers(); }
  void publish(const Json::Value& source) override {
    validate_control(type_, source);
    if (type_ == "geometry_msgs/msg/PoseStamped") { geometry_msgs::PoseStamped m; header(m, source); fill_pose(m.pose, source["pose"]); publisher_.publish(m); }
    else if (type_ == "geometry_msgs/msg/PoseWithCovarianceStamped") {
      geometry_msgs::PoseWithCovarianceStamped m; header(m, source); fill_pose(m.pose.pose, source["pose"]["pose"]);
      for (unsigned i = 0; i < 36; ++i) m.pose.covariance[i] = source["pose"]["covariance"][i].asDouble();
      publisher_.publish(m);
    } else { geometry_msgs::Twist m; fill_vector(m.linear, source["linear"]); fill_vector(m.angular, source["angular"]); publisher_.publish(m); }
  }
 private:
  template<class T> void header(T& m, const Json::Value& source) {
    m.header.frame_id = source["header"]["frame_id"].asString();
    if (source["header"].isMember("stamp")) {
      m.header.stamp.sec = source["header"]["stamp"]["sec"].asUInt(); m.header.stamp.nsec = source["header"]["stamp"]["nanosec"].asUInt();
    } else m.header.stamp = ros::Time::now();
  }
  std::string type_;
  ros::Publisher publisher_;
};

class Ros1Adapter final : public RosAdapter {
 public:
  Ros1Adapter() {
    ros::M_string remappings;
    ros::init(remappings, "rvizweb_v2", ros::init_options::NoSigintHandler);
    if (!ros::master::check()) throw std::runtime_error("ROS Master unavailable; start roscore and check ROS_MASTER_URI");
    node_ = std::make_unique<ros::NodeHandle>();
    spinner_ = std::make_unique<ros::AsyncSpinner>(1);
    static_handle_ = generic("/tf_static", "tf2_msgs/msg/TFMessage",
      [stream = static_stream_](FramePtr frame) { stream->publish(std::move(frame)); });
    spinner_->start();
  }
  ~Ros1Adapter() override { stop(); }
  std::string middleware() const override { return "ros1"; }
  bool ready() const override { return ros::ok(); }
  Json::Value topics() override {
    ros::master::V_TopicInfo topics;
    if (!ros::master::getTopics(topics)) throw std::runtime_error("ROS Master unavailable");
    Json::Value list(Json::arrayValue);
    for (const auto& item : topics) {
      auto type = item.datatype;
      const auto slash = type.find('/');
      if (slash != std::string::npos) type.insert(slash, "/msg");
      Json::Value topic;
      topic["name"] = item.name; topic["message_type"] = type;
      topic["supported"] = supports(type);
      topic["publishers"] = Json::Value(Json::arrayValue);
      topic["subscribers"] = Json::Value(Json::arrayValue);
      list.append(topic);
    }
    return list;
  }
  bool supports(const std::string& type) override {
    static const std::regex canonical("[A-Za-z][A-Za-z0-9_]*/msg/[A-Za-z][A-Za-z0-9_]*");
    return type.size() <= 256 && std::regex_match(type, canonical);
  }
  std::shared_ptr<void> subscribe(const std::string& topic, const std::string& type,
                                  const std::string& reliability, const std::string& durability, Sink sink) override {
    if (durability == "transient_local") throw std::invalid_argument("ROS1 uses publisher latching, not DDS durability");
    if (reliability != "auto" && reliability != "best_effort") throw std::invalid_argument("ROS1 does not expose DDS reliability");
    if (topic == "/tf_static" && type == "tf2_msgs/msg/TFMessage") return static_stream_->attach(std::move(sink));
    if (type == "sensor_msgs/msg/PointCloud2") {
      auto encoder = std::make_shared<PointEncoder>();
      auto sub = node_->subscribe<sensor_msgs::PointCloud2>(topic, 1,
        [sink, topic, encoder](const sensor_msgs::PointCloud2::ConstPtr& m) {
          sink(converted(topic, [&] { return encoder->encode(*m, topic, stamp(m->header.stamp.sec, m->header.stamp.nsec)); }));
        });
      return std::make_shared<ros::Subscriber>(std::move(sub));
    }
    if (type == "nav_msgs/msg/Odometry") {
      auto sub = node_->subscribe<nav_msgs::Odometry>(topic, 1,
        [sink, topic](const nav_msgs::Odometry::ConstPtr& m) {
          sink(converted(topic, [&] { return odometry(*m, topic, stamp(m->header.stamp.sec, m->header.stamp.nsec)); }));
        });
      return std::make_shared<ros::Subscriber>(std::move(sub));
    }
    return generic(topic, type, std::move(sink));
  }
  std::shared_ptr<RosPublisher> advertise(const std::string& topic, const std::string& type) override {
    if (!publish_type(type)) throw std::invalid_argument("Unsupported publish type");
    return std::make_shared<Ros1Publisher>(*node_, topic, type);
  }
  void stop() override {
    if (spinner_) spinner_->stop();
    if (ros::ok()) ros::shutdown();
  }
 private:
  std::shared_ptr<void> generic(const std::string& topic, std::string type, Sink sink) {
    auto encoder = std::make_shared<DisplayEncoder>(topic, type);
    type.erase(type.find("/msg"), 4);
    const auto depth = type == "tf2_msgs/TFMessage" || type.find("visualization_msgs/") == 0 ? 100 : 1;
    auto sub = node_->subscribe<topic_tools::ShapeShifter>(topic, depth,
      [encoder, sink, type, topic, decoder = std::shared_ptr<Ros1Dynamic>{}, definition = std::string{}](const topic_tools::ShapeShifter::ConstPtr& message) mutable {
        sink(converted(topic, [&] {
          if (message->getDataType() != type) throw std::invalid_argument("Publisher type differs from requested type");
          if (!decoder || definition != message->getMessageDefinition()) {
            definition = message->getMessageDefinition(); decoder = std::make_shared<Ros1Dynamic>(type, definition);
          }
          if (message->size() > max_frame_bytes) throw std::length_error("Serialized message exceeds limit");
          std::vector<uint8_t> bytes(message->size());
          ros::serialization::OStream stream(bytes.data(), bytes.size()); message->write(stream);
          return encoder->encode(decoder->decode(bytes));
        }));
      });
    return std::make_shared<ros::Subscriber>(std::move(sub));
  }
  std::shared_ptr<ReplayStream> static_stream_ = std::make_shared<ReplayStream>();
  std::shared_ptr<void> static_handle_;
  std::unique_ptr<ros::NodeHandle> node_;
  std::unique_ptr<ros::AsyncSpinner> spinner_;
};
std::shared_ptr<RosAdapter> make_adapter() { return std::make_shared<Ros1Adapter>(); }
}  // namespace rvizweb
