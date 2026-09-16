#include "rvizweb/server.hpp"
#include "rvizweb/pointcloud_processing.hpp"
#include "rvizweb/control.hpp"
#include <regex>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <map>
#include <cstdlib>
#include <fnmatch.h>
#include <sstream>

namespace rvizweb {
namespace net = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
namespace ws = beast::websocket;
using tcp = net::ip::tcp;
using Clock = std::chrono::steady_clock;
struct Subscription {
  std::shared_ptr<std::atomic_bool> active;
  std::shared_ptr<void> handle;
  std::string type;
  std::string reliability;
  std::string durability;
};

bool topic_allowed(const std::string& topic, bool publishing = false) {
  const char* setting = std::getenv(publishing ? "ROS_PUBLISH_TOPIC_ALLOWLIST" : "ROS_SUBSCRIBE_TOPIC_ALLOWLIST");
  std::istringstream patterns(setting ? setting : publishing ? "/goal_pose,/initialpose,/cmd_vel" : "*");
  std::string pattern;
  while (std::getline(patterns, pattern, ',')) {
    const auto first = pattern.find_first_not_of(" \t");
    if (first == std::string::npos) continue;
    pattern = pattern.substr(first, pattern.find_last_not_of(" \t") - first + 1);
    if (fnmatch(pattern.c_str(), topic.c_str(), 0) == 0) return true;
  }
  return false;
}

class Session : public std::enable_shared_from_this<Session> {
 public:
  Session(tcp::socket socket, std::shared_ptr<RosAdapter> adapter,
          std::vector<std::string> origins, std::shared_ptr<std::atomic_uint> clients)
    : socket_(std::move(socket)), adapter_(std::move(adapter)), origins_(std::move(origins)),
      clients_(std::move(clients)), write_timer_(socket_.get_executor()) { ++*clients_; }
  ~Session() {
    for (auto& [topic, sub] : subscriptions_) sub.active->store(false);
    --*clients_;
  }
  void start() {
    parser_.body_limit(1024);
    parser_.header_limit(8192);
    beast::get_lowest_layer(socket_).expires_after(std::chrono::seconds(10));
    http::async_read(socket_.next_layer(), input_, parser_,
      [self = shared_from_this()](beast::error_code error, std::size_t) {
        if (error) return self->stop();
        self->route();
      });
  }
 private:
  void stop() {
    if (closed_) return;
    closed_ = true;
    for (auto& [topic, sub] : subscriptions_) sub.active->store(false);
    subscriptions_.clear();
    for (auto& entry : publications_) entry.second->timer.cancel();
    publications_.clear();
    publishers_.clear();
    outbox_.clear();
    write_timer_.cancel();
    beast::error_code ignored;
    beast::get_lowest_layer(socket_).socket().cancel(ignored);
    beast::get_lowest_layer(socket_).socket().shutdown(tcp::socket::shutdown_both, ignored);
    beast::get_lowest_layer(socket_).socket().close(ignored);
  }
  bool allowed_origin(const http::request<http::string_body>& request) {
    const auto origin = request[http::field::origin].to_string();
    const auto host = request[http::field::host].to_string();
    return origin.empty() || origin == "http://" + host || origin == "https://" + host ||
      std::find(origins_.begin(), origins_.end(), origin) != origins_.end();
  }
  void respond(http::status status, const Json::Value& body) {
    auto response = std::make_shared<http::response<http::string_body>>(status, 11);
    response->set(http::field::content_type, "application/json");
    response->set(http::field::cache_control, "no-store");
    response->set("X-Content-Type-Options", "nosniff");
    response->keep_alive(false);
    response->body() = json(body);
    response->prepare_payload();
    http::async_write(socket_.next_layer(), *response,
      [self = shared_from_this(), response](beast::error_code, std::size_t) { self->stop(); });
  }
  void route() {
    const auto& request = parser_.get();
    if (!allowed_origin(request)) {
      Json::Value error; error["error"] = "origin_not_allowed";
      return respond(http::status::forbidden, error);
    }
    if (request.method() != http::verb::get) {
      Json::Value error; error["error"] = "method_not_allowed";
      return respond(http::status::method_not_allowed, error);
    }
    if (request.target() == "/ws/v2/ros" && ws::is_upgrade(request)) {
      beast::get_lowest_layer(socket_).expires_never();
      auto timeout = ws::stream_base::timeout::suggested(beast::role_type::server);
      timeout.handshake_timeout = std::chrono::seconds(10);
      timeout.idle_timeout = std::chrono::seconds(15);
      timeout.keep_alive_pings = true;
      socket_.set_option(timeout);
      socket_.read_message_max(max_request_bytes);
      socket_.async_accept(request, [self = shared_from_this()](beast::error_code error) {
        if (error) return self->stop();
        Json::Value hello;
        hello["version"] = 2; hello["event"] = "hello";
        hello["capabilities"] = capabilities(self->adapter_->middleware());
        self->control(hello);
        self->read();
      });
      return;
    }
    try {
      Json::Value body;
      if (request.target() == "/api/v2/ros/health") {
        body = capabilities(adapter_->middleware());
        body["ready"] = adapter_->ready();
        return respond(adapter_->ready() ? http::status::ok : http::status::service_unavailable, body);
      }
      if (request.target() == "/api/v2/ros/capabilities") return respond(http::status::ok, capabilities(adapter_->middleware()));
      if (request.target() == "/api/v2/ros/metrics") {
        body = adapter_->metrics(); body["pointcloud_processing"] = point_options().json_value();
        return respond(http::status::ok, body);
      }
      if (request.target() == "/api/v2/ros/topics") {
        body["topics"] = adapter_->topics();
        return respond(http::status::ok, body);
      }
      body["error"] = "not_found";
      respond(http::status::not_found, body);
    } catch (const std::exception& error) {
      Json::Value body; body["error"] = "ros_unavailable"; body["message"] = error.what();
      respond(http::status::service_unavailable, body);
    }
  }
  void control(const Json::Value& message) {
    if (closed_) return;
    if (!outbox_.control(text_frame(message))) return stop();
    write();
  }
  void read() {
    if (closed_) return;
    socket_.async_read(input_, [self = shared_from_this()](beast::error_code error, std::size_t) {
      if (error) return self->stop();
      const auto now = Clock::now();
      if (now - self->rate_start_ >= std::chrono::seconds(1)) {
        self->rate_start_ = now; self->requests_ = 0;
      }
      if (++self->requests_ > 60 || !self->socket_.got_text()) return self->stop();
      const auto text = beast::buffers_to_string(self->input_.data());
      self->input_.consume(self->input_.size());
      self->request(text);
      self->read();
    });
  }
  void request(const std::string& text) {
    Json::Value response; response["version"] = 2; response["ok"] = false;
    try {
      const auto request = parse(text);
      if (!request["id"].isString() || request["id"].asString().empty() || request["id"].asString().size() > 128)
        throw std::invalid_argument("id must be a nonempty string up to 128 bytes");
      response["id"] = request["id"];
      if (!request["version"].isInt() || request["version"].asInt() != 2) {
        response["error"]["code"] = "protocol_mismatch";
        response["error"]["message"] = "Expected protocol version 2";
        return control(response);
      }
      if (!request["method"].isString() || (!request["params"].isNull() && !request["params"].isObject()))
        throw std::invalid_argument("Expected method string and params object");
      const auto method = request["method"].asString();
      const auto& params = request["params"];
      auto& result = response["result"];
      result = Json::Value(Json::objectValue);
      if (method == "ping") result["pong"] = true;
      else if (method == "capabilities") result = capabilities(adapter_->middleware());
      else if (method == "topics.list") result["topics"] = adapter_->topics();
      else if (method == "topics.advertise" || method == "topics.unadvertise" || method == "topics.publish") {
        return control_request(request, response);
      }
      else if (method == "streams.stats") {
        result = adapter_->metrics(); result["pointcloud_processing"] = point_options().json_value();
      }
      else if (method == "session.stats") {
        result["queue"] = outbox_.stats();
        result["sent"] = sent_;
        result["dropped_frames"] = Json::UInt64(outbox_.dropped());
        result["subscriptions"] = Json::UInt64(subscriptions_.size());
        result["publishers"] = Json::UInt64(publishers_.size());
        result["pending_publications"] = Json::UInt64(publications_.size());
        result["connections"] = clients_->load();
      }
      else if (method == "topics.subscribe" || method == "topics.unsubscribe") {
        if (!params["topic"].isString()) throw std::invalid_argument("topic must be a string");
        const auto topic = params["topic"].asString();
        if (topic.empty() || topic.front() != '/' || topic.size() > 256 ||
            topic.find_first_not_of("/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_") != std::string::npos)
          throw std::invalid_argument("topic must be an absolute ROS topic name");
        if (method == "topics.unsubscribe") {
          auto found = subscriptions_.find(topic);
          if (found != subscriptions_.end()) {
            found->second.active->store(false);
            subscriptions_.erase(found);
            outbox_.erase(topic);
            sent_.removeMember(topic);
          }
        } else {
          if (!params["type"].isString()) throw std::invalid_argument("type must be a canonical message type");
          const auto type = params["type"].asString();
          if (!topic_allowed(topic)) {
            response.removeMember("result");
            response["error"]["code"] = "topic_not_allowed";
            response["error"]["message"] = "Topic is outside ROS_SUBSCRIBE_TOPIC_ALLOWLIST";
            return control(response);
          }
          if (!adapter_->supports(type)) {
            response["error"]["code"] = "unsupported_type";
            response["error"]["message"] = "Message type support is not available in this ROS environment";
            response.removeMember("result");
            return control(response);
          }
          const auto durability = params.get("durability", "auto").asString();
          if (durability != "auto" && durability != "volatile" && durability != "transient_local")
            throw std::invalid_argument("Unsupported durability");
          const auto reliability = params.get("reliability", "auto").asString();
          auto found = subscriptions_.find(topic);
          if (found != subscriptions_.end()) {
            if (found->second.type != type || found->second.reliability != reliability || found->second.durability != durability)
              throw std::invalid_argument("Unsubscribe before changing type or QoS");
          } else {
            if (subscriptions_.size() >= 32) throw std::invalid_argument("Subscription limit reached");
            auto active = std::make_shared<std::atomic_bool>(true);
            const std::weak_ptr<Session> weak = shared_from_this();
            auto handle = adapter_->subscribe(topic, type, reliability, durability, [weak, active, topic](FramePtr frame) {
              auto self = weak.lock();
              if (!self || !self->outbox_.data(topic, std::move(frame), active)) return;
              // Only one notification may wait in Asio; payloads stay in the bounded outbox.
              if (self->wake_pending_.exchange(true)) return;
              net::post(self->socket_.get_executor(), [self] {
                self->wake_pending_.store(false);
                self->write();
              });
            });
            subscriptions_.emplace(topic, Subscription{active, std::move(handle), type, reliability, durability});
          }
        }
        result["topic"] = topic;
      } else {
        response.removeMember("result");
        response["error"]["code"] = "unsupported_method";
        response["error"]["message"] = "Method not supported by this service";
        return control(response);
      }
      response["ok"] = true;
    } catch (const std::invalid_argument& e) {
      response.removeMember("result");
      response["error"]["code"] = "invalid_request"; response["error"]["message"] = e.what();
    } catch (const std::exception& e) {
      response.removeMember("result");
      response["error"]["code"] = "ros_error"; response["error"]["message"] = e.what();
    }
    control(response);
  }
  struct PublisherEntry {
    std::string type;
    std::shared_ptr<RosPublisher> handle;
  };
  struct Publication {
    explicit Publication(net::steady_timer::executor_type executor) : timer(executor) {}
    net::steady_timer timer;
    std::string topic;
    Json::Value message, response;
    std::shared_ptr<RosPublisher> publisher;
    Clock::time_point deadline = Clock::now() + std::chrono::milliseconds(1500);
  };
  struct Receipt { std::string fingerprint; Json::Value response; };
  void reject(Json::Value response, const std::string& code, const std::string& message) {
    response["ok"] = false; response.removeMember("result");
    response["error"]["code"] = code; response["error"]["message"] = message;
    control(response);
  }
  void finish_publication(const std::string& id, const std::shared_ptr<Publication>& pending,
                          const std::string& code = {}, const std::string& message = {}) {
    if (closed_ || !publications_.count(id)) return;
    auto response = pending->response;
    pending->timer.cancel();
    publications_.erase(id);
    if (code.empty()) {
      response["ok"] = true;
      response["result"]["topic"] = pending->topic;
      response["result"]["status"] = "submitted";
      response["result"]["execution"] = "unknown";
    } else {
      response["ok"] = false; response.removeMember("result");
      response["error"]["code"] = code; response["error"]["message"] = message;
    }
    receipts_.at(id).response = response;
    control(response);
  }
  void dispatch_publication(const std::string& id, const std::shared_ptr<Publication>& pending) {
    if (closed_ || !publications_.count(id)) return;
    try {
      if (!adapter_->ready()) return finish_publication(id, pending, "ros_unavailable", "ROS is not ready; command not submitted");
      if (pending->publisher->subscribers() > 0) {
        // Exactly one local submission; no retransmission on timeout or reconnect.
        pending->publisher->publish(pending->message);
        return finish_publication(id, pending);
      }
      if (Clock::now() >= pending->deadline)
        return finish_publication(id, pending, "no_subscribers", "No matching ROS subscriber; command not submitted");
    } catch (const std::exception& e) { return finish_publication(id, pending, "submission_unknown", e.what()); }
    pending->timer.expires_after(std::chrono::milliseconds(50));
    pending->timer.async_wait([weak = weak_from_this(), id, pending](beast::error_code error) {
      if (!error) if (auto self = weak.lock()) self->dispatch_publication(id, pending);
    });
  }
  void control_request(const Json::Value& request, Json::Value response) {
    const auto method = request["method"].asString();
    const auto& params = request["params"];
    const auto id = request["id"].asString();
    const bool publishing = method == "topics.publish";
    if (publishing) {
      auto found = receipts_.find(id);
      if (found != receipts_.end()) {
        if (found->second.fingerprint != json(request)) return reject(response, "request_id_conflict", "Request id was already used for another command");
        if (!found->second.response.isNull()) control(found->second.response);
        return;
      }
    }
    if (!params["topic"].isString()) throw std::invalid_argument("topic must be a string");
    const auto topic = params["topic"].asString();
    static const std::regex topic_name("(/[A-Za-z_][A-Za-z0-9_]*)+");
    if (topic.size() > 256 || !std::regex_match(topic, topic_name)) throw std::invalid_argument("Invalid absolute ROS topic name");
    if (!topic_allowed(topic, true)) return reject(response, "topic_not_allowed", "Topic is outside ROS_PUBLISH_TOPIC_ALLOWLIST");
    if (method == "topics.unadvertise") {
      std::vector<std::string> cancelled;
      for (const auto& [key, pending] : publications_) if (pending->topic == topic) cancelled.push_back(key);
      for (const auto& key : cancelled) {
        auto pending = publications_.at(key);
        finish_publication(key, pending, "cancelled", "Publisher removed before submission");
      }
      publishers_.erase(topic);
      response["ok"] = true; response["result"]["topic"] = topic; return control(response);
    }
    if (!params["type"].isString() || !publish_type(params["type"].asString()))
      return reject(response, "unsupported_type", "Publish supports PoseStamped, PoseWithCovarianceStamped and Twist");
    const auto type = params["type"].asString();
    if (publishing) {
      validate_control(type, params["msg"]);
      if (publications_.size() >= 8) return reject(response, "publish_busy", "Pending command limit reached");
      for (const auto& entry : publications_) if (entry.second->topic == topic)
        return reject(response, "publish_busy", "A command for this topic is still pending");
    }
    auto publisher = publishers_.find(topic);
    if (publisher != publishers_.end() && publisher->second.type != type)
      throw std::invalid_argument("Unadvertise before changing publisher type");
    if (publisher == publishers_.end()) {
      if (publishers_.size() >= 16) return reject(response, "publisher_limit", "Publisher limit reached");
      publisher = publishers_.emplace(topic, PublisherEntry{type, adapter_->advertise(topic, type)}).first;
    }
    if (!publishing) {
      response["ok"] = true; response["result"]["topic"] = topic;
      response["result"]["status"] = "advertised"; return control(response);
    }
    // Keep the most recent 256 receipts in this session, never evict pending commands.
    while (receipts_.size() >= 256) {
      auto oldest = receipt_order_.front(); receipt_order_.pop_front();
      if (publications_.count(oldest)) receipt_order_.push_back(oldest); else receipts_.erase(oldest);
    }
    receipts_[id] = Receipt{json(request), Json::Value()}; receipt_order_.push_back(id);
    auto pending = std::make_shared<Publication>(socket_.get_executor());
    pending->topic = topic; pending->message = params["msg"]; pending->response = std::move(response);
    pending->publisher = publisher->second.handle;
    // Velocity samples should never wait and become stale during discovery.
    if (type == "geometry_msgs/msg/Twist") pending->deadline = Clock::now();
    publications_[id] = pending;
    dispatch_publication(id, pending);
  }
  void write() {
    if (closed_ || writing_) return;
    writing_ = outbox_.pop();
    if (!writing_) return;
    socket_.binary(writing_->binary);
    write_timer_.expires_after(std::chrono::seconds(2));
    write_timer_.async_wait([weak = weak_from_this()](beast::error_code error) {
      if (!error) if (auto self = weak.lock()) self->stop();
    });
    socket_.async_write(net::buffer(writing_->bytes),
      [self = shared_from_this()](beast::error_code error, std::size_t) {
        self->write_timer_.cancel();
        if (!error && self->subscriptions_.count(self->writing_->topic)) {
          auto& stats = self->sent_[self->writing_->topic];
          stats["frames"] = stats.get("frames", Json::UInt64(0)).asUInt64() + Json::UInt64(1);
          stats["bytes"] = stats.get("bytes", Json::UInt64(0)).asUInt64() + Json::UInt64(self->writing_->bytes.size());
        }
        self->writing_.reset();
        if (error) return self->stop();
        self->write();
      });
  }
  ws::stream<beast::tcp_stream> socket_;
  std::shared_ptr<RosAdapter> adapter_;
  std::vector<std::string> origins_;
  std::shared_ptr<std::atomic_uint> clients_;
  net::steady_timer write_timer_;
  http::request_parser<http::string_body> parser_;
  beast::flat_buffer input_;
  Outbox outbox_;
  Json::Value sent_{Json::objectValue};
  FramePtr writing_;
  std::map<std::string, Subscription> subscriptions_;
  std::map<std::string, PublisherEntry> publishers_;
  std::map<std::string, std::shared_ptr<Publication>> publications_;
  std::map<std::string, Receipt> receipts_;
  std::deque<std::string> receipt_order_;
  std::atomic_bool wake_pending_{false};
  bool closed_ = false;
  Clock::time_point rate_start_ = Clock::now();
  unsigned requests_ = 0;
};

class Listener : public std::enable_shared_from_this<Listener> {
 public:
  Listener(net::io_context& io, std::shared_ptr<RosAdapter> adapter, const tcp::endpoint& endpoint,
           std::vector<std::string> origins)
    : acceptor_(io), adapter_(std::move(adapter)), origins_(std::move(origins)), clients_(std::make_shared<std::atomic_uint>(0)) {
    acceptor_.open(endpoint.protocol());
    acceptor_.set_option(net::socket_base::reuse_address(true));
    acceptor_.bind(endpoint);
    acceptor_.listen(16);
  }
  void accept() {
    acceptor_.async_accept([self = shared_from_this()](beast::error_code error, tcp::socket socket) {
      if (!error && self->clients_->load() < 16)
        std::make_shared<Session>(std::move(socket), self->adapter_, self->origins_, self->clients_)->start();
      if (self->acceptor_.is_open()) self->accept();
    });
  }
 private:
  tcp::acceptor acceptor_;
  std::shared_ptr<RosAdapter> adapter_;
  std::vector<std::string> origins_;
  std::shared_ptr<std::atomic_uint> clients_;
};
void listen(net::io_context& io, std::shared_ptr<RosAdapter> adapter,
            const std::string& address, uint16_t port, const std::vector<std::string>& origins) {
  std::make_shared<Listener>(io, std::move(adapter), tcp::endpoint(net::ip::make_address(address), port), origins)->accept();
}
}  // namespace rvizweb
