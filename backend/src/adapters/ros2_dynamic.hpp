#pragma once
#include "rvizweb/messages.hpp"
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/typesupport_helpers.hpp>
#include <rmw/rmw.h>
#include <rosidl_typesupport_introspection_cpp/message_introspection.hpp>
#include <rosidl_typesupport_introspection_cpp/field_types.hpp>
#include <codecvt>
#include <locale>
namespace rvizweb {
class Ros2Dynamic {
  using Members = rosidl_typesupport_introspection_cpp::MessageMembers;
  using Member = rosidl_typesupport_introspection_cpp::MessageMember;
 public:
  explicit Ros2Dynamic(const std::string& type) {
    introspection_ = rclcpp::get_typesupport_library(type, "rosidl_typesupport_introspection_cpp");
    serialization_ = rclcpp::get_typesupport_library(type, "rosidl_typesupport_cpp");
    auto handle = rclcpp::get_typesupport_handle(type, "rosidl_typesupport_introspection_cpp", *introspection_);
    members_ = static_cast<const Members*>(handle->data);
    support_ = rclcpp::get_typesupport_handle(type, "rosidl_typesupport_cpp", *serialization_);
  }
  Json::Value decode(const rclcpp::SerializedMessage& wire) const {
    if (wire.size() > max_frame_bytes) throw std::length_error("Serialized message exceeds limit");
    void* memory = ::operator new(members_->size_of_);
    members_->init_function(memory, rosidl_runtime_cpp::MessageInitialization::ALL);
    std::unique_ptr<void, std::function<void(void*)>> owner(memory, [this](void* p) { members_->fini_function(p); ::operator delete(p); });
    if (rmw_deserialize(&wire.get_rcl_serialized_message(), support_, memory) != RMW_RET_OK)
      throw std::runtime_error("ROS2 deserialization failed");
    size_t budget = 1000000;
    return object(members_, memory, 0, budget);
  }
 private:
  static Json::Value scalar(const Member& m, const void* p, unsigned depth, size_t& budget) {
    using namespace rosidl_typesupport_introspection_cpp;
    if (!budget--) throw std::length_error("Dynamic field count limit reached");
    switch (m.type_id_) {
      case ROS_TYPE_FLOAT: return number(*static_cast<const float*>(p));
      case ROS_TYPE_DOUBLE: return number(*static_cast<const double*>(p));
      case ROS_TYPE_LONG_DOUBLE: return number(*static_cast<const long double*>(p));
      case ROS_TYPE_BOOLEAN: return *static_cast<const bool*>(p);
      case ROS_TYPE_CHAR: case ROS_TYPE_OCTET: case ROS_TYPE_UINT8: return *static_cast<const uint8_t*>(p);
      case ROS_TYPE_INT8: return *static_cast<const int8_t*>(p);
      case ROS_TYPE_WCHAR: case ROS_TYPE_UINT16: return *static_cast<const uint16_t*>(p);
      case ROS_TYPE_INT16: return *static_cast<const int16_t*>(p);
      case ROS_TYPE_UINT32: return *static_cast<const uint32_t*>(p);
      case ROS_TYPE_INT32: return *static_cast<const int32_t*>(p);
      case ROS_TYPE_UINT64: return Json::UInt64(*static_cast<const uint64_t*>(p));
      case ROS_TYPE_INT64: return Json::Int64(*static_cast<const int64_t*>(p));
      case ROS_TYPE_STRING: return *static_cast<const std::string*>(p);
      case ROS_TYPE_WSTRING: return std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t>{}.to_bytes(*static_cast<const std::u16string*>(p));
      case ROS_TYPE_MESSAGE: return object(static_cast<const Members*>(m.members_->data), p, depth + 1, budget);
      default: throw std::invalid_argument("Unsupported introspection field");
    }
  }
  static Json::Value object(const Members* members, const void* p, unsigned depth, size_t& budget) {
    if (depth > 32) throw std::length_error("Dynamic nesting limit reached");
    Json::Value result(Json::objectValue);
    for (uint32_t i = 0; i < members->member_count_; ++i) {
      const auto& m = members->members_[i];
      const auto* field = static_cast<const uint8_t*>(p) + m.offset_;
      if (!m.is_array_) result[m.name_] = scalar(m, field, depth, budget);
      else {
        const size_t n = m.size_function(field);
        if (n > budget) throw std::length_error("Dynamic array limit reached");
        auto& array = result[m.name_]; array = Json::Value(Json::arrayValue);
        for (size_t j = 0; j < n; ++j) {
          // vector<bool> has no addressable elements; introspection fetch copies it.
          if (m.type_id_ == rosidl_typesupport_introspection_cpp::ROS_TYPE_BOOLEAN && m.fetch_function) {
            bool value; m.fetch_function(field, j, &value); --budget; array.append(value);
          } else array.append(scalar(m, m.get_const_function(field, j), depth, budget));
        }
      }
    }
    return result;
  }
  std::shared_ptr<rcpputils::SharedLibrary> introspection_, serialization_;
  const Members* members_;
  const rosidl_message_type_support_t* support_;
};
} // namespace rvizweb
