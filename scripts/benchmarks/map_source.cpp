// Benchmark-only source/probe. Publishes XYZ maps on an isolated test topic.
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <chrono>
#include <fstream>
#include <iostream>
#include <thread>
#include <cstring>
#include <vector>
#include <cmath>
using Clock = std::chrono::steady_clock;
int64_t wall_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count(); }
int main(int argc, char** argv) {
  if (argc < 3) { std::cerr << "map_source probe LOG | publish XYZ POINTS HZ LOG\n"; return 2; }
  try {
    rclcpp::init(0, nullptr);
    auto node = std::make_shared<rclcpp::Node>(std::string("map_bench_") + argv[1]);
    auto qos = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort().durability_volatile();
    if (std::string(argv[1]) == "probe") {
      std::ofstream log(argv[2]);
      auto sub = node->create_subscription<sensor_msgs::msg::PointCloud2>("/benchmark/map", qos,
        [&log](sensor_msgs::msg::PointCloud2::ConstSharedPtr m) {
          log << wall_ns() << ',' << (int64_t(m->header.stamp.sec)*1000000000LL+m->header.stamp.nanosec) << '\n';
        });
      rclcpp::spin(node);
    } else {
      if (argc != 6) throw std::runtime_error("Expected XYZ POINTS HZ LOG");
      std::ifstream input(argv[2], std::ios::binary | std::ios::ate);
      if (!input) throw std::runtime_error("Cannot read XYZ file");
      const auto size = static_cast<size_t>(input.tellg());
      if (!size || size % 12) throw std::runtime_error("Expected packed float32 XYZ");
      std::vector<uint8_t> original(size); input.seekg(0); input.read(reinterpret_cast<char*>(original.data()), size);
      const auto count = std::stoul(argv[3]); const auto hz = std::stod(argv[4]);
      if (!count || count > 1600000 || !std::isfinite(hz) || hz <= 0 || hz > 1000) throw std::runtime_error("Invalid load");
      sensor_msgs::msg::PointCloud2 m; m.header.frame_id = "map"; m.height=1; m.width=count;
      m.point_step=12; m.row_step=count*12; m.is_dense=true; m.is_bigendian=false; m.data.resize(count*12);
      for (size_t i=0; i<count; ++i) {
        // Uniform thinning below native size; tiled original samples above it.
        const size_t source = count <= size/12 ? i*(size/12)/count : i%(size/12);
        std::memcpy(m.data.data()+i*12, original.data()+source*12, 12);
      }
      for (unsigned i=0; i<3; ++i) { sensor_msgs::msg::PointField f; f.name=std::string(1,"xyz"[i]); f.offset=i*4; f.datatype=7; f.count=1; m.fields.push_back(f); }
      auto pub = node->create_publisher<sensor_msgs::msg::PointCloud2>("/benchmark/map", qos);
      std::ofstream log(argv[5]);
      const auto period = std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(1.0/hz));
      auto next = Clock::now();
      while (rclcpp::ok()) {
        const auto stamp = wall_ns(); m.header.stamp.sec=stamp/1000000000LL; m.header.stamp.nanosec=stamp%1000000000LL;
        pub->publish(m); log << wall_ns() << ',' << stamp << '\n';
        next += period;
        if (next < Clock::now()) next=Clock::now(); // Never catch up with a burst.
        std::this_thread::sleep_until(next);
      }
    }
    rclcpp::shutdown();
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
