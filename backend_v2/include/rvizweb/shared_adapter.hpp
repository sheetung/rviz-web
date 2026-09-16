#pragma once
#include "rvizweb/adapter.hpp"
#include <algorithm>
#include <chrono>
#include <tuple>

namespace rvizweb {
// Share only identical requested topic/type/QoS. auto and explicit QoS stay
// separate, since auto is resolved by the ROS adapter at creation time.
class SharedAdapter final : public RosAdapter {
  using Clock = std::chrono::steady_clock;
  using Key = std::tuple<std::string, std::string, std::string, std::string>;
  struct Entry {
    std::mutex mutex;
    std::shared_ptr<void> upstream;
    std::map<uint64_t, Sink> sinks;
    FramePtr latest;
    std::shared_ptr<std::atomic_size_t> cache_bytes;
    uint64_t next = 0, received = 0, encoded = 0, errors = 0, throttled = 0, bytes = 0;
    double conversion_ms = 0, max_conversion_ms = 0;
    Clock::time_point started = Clock::now(), last{}, last_error{};
    std::string error;
    explicit Entry(std::shared_ptr<std::atomic_size_t> budget) : cache_bytes(std::move(budget)) {}
    ~Entry() { if (latest) cache_bytes->fetch_sub(latest->bytes.size()); }
    void publish(FramePtr frame) {
      std::lock_guard<std::mutex> lock(mutex);
      ++received; last = Clock::now();
      if (frame->throttled) { ++throttled; return; }
      conversion_ms += frame->conversion_ms;
      max_conversion_ms = std::max(max_conversion_ms, frame->conversion_ms);
      if (frame->conversion_error) {
        ++errors; error = frame->bytes;
        if (last_error != Clock::time_point{} && last - last_error < std::chrono::seconds(1)) return;
        last_error = last;
      } else {
        ++encoded; bytes += frame->bytes.size();
        if (latest) { cache_bytes->fetch_sub(latest->bytes.size()); latest.reset(); }
        const auto size = frame->bytes.size();
        const auto previous = cache_bytes->fetch_add(size);
        if (previous + size <= 64 * 1024 * 1024) latest = frame;
        else cache_bytes->fetch_sub(size);
      }
      for (const auto& item : sinks) item.second(frame);
    }
  };
  struct Lease {
    std::shared_ptr<Entry> entry;
    uint64_t id;
    Lease(std::shared_ptr<Entry> e, uint64_t i) : entry(std::move(e)), id(i) {}
    ~Lease() { std::lock_guard<std::mutex> lock(entry->mutex); entry->sinks.erase(id); }
  };
 public:
  explicit SharedAdapter(std::shared_ptr<RosAdapter> adapter) : adapter_(std::move(adapter)) {}
  std::string middleware() const override { return adapter_->middleware(); }
  bool ready() const override { return adapter_->ready(); }
  Json::Value topics() override { return adapter_->topics(); }
  bool supports(const std::string& type) override { return adapter_->supports(type); }
  std::shared_ptr<RosPublisher> advertise(const std::string& topic, const std::string& type) override {
    return adapter_->advertise(topic, type);
  }
  void stop() override { adapter_->stop(); }
  std::shared_ptr<void> subscribe(const std::string& topic, const std::string& type,
      const std::string& reliability, const std::string& durability, Sink sink) override {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = entries_.begin(); it != entries_.end();) {
      if (it->second.expired()) it = entries_.erase(it); else ++it;
    }
    const Key key{topic, type, reliability, durability};
    auto found = entries_.find(key);
    auto entry = found == entries_.end() ? nullptr : found->second.lock();
    if (!entry) {
      if (entries_.size() >= 64) throw std::length_error("Shared stream limit reached (64)");
      entry = std::make_shared<Entry>(cache_bytes_);
      entry->upstream = adapter_->subscribe(topic, type, reliability, durability,
        [weak = std::weak_ptr<Entry>(entry)](FramePtr frame) { if (auto e = weak.lock()) e->publish(std::move(frame)); });
      entries_[key] = entry;
    }
    std::lock_guard<std::mutex> stream_lock(entry->mutex);
    const auto id = ++entry->next;
    entry->sinks.emplace(id, std::move(sink));
    auto lease = std::make_shared<Lease>(entry, id);
    // Preserve latched data and display snapshots for a client joining an
    // existing subscription. Deliver before newer callbacks, under stream lock.
    if (entry->latest) entry->sinks.at(id)(entry->latest);
    return lease;
  }
  Json::Value metrics() override {
    std::lock_guard<std::mutex> lock(mutex_);
    Json::Value result, streams(Json::arrayValue);
    const auto now = Clock::now();
    for (const auto& item : entries_) if (auto entry = item.second.lock()) {
      std::lock_guard<std::mutex> stream_lock(entry->mutex);
      Json::Value j;
      j["topic"] = std::get<0>(item.first); j["type"] = std::get<1>(item.first);
      j["reliability"] = std::get<2>(item.first); j["durability"] = std::get<3>(item.first);
      j["clients"] = Json::UInt64(entry->sinks.size());
      j["received"] = Json::UInt64(entry->received); j["encoded"] = Json::UInt64(entry->encoded);
      j["conversion_errors"] = Json::UInt64(entry->errors); j["throttled"] = Json::UInt64(entry->throttled);
      j["encoded_bytes"] = Json::UInt64(entry->bytes);
      const auto elapsed = std::chrono::duration<double>(now - entry->started).count();
      j["received_hz_average"] = entry->received / std::max(elapsed, .001);
      j["encoded_bytes_per_second_average"] = entry->bytes / std::max(elapsed, .001);
      j["conversion_ms_average"] = entry->conversion_ms / std::max(uint64_t(1), entry->received - entry->throttled);
      j["conversion_ms_max"] = entry->max_conversion_ms;
      j["last_received_age_ms"] = entry->received ? Json::Value(std::chrono::duration<double, std::milli>(now - entry->last).count()) : Json::Value();
      j["last_error"] = entry->error.empty() ? Json::Value() : parse(entry->error)["error"];
      j["snapshot_cached"] = bool(entry->latest);
      streams.append(j);
    }
    result["streams"] = streams; result["shared_streams"] = streams.size();
    result["snapshot_bytes"] = Json::UInt64(cache_bytes_->load());
    result["max_shared_streams"] = 64; result["max_snapshot_bytes"] = 64 * 1024 * 1024;
    return result;
  }
 private:
  std::shared_ptr<RosAdapter> adapter_;
  std::mutex mutex_;
  std::map<Key, std::weak_ptr<Entry>> entries_;
  std::shared_ptr<std::atomic_size_t> cache_bytes_ = std::make_shared<std::atomic_size_t>(0);
};
} // namespace rvizweb
