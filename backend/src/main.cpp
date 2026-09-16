#include "rvizweb/version.hpp"
#include "rvizweb/server.hpp"
#include "rvizweb/shared_adapter.hpp"
#include "rvizweb/pointcloud_processing.hpp"
#include <boost/asio/signal_set.hpp>
#include <iostream>
#include <stdexcept>

int main(int argc, char** argv) {
  try {
    std::string host = "127.0.0.1";
    unsigned port = 8082;
    std::vector<std::string> origins;
    for (int i = 1; i < argc; ++i) {
      const std::string arg = argv[i];
      if (arg == "--help") {
        std::cout << "rvizweb_native [--host 127.0.0.1] [--port 8082] [--allow-origin http://host:port]\n";
        return 0;
      }
      if (++i >= argc) throw std::invalid_argument("Missing option value");
      if (arg == "--host") host = argv[i];
      else if (arg == "--port") {
        const std::string value = argv[i];
        if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
          throw std::invalid_argument("Port must be an integer");
        port = std::stoul(value);
        if (port == 0 || port > 65535) throw std::invalid_argument("Port must be 1..65535");
      }
      else if (arg == "--allow-origin") origins.emplace_back(argv[i]);
      else throw std::invalid_argument("Unknown option: " + arg);
    }
    rvizweb::point_options(); // Fail early on invalid process-wide processing options.
    auto adapter = std::make_shared<rvizweb::SharedAdapter>(rvizweb::make_adapter());
    boost::asio::io_context io(1);
    boost::asio::signal_set signals(io, SIGINT, SIGTERM);
    signals.async_wait([&](auto, auto) { io.stop(); });
    rvizweb::listen(io, adapter, host, static_cast<uint16_t>(port), origins);
    std::cout << "RVizWeb native " << rvizweb::backend_version << " " << adapter->middleware() << " listening on " << host << ':' << port << std::endl;
    io.run();
    adapter->stop();
  } catch (const std::exception& e) {
    std::cerr << "Startup failed: " << e.what() << '\n';
    return 1;
  }
}
