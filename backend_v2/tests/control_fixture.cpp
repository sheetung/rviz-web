#include "rvizweb/messages.hpp"
#include <fstream>
#include <iostream>
#if RVIZWEB_ROS_VERSION == 2
#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist.hpp>
using Goal = geometry_msgs::msg::PoseStamped;
using Initial = geometry_msgs::msg::PoseWithCovarianceStamped;
using Twist = geometry_msgs::msg::Twist;
#else
#include <ros/ros.h>
#include <geometry_msgs/PoseStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/Twist.h>
using Goal = geometry_msgs::PoseStamped;
using Initial = geometry_msgs::PoseWithCovarianceStamped;
using Twist = geometry_msgs::Twist;
#endif
using namespace rvizweb;
template<class T> Json::Value header(const T& m) {
  Json::Value j; j["frame_id"] = m.header.frame_id;
#if RVIZWEB_ROS_VERSION == 2
  j["stamp"] = stamp(m.header.stamp.sec, m.header.stamp.nanosec);
#else
  j["stamp"] = stamp(m.header.stamp.sec, m.header.stamp.nsec);
#endif
  return j;
}
template<class T> Json::Value pose(const T& m) {
  Json::Value j; j["position"] = vector(m.position); j["orientation"] = quaternion(m.orientation); return j;
}
void record(const std::string& topic, const Json::Value& message) {
  Json::Value event; event["topic"] = topic; event["msg"] = message;
  std::cout << json(event) << std::endl;
}
int main(int argc, char** argv) {
  const std::string late_flag = argc > 1 ? argv[1] : "/tmp/rviz-v3-late-subscriber";
  auto goal_callback = [](const std::string& topic) { return [topic](auto m) {
    Json::Value j; j["header"] = header(*m); j["pose"] = pose(m->pose); record(topic, j);
  }; };
  auto initial_callback = [](const std::string& topic) { return [topic](auto m) {
    Json::Value j; j["header"] = header(*m); j["pose"]["pose"] = pose(m->pose.pose);
    j["pose"]["covariance"] = numbers(m->pose.covariance); record(topic, j);
  }; };
#if RVIZWEB_ROS_VERSION == 2
  rclcpp::init(argc, argv); auto node = std::make_shared<rclcpp::Node>("rvizweb_control_receiver");
#define SUB(T, topic, callback) node->create_subscription<T>(topic, rclcpp::QoS(100).reliable().durability_volatile(), callback)
#else
  ros::init(argc, argv, "rvizweb_control_receiver"); ros::NodeHandle node;
#define SUB(T, topic, callback) node.subscribe<T>(topic, 100, callback)
#endif
  // Concrete pointer signatures work in both roscpp and rclcpp.
#if RVIZWEB_ROS_VERSION == 2
  using GoalPtr = Goal::ConstSharedPtr; using InitialPtr = Initial::ConstSharedPtr; using TwistPtr = Twist::ConstSharedPtr;
#else
  using GoalPtr = Goal::ConstPtr; using InitialPtr = Initial::ConstPtr; using TwistPtr = Twist::ConstPtr;
#endif
  auto g = SUB(Goal, "/v3_test/goal", [goal_callback](GoalPtr m) { goal_callback("/v3_test/goal")(m); });
  auto default_g = SUB(Goal, "/goal_pose", [goal_callback](GoalPtr m) { goal_callback("/goal_pose")(m); });
  auto i = SUB(Initial, "/v3_test/initialpose", [initial_callback](InitialPtr m) { initial_callback("/v3_test/initialpose")(m); });
  auto default_i = SUB(Initial, "/initialpose", [initial_callback](InitialPtr m) { initial_callback("/initialpose")(m); });
  auto t = SUB(Twist, "/v3_test/cmd_vel", [](TwistPtr m) { Json::Value j; j["linear"] = vector(m->linear); j["angular"] = vector(m->angular); record("/v3_test/cmd_vel", j); });
  decltype(g) late;
  size_t previous_count = size_t(-1);
  auto step = [&] {
    if (!late && std::ifstream(late_flag).good()) late = SUB(Goal, "/v3_test/late", [goal_callback](GoalPtr m) { goal_callback("/v3_test/late")(m); });
#if RVIZWEB_ROS_VERSION == 2
    const auto count = g->get_publisher_count();
#else
    const auto count = g.getNumPublishers();
#endif
    if (count != previous_count) {
      Json::Value j; j["kind"] = "graph"; j["goal_publishers"] = Json::UInt64(count); std::cout << json(j) << std::endl;
      previous_count = count;
    }
  };
#if RVIZWEB_ROS_VERSION == 2
  auto timer = node->create_wall_timer(std::chrono::milliseconds(50), step); rclcpp::spin(node); rclcpp::shutdown();
#else
  ros::Rate rate(20); while (ros::ok()) { ros::spinOnce(); step(); rate.sleep(); }
#endif
}
