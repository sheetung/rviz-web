#include "rvizweb/shared_adapter.hpp"
#include "rvizweb/conversion.hpp"
#include "rvizweb/pointcloud_processing.hpp"
#include <iostream>
#include <thread>
using namespace rvizweb;
void check(bool b, const char* why) { if (!b) throw std::runtime_error(why); }
struct Fake : RosAdapter {
  unsigned created = 0; std::vector<Sink> sinks; std::vector<std::weak_ptr<void>> handles;
  std::string middleware() const override { return "test"; }
  bool ready() const override { return true; }
  Json::Value topics() override { return {}; }
  bool supports(const std::string&) override { return true; }
  void stop() override {}
  std::shared_ptr<RosPublisher> advertise(const std::string&, const std::string&) override { return {}; }
  std::shared_ptr<void> subscribe(const std::string&, const std::string&, const std::string&, const std::string&, Sink sink) override {
    ++created; sinks.push_back(sink); auto handle = std::make_shared<int>(1); handles.push_back(handle); return handle;
  }
};
struct Field { std::string name; uint32_t offset; uint8_t datatype; uint32_t count; };
struct Cloud {
  struct { std::string frame_id = "map"; } header;
  uint32_t height = 2, width = 2, point_step = 16, row_step = 36;
  bool is_bigendian = false, is_dense = false;
  std::vector<Field> fields{{"x",0,7,1},{"y",4,7,1},{"z",8,7,1},{"intensity",12,7,1}};
  std::vector<uint8_t> data = std::vector<uint8_t>(72, 0xCD);
};
Cloud cloud(bool big) {
  Cloud c; c.is_bigendian = big;
  const float points[4][4] = {{.1f,.1f,.1f,42},{.2f,.2f,.2f,43},{2,2,2,44},{-1,-1,-1,45}};
  for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) {
    auto* dest = c.data.data() + (i/2)*36+(i%2)*16+j*4;
    std::memcpy(dest, &points[i][j], 4); if (big) std::reverse(dest, dest+4);
  }
  return c;
}
int main() {
  auto raw = std::make_shared<Fake>(); SharedAdapter adapter(raw);
  FramePtr a, b; unsigned calls = 0;
  auto one = adapter.subscribe("/points","pc","auto","auto",[&](FramePtr f){ a=f; });
  auto f = converted("/points", [] { return text_frame(Json::Value(Json::objectValue)); });
  raw->sinks[0](f);
  auto two = adapter.subscribe("/points","pc","auto","auto",[&](FramePtr f){ b=f; ++calls; });
  check(raw->created == 1 && a == b && b == f, "one upstream, shared bytes, immediate replay");
  auto other = adapter.subscribe("/points","pc","reliable","auto",[](FramePtr){});
  check(raw->created == 2, "different QoS isolated");
  one.reset(); raw->sinks[0](f); check(calls==2, "remaining client survives unsubscribe");
  auto stats=adapter.metrics(); check(stats["shared_streams"].asUInt64()==2, "stream metrics");
  auto error=converted("/points", []()->FramePtr { throw std::length_error("oversize"); });
  raw->sinks[0](error); raw->sinks[0](error);
  check(b->conversion_error && calls==3, "error delivered once per second");
  raw->sinks[0](f); check(b==f, "valid sample recovers after error");
  two.reset(); other.reset();
  check(raw->handles[0].expired() && raw->handles[1].expired(), "upstream released after final client");
  check(adapter.metrics()["shared_streams"].asUInt64()==0 && adapter.metrics()["snapshot_bytes"].asUInt64()==0, "metrics and cache release");
  // Concurrent callback/attach/detach, matching real ROS/network threads.
  auto keep=adapter.subscribe("/race","pc","auto","auto",[](FramePtr){});
  auto emit=raw->sinks.back();
  std::thread writer([&]{ for(int i=0;i<10000;++i) emit(f); });
  for(int i=0;i<1000;++i) { auto h=adapter.subscribe("/race","pc","auto","auto",[](FramePtr){}); adapter.metrics(); }
  writer.join(); keep.reset();
  for(bool big : {false,true}) {
    auto c=cloud(big); PointEncoder untouched(PointOptions{});
    check(untouched.encode(c,"/pc",stamp(1,2))->bytes==pointcloud(c,"/pc",stamp(1,2))->bytes, "default wire exact including padding");
    PointOptions options; options.voxel=1; options.crop=true; options.bounds={0,0,0,3,3,3};
    auto reduced=filter_points(c,options);
    check(reduced.height==1 && reduced.width==2 && reduced.row_step==32, "voxel and crop dimensions");
    check(std::equal(reduced.data.begin(),reduced.data.begin()+16,c.data.begin()), "first record incl intensity retained");
    check(std::equal(reduced.data.begin()+16,reduced.data.end(),c.data.begin()+36), "row padding excluded");
    check(reduced.is_bigendian==big && reduced.fields.size()==4, "endianness and fields retained");
    PointOptions rate; rate.rate=1; PointEncoder limited(rate);
    check(!limited.encode(c,"/pc",stamp(0,0))->throttled && limited.encode(c,"/pc",stamp(0,0))->throttled, "rate limit before encoding");
    options.bounds={10,10,10,20,20,20}; check(filter_points(c,options).width==0, "empty crop valid");
    c.fields[0].datatype=6;
    auto failed=converted("/pc", [&]{ return pointcloud(filter_points(c,options),"/pc",stamp(0,0)); });
    check(failed->conversion_error, "unsupported XYZ types produce error");
  }
  // Cache memory is globally bounded and reclaimed with stream ownership.
  std::vector<std::shared_ptr<void>> leases;
  for (int i=0;i<6;++i) {
    leases.push_back(adapter.subscribe("/large"+std::to_string(i),"pc","auto","auto",[](FramePtr){}));
    auto large=std::make_shared<Frame>(); large->bytes.resize(16*1024*1024);
    raw->sinks.back()(large);
  }
  check(adapter.metrics()["snapshot_bytes"].asUInt64()<=64*1024*1024, "global snapshot byte bound");
  leases.clear(); check(adapter.metrics()["snapshot_bytes"].asUInt64()==0, "large cache reclaimed");
  PointOptions excluded; excluded.topics="/other"; excluded.voxel=1;
  PointEncoder selection(excluded); auto original=cloud(false);
  check(selection.encode(original,"/pc",stamp(0,0))->bytes==pointcloud(original,"/pc",stamp(0,0))->bytes, "unselected topics untouched");
  setenv("RVIZWEB_POINTCLOUD_MAX_HZ","nan",1);
  bool invalid=false; try { PointOptions::environment(); } catch(const std::invalid_argument&) { invalid=true; }
  unsetenv("RVIZWEB_POINTCLOUD_MAX_HZ"); check(invalid,"invalid process settings rejected");
  Outbox box; auto active=std::make_shared<std::atomic_bool>(true);
  box.data("/a",f,active); box.data("/a",f,active);
  check(box.stats()["replaced_frames"].asUInt64()==1 && box.stats()["data_topics"].asUInt64()==1, "queue diagnostics");
  std::cout << "Sharing, replay, QoS isolation, cleanup, races, errors, endian filtering, fidelity and rate limits passed\n";
}
