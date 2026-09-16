#pragma once
#include "rvizweb/messages.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <sstream>
#include <set>
#include <fnmatch.h>

namespace rvizweb {
struct PointOptions {
  double rate = 0, voxel = 0;
  bool crop = false;
  std::array<double, 6> bounds{};
  std::string topics = "*";
  static PointOptions environment() {
    PointOptions o;
    auto read = [](const char* name, double maximum) {
      const auto* value = std::getenv(name);
      if (!value || !*value) return 0.;
      char* end = nullptr; const auto n = std::strtod(value, &end);
      if (*end || end == value || !std::isfinite(n) || n < 0 || n > maximum)
        throw std::invalid_argument(std::string(name) + " is outside its supported range");
      return n;
    };
    o.rate = read("RVIZWEB_POINTCLOUD_MAX_HZ", 200);
    o.voxel = read("RVIZWEB_POINTCLOUD_VOXEL_SIZE", 100);
    if (const auto* value = std::getenv("RVIZWEB_POINTCLOUD_TOPICS")) o.topics = value;
    if (const auto* value = std::getenv("RVIZWEB_POINTCLOUD_CROP")) {
      if (*value) {
        std::string text(value); std::replace(text.begin(), text.end(), ',', ' ');
        std::istringstream in(text);
        for (auto& b : o.bounds) if (!(in >> b) || !std::isfinite(b)) throw std::invalid_argument("Invalid pointcloud crop bounds");
        std::string extra; if (in >> extra) throw std::invalid_argument("Crop requires six values");
        for (int i = 0; i < 3; ++i) if (o.bounds[i] > o.bounds[i + 3]) throw std::invalid_argument("Crop minimum exceeds maximum");
        o.crop = true;
      }
    }
    return o;
  }
  bool matches(const std::string& topic) const {
    std::istringstream in(topics); std::string pattern;
    while (std::getline(in, pattern, ',')) if (fnmatch(pattern.c_str(), topic.c_str(), 0) == 0) return true;
    return false;
  }
  Json::Value json_value() const {
    Json::Value j; j["max_hz"] = rate; j["voxel_size"] = voxel; j["topics"] = topics;
    j["crop"] = Json::Value();
    if (crop) { j["crop"] = Json::Value(Json::arrayValue); for (auto b : bounds) j["crop"].append(b); }
    j["coordinate_frame"] = "source_message_frame";
    j["voxel_selection"] = "first_original_point";
    return j;
  }
};
inline const PointOptions& point_options() { static const auto o = PointOptions::environment(); return o; }

// Retain complete original records, including rgb/intensity/custom fields.
// Enabled filtering makes an unorganized cloud and removes row padding.
template<class T> T filter_points(const T& m, const PointOptions& options) {
  if (!options.crop && options.voxel == 0) return m;
  if (!m.point_step || uint64_t(m.row_step) * m.height != m.data.size() ||
      uint64_t(m.width) * m.point_step > m.row_step) throw std::invalid_argument("Invalid PointCloud2 dimensions");
  if (m.data.size() > max_frame_bytes || uint64_t(m.width) * m.height > 1000000)
    throw std::length_error("Pointcloud processing limit reached");
  std::array<uint32_t, 3> offsets{}, sizes{};
  for (const auto& f : m.fields) for (int i = 0; i < 3; ++i) if (f.name == std::string(1, "xyz"[i])) {
    if (sizes[i] || f.count != 1 || (f.datatype != 7 && f.datatype != 8)) throw std::invalid_argument("XYZ must be unique scalar FLOAT32/FLOAT64 fields");
    offsets[i] = f.offset; sizes[i] = f.datatype == 7 ? 4 : 8;
    if (uint64_t(offsets[i]) + sizes[i] > m.point_step) throw std::invalid_argument("XYZ exceeds point record");
  }
  for (auto size : sizes) if (!size) throw std::invalid_argument("Pointcloud processing requires XYZ");
  T output;
  output.header = m.header; output.fields = m.fields; output.is_bigendian = m.is_bigendian;
  output.point_step = m.point_step; output.height = 1; output.is_dense = true;
  output.data.clear(); output.data.reserve(m.data.size());
  const uint16_t endian = 1;
  const bool swap = bool(m.is_bigendian) == (*reinterpret_cast<const uint8_t*>(&endian) == 1);
  std::set<std::array<int64_t, 3>> voxels;
  for (uint32_t row = 0; row < m.height; ++row) for (uint32_t col = 0; col < m.width; ++col) {
    const auto* point = m.data.data() + size_t(row) * m.row_step + size_t(col) * m.point_step;
    std::array<double, 3> xyz{}; bool keep = true;
    for (int i = 0; i < 3; ++i) {
      std::array<uint8_t, 8> bytes{}; std::memcpy(bytes.data(), point + offsets[i], sizes[i]);
      if (swap) std::reverse(bytes.begin(), bytes.begin() + sizes[i]);
      if (sizes[i] == 4) { float v; std::memcpy(&v, bytes.data(), 4); xyz[i] = v; }
      else std::memcpy(&xyz[i], bytes.data(), 8);
      if (!std::isfinite(xyz[i]) || (options.crop && (xyz[i] < options.bounds[i] || xyz[i] > options.bounds[i + 3]))) keep = false;
    }
    if (!keep) continue;
    if (options.voxel > 0) {
      std::array<int64_t, 3> key{};
      for (int i = 0; i < 3; ++i) {
        const auto n = std::floor(xyz[i] / options.voxel);
        if (!std::isfinite(n) || std::abs(n) > 9e15) throw std::invalid_argument("Voxel coordinate outside supported range");
        key[i] = static_cast<int64_t>(n);
      }
      if (!voxels.insert(key).second) continue;
    }
    output.data.insert(output.data.end(), point, point + m.point_step);
  }
  output.width = output.data.size() / output.point_step; output.row_step = output.data.size();
  return output;
}
class PointEncoder {
 public:
  explicit PointEncoder(PointOptions options = point_options()) : options_(std::move(options)) {}
  template<class T> FramePtr encode(const T& m, const std::string& topic, const Json::Value& time) {
    if (!options_.matches(topic)) return pointcloud(m, topic, time);
    const auto now = std::chrono::steady_clock::now();
    if (options_.rate > 0 && last_ != std::chrono::steady_clock::time_point{} &&
        std::chrono::duration<double>(now - last_).count() < 1 / options_.rate) {
      auto frame = std::make_shared<Frame>(); frame->throttled = true; return frame;
    }
    // Failed conversion must not suppress the next valid sample.
    auto frame = options_.crop || options_.voxel > 0 ? pointcloud(filter_points(m, options_), topic, time) : pointcloud(m, topic, time);
    last_ = now; return frame;
  }
 private:
  PointOptions options_;
  std::chrono::steady_clock::time_point last_{};
};
} // namespace rvizweb
