#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include "rvizweb/adapter.hpp"
#include "rvizweb/messages.hpp"
#include "rvizweb/control.hpp"
#include "rvizweb/display.hpp"
#include "rvizweb/ros2_dynamic.hpp"
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <iostream>
#include <thread>
#include <regex>

namespace rvizweb {

class Ros2Publisher final : public RosPublisher {
 public:
  Ros2Publisher(rclcpp::Node::SharedPtr node, const std::string& topic, std::string type) : node_(node), type_(std::move(type)) {
    auto qos = rclcpp::QoS(1).reliable().durability_volatile();
    if (type_ == "geometry_msgs/msg/PoseStamped") goal_ = node->create_publisher<geometry_msgs::msg::PoseStamped>(topic, qos);
    else if (type_ == "geometry_msgs/msg/PoseWithCovarianceStamped") initial_ = node->create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>(topic, qos);
    else twist_ = node->create_publisher<geometry_msgs::msg::Twist>(topic, qos);
  }
  size_t subscribers() const override {
    return goal_ ? goal_->get_subscription_count() : initial_ ? initial_->get_subscription_count() : twist_->get_subscription_count();
  }
  void publish(const Json::Value& source) override {
    validate_control(type_, source);
    if (goal_) { geometry_msgs::msg::PoseStamped m; header(m, source); fill_pose(m.pose, source["pose"]); goal_->publish(m); }
    else if (initial_) {
      geometry_msgs::msg::PoseWithCovarianceStamped m; header(m, source); fill_pose(m.pose.pose, source["pose"]["pose"]);
      for (unsigned i = 0; i < 36; ++i) m.pose.covariance[i] = source["pose"]["covariance"][i].asDouble();
      initial_->publish(m);
    } else { geometry_msgs::msg::Twist m; fill_vector(m.linear, source["linear"]); fill_vector(m.angular, source["angular"]); twist_->publish(m); }
  }
 private:
  template<class T> void header(T& m, const Json::Value& source) {
    m.header.frame_id = source["header"]["frame_id"].asString();
    if (source["header"].isMember("stamp")) {
      m.header.stamp.sec = source["header"]["stamp"]["sec"].asInt(); m.header.stamp.nanosec = source["header"]["stamp"]["nanosec"].asUInt();
    } else m.header.stamp = node_->now();
  }
  rclcpp::Node::SharedPtr node_;
  std::string type_;
  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr goal_;
  rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr initial_;
  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr twist_;
};

class Ros2Adapter final : public RosAdapter {
 public:
  Ros2Adapter() {
    rclcpp::init(0, nullptr, rclcpp::InitOptions(), rclcpp::SignalHandlerOptions::None);
    node_ = std::make_shared<rclcpp::Node>("rvizweb_v2");
    executor_ = std::make_unique<rclcpp::executors::SingleThreadedExecutor>();
    executor_->add_node(node_);
    // Subscribe before clients connect; ROS2 static publishers offer transient-local history.
    static_handle_ = generic("/tf_static", "tf2_msgs/msg/TFMessage", rclcpp::QoS(100).reliable().transient_local(),
      [stream = static_stream_](FramePtr frame) { stream->publish(std::move(frame)); });
    thread_ = std::thread([this] {
      try { executor_->spin(); }
      catch (const std::exception& e) { std::cerr << "ROS executor: " << e.what() << '\n'; }
      running_ = false;
    });
  }
  ~Ros2Adapter() override { stop(); }
  std::string middleware() const override { return "ros2"; }
  bool ready() const override { return running_ && rclcpp::ok(); }
  Json::Value topics() override {
    Json::Value list(Json::arrayValue);
    for (const auto& [name, types] : node_->get_topic_names_and_types()) {
      for (const auto& type : types) {
        Json::Value topic;
        topic["name"] = name; topic["message_type"] = type;
        topic["supported"] = supports(type);
        topic["publishers"] = Json::Value(Json::arrayValue);
        topic["subscribers"] = Json::Value(Json::arrayValue);
        list.append(topic);
      }
    }
    return list;
  }
  bool supports(const std::string& type) override {
    static const std::regex canonical("[A-Za-z][A-Za-z0-9_]*/msg/[A-Za-z][A-Za-z0-9_]*");
    if (type.size() > 256 || !std::regex_match(type, canonical)) return false;
    if (type == "sensor_msgs/msg/PointCloud2" || type == "nav_msgs/msg/Odometry") return true;
    try { Ros2Dynamic probe(type); return true; } catch (...) { return false; }
  }
  std::shared_ptr<void> subscribe(const std::string& topic, const std::string& type,
                                  const std::string& reliability, const std::string& durability, Sink sink) override {
    if (reliability != "auto" && reliability != "best_effort" && reliability != "reliable") throw std::invalid_argument("Unsupported reliability");
    if (topic == "/tf_static" && type == "tf2_msgs/msg/TFMessage") {
      if (durability == "volatile" || reliability == "best_effort")
        throw std::invalid_argument("/tf_static requires reliable transient_local QoS");
      return static_stream_->attach(std::move(sink));
    }
    rclcpp::QoS qos(rclcpp::KeepLast(type == "tf2_msgs/msg/TFMessage" || type.find("visualization_msgs/") == 0 ? 100 : 1));
    qos.durability_volatile();
    if (reliability == "best_effort" || reliability == "auto") qos.best_effort();
    else if (reliability == "reliable") qos.reliable();
    else throw std::invalid_argument("Unsupported reliability");
    bool transient = durability == "transient_local";
    const auto publishers = node_->get_publishers_info_by_topic(topic);
    if (durability == "auto") {
      transient = !publishers.empty() && std::all_of(publishers.begin(), publishers.end(), [](const auto& info) {
        return info.qos_profile().durability() == rclcpp::DurabilityPolicy::TransientLocal;
      });
    }
    if (transient) {
      qos.transient_local();
      if (reliability == "auto" && std::all_of(publishers.begin(), publishers.end(), [](const auto& info) {
        return info.qos_profile().reliability() == rclcpp::ReliabilityPolicy::Reliable;
      })) qos.reliable();
    }
    if (type == "sensor_msgs/msg/PointCloud2") {
      return node_->create_subscription<sensor_msgs::msg::PointCloud2>(topic, qos,
        [sink, topic](sensor_msgs::msg::PointCloud2::ConstSharedPtr m) {
          try { sink(pointcloud(*m, topic, stamp(m->header.stamp.sec, m->header.stamp.nanosec))); }
          catch (const std::exception& e) { std::cerr << "PointCloud2 skipped: " << e.what() << '\n'; }
        });
    }
    if (type == "nav_msgs/msg/Odometry") {
      return node_->create_subscription<nav_msgs::msg::Odometry>(topic, qos,
        [sink, topic](nav_msgs::msg::Odometry::ConstSharedPtr m) {
          sink(odometry(*m, topic, stamp(m->header.stamp.sec, m->header.stamp.nanosec)));
        });
    }
    return generic(topic, type, qos, std::move(sink));
  }
  std::shared_ptr<RosPublisher> advertise(const std::string& topic, const std::string& type) override {
    if (!publish_type(type)) throw std::invalid_argument("Unsupported publish type");
    return std::make_shared<Ros2Publisher>(node_, topic, type);
  }
  void stop() override {
    running_ = false;
    executor_->cancel();
    if (thread_.joinable()) thread_.join();
    if (rclcpp::ok()) rclcpp::shutdown();
  }
 private:
  std::shared_ptr<void> generic(const std::string& topic, const std::string& type, const rclcpp::QoS& qos, Sink sink) {
    auto decoder = std::make_shared<Ros2Dynamic>(type);
    auto encoder = std::make_shared<DisplayEncoder>(topic, type);
    return node_->create_generic_subscription(topic, type, qos,
      [decoder, encoder, sink](std::shared_ptr<rclcpp::SerializedMessage> message) {
        try { sink(encoder->encode(decoder->decode(*message))); }
        catch (const std::exception& e) { std::cerr << "Display message skipped: " << e.what() << '\n'; }
      });
  }
  std::shared_ptr<ReplayStream> static_stream_ = std::make_shared<ReplayStream>();
  std::shared_ptr<void> static_handle_;
  rclcpp::Node::SharedPtr node_;
  std::unique_ptr<rclcpp::executors::SingleThreadedExecutor> executor_;
  std::thread thread_;
  std::atomic_bool running_{true};
};
std::shared_ptr<RosAdapter> make_adapter() { return std::make_shared<Ros2Adapter>(); }
}  // namespace rvizweb
