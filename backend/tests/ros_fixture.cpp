#include <cstring>
#if RVIZWEB_ROS_VERSION == 2
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <nav_msgs/msg/odometry.hpp>
using Cloud = sensor_msgs::msg::PointCloud2;
using Odom = nav_msgs::msg::Odometry;
#else
#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>
#include <nav_msgs/Odometry.h>
using Cloud = sensor_msgs::PointCloud2;
using Odom = nav_msgs::Odometry;
#endif

Cloud cloud() {
  Cloud m;
  m.header.frame_id = "map";
  m.header.stamp.sec = 777;
#if RVIZWEB_ROS_VERSION == 2
  m.header.stamp.nanosec = 1234;
#else
  m.header.stamp.nsec = 1234;
#endif
  m.width = 2; m.height = 1; m.point_step = 16; m.row_step = 40;
  m.is_dense = true; m.is_bigendian = false;
  m.fields.resize(4);
  const char* names[] = {"x", "y", "z", "intensity"};
  for (unsigned i = 0; i < 4; ++i) {
    m.fields[i].name = names[i]; m.fields[i].offset = i * 4;
    m.fields[i].datatype = 7; m.fields[i].count = 1;
  }
  m.data.resize(40, 0xa5);
  const float values[] = {1, 2, 3, 42, 4, 5, 6, 84};
  std::memcpy(m.data.data(), values, sizeof(values));
  return m;
}
Odom odometry() {
  Odom m;
  m.header.frame_id = "map"; m.child_frame_id = "base_link";
  m.header.stamp.sec = 777;
  m.pose.pose.position.x = 1.25; m.pose.pose.position.y = -2.5; m.pose.pose.position.z = 3;
  m.pose.pose.orientation.w = 1;
  return m;
}
int main(int argc, char** argv) {
#if RVIZWEB_ROS_VERSION == 2
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("rvizweb_v2_fixture");
  auto pc = node->create_publisher<Cloud>("/v2_test/points", rclcpp::QoS(1).best_effort());
  auto od = node->create_publisher<Odom>("/v2_test/odom", 1);
  auto timer = node->create_wall_timer(std::chrono::milliseconds(100), [&] {
    pc->publish(cloud()); od->publish(odometry());
  });
  rclcpp::spin(node);
  rclcpp::shutdown();
#else
  ros::init(argc, argv, "rvizweb_v2_fixture");
  ros::NodeHandle node;
  auto pc = node.advertise<Cloud>("/v2_test/points", 1);
  auto od = node.advertise<Odom>("/v2_test/odom", 1);
  ros::Rate rate(10);
  while (ros::ok()) { pc.publish(cloud()); od.publish(odometry()); ros::spinOnce(); rate.sleep(); }
#endif
}
