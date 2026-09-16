#!/usr/bin/env python3
"""Read-only check of the public page, management API and native ROS API."""
import argparse
import json
from urllib.request import ProxyHandler, build_opener

def check(base, middleware=None):
    opener = build_opener(ProxyHandler({}))
    def get(path):
        with opener.open(base.rstrip("/") + path, timeout=5) as response:
            return response.headers.get("Content-Type", ""), response.read()
    content_type, body = get("/")
    if "text/html" not in content_type or b'<div id="app">' not in body:
        raise RuntimeError("Public URL does not serve the RVizWeb page")
    _, body = get("/health")
    management = json.loads(body)
    if management.get("ros_backend") != "v2" or management.get("status") != "healthy":
        raise RuntimeError(f"Management service is not healthy v2: {management}")
    _, body = get("/api/v2/ros/health")
    native = json.loads(body)
    if native.get("ready") is not True:
        raise RuntimeError(f"Native ROS service is not ready: {native}")
    _, body = get("/api/v2/ros/capabilities")
    capabilities = json.loads(body)
    if capabilities.get("protocol_version") != 2 or capabilities.get("stage", 0) < 3:
        raise RuntimeError("Native capabilities are incompatible")
    if middleware and capabilities.get("middleware") != middleware:
        raise RuntimeError(f"Expected {middleware}, got {capabilities.get('middleware')}")
    return {"url": base, "management": management, "native": native,
            "backend_version": capabilities["backend_version"],
            "middleware": capabilities["middleware"]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--middleware", choices=("ros1", "ros2"))
    args = parser.parse_args()
    print(json.dumps(check(args.url, args.middleware), ensure_ascii=False, indent=2))
