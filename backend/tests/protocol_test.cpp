#include "rvizweb/protocol.hpp"
#include <iostream>
#include <stdexcept>
using namespace rvizweb;
void check(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
int main() {
  Json::Value metadata; metadata["topic"] = "/points";
  metadata["msg"]["fields"][0]["name"] = "intensity";
  const std::vector<uint8_t> data{0, 255, 128, 1, 2};
  const auto binary = pointcloud_frame(metadata, data);
  check(binary->binary && binary->bytes.substr(0, 4) == "RVPC", "binary magic");
  uint32_t length = 0;
  for (unsigned i = 0; i < 4; ++i) length |= uint32_t(uint8_t(binary->bytes[8 + i])) << (8 * i);
  const auto parsed = parse(binary->bytes.substr(12, length));
  check(parsed["msg"]["fields"][0]["name"] == "intensity", "fields preserved");
  const auto offset = (12 + length + 3) & ~std::size_t(3);
  check(binary->bytes.substr(offset) == std::string(data.begin(), data.end()), "all bytes preserved and aligned");
  bool rejected = false;
  try { parse("{\"id\":1,\"id\":2}"); } catch (...) { rejected = true; }
  check(rejected, "duplicate JSON keys rejected");
  Outbox box;
  auto active = std::make_shared<std::atomic_bool>(true);
  auto first = text_frame(Json::Value("first"));
  auto latest = text_frame(Json::Value("latest"));
  auto ack = text_frame(Json::Value("ack"));
  box.data("/a", first, active); box.data("/a", latest, active); box.control(ack);
  check(box.pop() == ack && box.pop() == latest && !box.pop(), "control priority and latest data");
  check(box.dropped() == 1, "replacement counted");
  for (int i = 0; i < 20; ++i) box.data("/topic" + std::to_string(i), first, active);
  unsigned count = 0; while (box.pop()) ++count;
  check(count == 8, "data queue bounded");
  active->store(false);
  check(!box.data("/old", first, active) && !box.pop(), "cancelled subscription cannot enqueue");
  for (unsigned i = 0; i < 32; ++i) check(box.control(ack), "control capacity");
  check(!box.control(ack), "control overflow signalled, never silently dropped");
  box.clear(); active->store(true); box.data("/removed", first, active); box.erase("/removed");
  check(!box.pop(), "unsubscribe discards pending data");
  std::cout << "RVPC fidelity, control priority, queue bounds and cancellation passed\n";
}
