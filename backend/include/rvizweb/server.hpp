#pragma once
#include "rvizweb/adapter.hpp"
#include <boost/asio/io_context.hpp>
#include <vector>
namespace rvizweb {
void listen(boost::asio::io_context& io, std::shared_ptr<RosAdapter> adapter,
            const std::string& address, uint16_t port, const std::vector<std::string>& origins);
}
