#include <limits>
#if RVIZWEB_ROS_VERSION == 2
#include <rclcpp/rclcpp.hpp>
#include <tf2_msgs/msg/tf_message.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <nav_msgs/msg/path.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
using Tf = tf2_msgs::msg::TFMessage;
using Scan = sensor_msgs::msg::LaserScan;
using Path = nav_msgs::msg::Path;
using Grid = nav_msgs::msg::OccupancyGrid;
using Marker = visualization_msgs::msg::Marker;
using Markers = visualization_msgs::msg::MarkerArray;
using Numbers = std_msgs::msg::Float64MultiArray;
#else
#include <ros/ros.h>
#include <topic_tools/shape_shifter.h>
#include <tf2_msgs/TFMessage.h>
#include <sensor_msgs/LaserScan.h>
#include <nav_msgs/Path.h>
#include <nav_msgs/OccupancyGrid.h>
#include <visualization_msgs/MarkerArray.h>
#include <std_msgs/Float64MultiArray.h>
using Tf = tf2_msgs::TFMessage;
using Scan = sensor_msgs::LaserScan;
using Path = nav_msgs::Path;
using Grid = nav_msgs::OccupancyGrid;
using Marker = visualization_msgs::Marker;
using Markers = visualization_msgs::MarkerArray;
using Numbers = std_msgs::Float64MultiArray;
#endif

template<class T> void header(T& m) { m.header.frame_id = "map"; m.header.stamp.sec = 777; }
Tf transform(const std::string& child, double x) {
  Tf m; m.transforms.resize(1); auto& t = m.transforms[0]; header(t);
  t.child_frame_id = child; t.transform.translation.x = x; t.transform.rotation.w = 1; return m;
}
Scan scan() {
  Scan m; header(m); m.angle_min = 0; m.angle_max = 1; m.angle_increment = 0.25;
  m.range_min = 0; m.range_max = 10;
  m.ranges = {1, 2, std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN(), 3};
  m.intensities = {10,20,30,40,50}; return m;
}
Path path() {
  Path m; header(m); m.poses.resize(2);
  for (int i = 0; i < 2; ++i) { header(m.poses[i]); m.poses[i].pose.position.x = i + 1; m.poses[i].pose.orientation.w = 1; }
  return m;
}
Grid grid() {
  Grid m; header(m); m.info.width = 2; m.info.height = 2; m.info.resolution = 0.5;
  m.info.origin.orientation.w = 1; m.data = {-1, 0, 50, 100}; return m;
}
Marker marker(int id) {
  Marker m; header(m); m.ns = "fixture"; m.id = id; m.type = 1; m.action = 0;
  m.pose.position.x = id; m.pose.orientation.w = 1; m.scale.x = m.scale.y = m.scale.z = 0.3;
  m.color.r = 1; m.color.a = 1; m.text = "fixture"; return m;
}
Numbers numbers() {
  Numbers m; m.layout.dim.resize(1); m.layout.dim[0].label = "voltage"; m.layout.dim[0].size = 3;
  m.layout.dim[0].stride = 3; m.data = {1.25, -2.5, 42}; return m;
}
int main(int argc, char** argv) {
#if RVIZWEB_ROS_VERSION == 2
  rclcpp::init(argc, argv); auto node = std::make_shared<rclcpp::Node>("rvizweb_display_fixture");
#define PUB(T, name, latched) node->create_publisher<T>(name, latched ? rclcpp::QoS(10).reliable().transient_local() : rclcpp::QoS(10).best_effort())
#define SEND(p, m) p->publish(m)
#else
  ros::init(argc, argv, "rvizweb_display_fixture"); ros::NodeHandle node;
#define PUB(T, name, latched) node.advertise<T>(name, 10, latched)
#define SEND(p, m) p.publish(m)
#endif
  auto tf = PUB(Tf, "/tf", false);
  auto stat = PUB(Tf, "/tf_static", true);
  auto stat2 = PUB(Tf, "/tf_static", true);
  auto scans = PUB(Scan, "/v2_test/scan", false);
  auto paths = PUB(Path, "/v2_test/path", false);
  auto maps = PUB(Grid, "/v2_test/map", true);
  auto volatile_maps = PUB(Grid, "/v2_test/map_volatile", false);
  auto marks = PUB(Marker, "/v2_test/marker", false);
  auto arrays = PUB(Markers, "/v2_test/markers", false);
#if RVIZWEB_ROS_VERSION == 2
  auto best_effort_map = node->create_publisher<Grid>("/v2_test/map_best_effort", rclcpp::QoS(1).best_effort().transient_local());
#endif
  auto values = PUB(Numbers, "/v2_test/numbers", false);
#if RVIZWEB_ROS_VERSION == 1
  topic_tools::ShapeShifter custom;
  custom.morph("12345678901234567890123456789012", "rvizweb_test_interfaces/Telemetry",
      "float64 voltage\ngeometry_msgs/Vector3 velocity\nfloat32[] samples\nbool[] flags\nstring label\n===\nMSG: geometry_msgs/Vector3\nfloat64 x\nfloat64 y\nfloat64 z\n", "1");
  std::vector<uint8_t> bytes;
  auto append = [&](const auto& value) { const auto* p = reinterpret_cast<const uint8_t*>(&value); bytes.insert(bytes.end(), p, p + sizeof(value)); };
  append(double(24.5)); append(double(-1.25)); append(double(0)); append(double(0));
  append(uint32_t(3)); append(float(1)); append(float(2)); append(float(3));
  append(uint32_t(2)); append(uint8_t(1)); append(uint8_t(0));
  std::string label = "自定义测试"; append(uint32_t(label.size())); bytes.insert(bytes.end(), label.begin(), label.end());
  ros::serialization::IStream wire(bytes.data(), bytes.size()); custom.read(wire);
  auto custom_pub = custom.advertise(node, "/v2_test/custom", 1, true);
#endif
  unsigned tick = 0;
  auto step = [&] {
    if (++tick == 20) { SEND(stat, transform("static_a", 4)); SEND(stat2, transform("static_b", 5)); SEND(maps, grid()); }
    SEND(tf, transform(tick % 2 ? "moving_a" : "moving_b", 6));
    SEND(scans, scan()); SEND(paths, path()); SEND(volatile_maps, grid());
    SEND(marks, marker(tick % 2));
    Markers m; m.markers.push_back(marker(2)); m.markers.push_back(marker(3)); SEND(arrays, m);
#if RVIZWEB_ROS_VERSION == 2
    best_effort_map->publish(grid());
#endif
    SEND(values, numbers());
#if RVIZWEB_ROS_VERSION == 1
    custom_pub.publish(custom);
#endif
  };
#if RVIZWEB_ROS_VERSION == 2
  auto timer = node->create_wall_timer(std::chrono::milliseconds(100), step);
  rclcpp::spin(node); rclcpp::shutdown();
#else
  ros::Rate rate(10); while (ros::ok()) { step(); ros::spinOnce(); rate.sleep(); }
#endif
}
