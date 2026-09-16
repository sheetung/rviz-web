#pragma once
#include "rvizweb/messages.hpp"
#include <map>
#include <sstream>
#include <cstring>
namespace rvizweb {
// Decode ROS1's wire format from the publisher's connection-header definition.
// This supports workspace messages without generating/linking their C++ types.
class Ros1Dynamic {
  struct Field { std::string type, name; int64_t count = -2; };
 public:
  Ros1Dynamic(const std::string& type, const std::string& definition) : root_(type) {
    if (definition.size() > 1024 * 1024) throw std::length_error("Message definition limit reached");
    std::istringstream input(definition); std::string line, current = type;
    fields_[current];
    while (std::getline(input, line)) {
      if (line.rfind("MSG: ", 0) == 0) { current = line.substr(5); fields_[current]; continue; }
      line = line.substr(0, line.find('#'));
      if (line.find('=') != std::string::npos) continue;
      std::istringstream tokens(line); Field f;
      if (!(tokens >> f.type >> f.name)) continue;
      const auto bracket = f.type.find('[');
      if (bracket != std::string::npos) {
        const auto n = f.type.substr(bracket + 1, f.type.size() - bracket - 2);
        f.count = n.empty() ? -1 : std::stoll(n);
        if (f.count > 1000000) throw std::length_error("Fixed array limit reached");
        f.type.resize(bracket);
      }
      if (f.type == "Header") f.type = "std_msgs/Header";
      else if (f.type.find('/') == std::string::npos && !primitive(f.type))
        f.type = current.substr(0, current.find('/')) + "/" + f.type;
      fields_[current].push_back(std::move(f));
    }
  }
  Json::Value decode(const std::vector<uint8_t>& wire) const {
    if (wire.size() > max_frame_bytes) throw std::length_error("Serialized message exceeds limit");
    Cursor c{wire}; auto result = object(root_, c, 0);
    if (c.offset != wire.size()) throw std::invalid_argument("Trailing ROS1 message bytes");
    return result;
  }
 private:
  struct Cursor {
    const std::vector<uint8_t>& bytes; size_t offset = 0, budget = 1000000;
    template<class T> T read() {
      if (bytes.size() - offset < sizeof(T)) throw std::invalid_argument("Truncated ROS1 message");
      uint8_t raw[sizeof(T)]; std::memcpy(raw, bytes.data() + offset, sizeof(T)); offset += sizeof(T);
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
      std::reverse(raw, raw + sizeof(T));
#endif
      T result; std::memcpy(&result, raw, sizeof(T)); return result;
    }
  };
  static bool primitive(const std::string& t) {
    for (const auto* name : {"bool", "byte", "char", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float32", "float64", "string", "time", "duration"}) if (t == name) return true;
    return false;
  }
  Json::Value scalar(const std::string& t, Cursor& c, unsigned depth) const {
    if (!c.budget--) throw std::length_error("Dynamic field count limit reached");
    if (t == "bool") return bool(c.read<uint8_t>());
    if (t == "int8" || t == "byte") return c.read<int8_t>();
    if (t == "uint8" || t == "char") return c.read<uint8_t>();
    if (t == "int16") return c.read<int16_t>();
    if (t == "uint16") return c.read<uint16_t>();
    if (t == "int32") return c.read<int32_t>();
    if (t == "uint32") return c.read<uint32_t>();
    if (t == "int64") return Json::Int64(c.read<int64_t>());
    if (t == "uint64") return Json::UInt64(c.read<uint64_t>());
    if (t == "float32") return number(c.read<float>());
    if (t == "float64") return number(c.read<double>());
    if (t == "time" || t == "duration") {
      Json::Value value;
      if (t == "time") { value["sec"] = c.read<uint32_t>(); value["nanosec"] = c.read<uint32_t>(); }
      else { value["sec"] = c.read<int32_t>(); value["nanosec"] = c.read<int32_t>(); }
      return value;
    }
    if (t == "string") {
      const auto n = c.read<uint32_t>();
      if (n > c.bytes.size() - c.offset) throw std::invalid_argument("Truncated ROS1 string");
      std::string result(reinterpret_cast<const char*>(c.bytes.data() + c.offset), n); c.offset += n; return result;
    }
    return object(t, c, depth + 1);
  }
  Json::Value object(const std::string& type, Cursor& c, unsigned depth) const {
    if (depth > 32) throw std::length_error("Dynamic nesting limit reached");
    const auto found = fields_.find(type);
    if (found == fields_.end()) throw std::invalid_argument("Missing ROS1 message definition: " + type);
    Json::Value result(Json::objectValue);
    for (const auto& f : found->second) {
      if (f.count == -2) result[f.name] = scalar(f.type, c, depth);
      else {
        const auto n = f.count == -1 ? c.read<uint32_t>() : uint64_t(f.count);
        if (n > c.budget) throw std::length_error("Dynamic array limit reached");
        auto& a = result[f.name]; a = Json::Value(Json::arrayValue);
        for (size_t i = 0; i < n; ++i) a.append(scalar(f.type, c, depth));
      }
    }
    return result;
  }
  std::string root_;
  std::map<std::string, std::vector<Field>> fields_;
};
} // namespace rvizweb
