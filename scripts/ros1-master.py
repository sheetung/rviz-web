#!/usr/bin/env python3
"""Check the configured ROS1 Master or run an explicitly enabled local Master."""
import argparse
import os
import signal
import threading
from urllib.parse import urlparse
from xmlrpc.client import ServerProxy, Transport


class TimeoutTransport(Transport):
    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = 2
        return connection


def local_port(uri):
    parsed = urlparse(uri)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Automatic Master startup requires a loopback ROS_MASTER_URI')
    return parsed.port or 11311


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'validate-local', 'run'))
    args = parser.parse_args()
    uri = os.environ.get('ROS_MASTER_URI', 'http://127.0.0.1:11311')
    try:
        if args.action == 'check':
            with ServerProxy(uri, transport=TimeoutTransport()) as master:
                code, reason, _ = master.getUri('/rvizweb_start')
                if code != 1:
                    raise RuntimeError(reason)
        else:
            port = local_port(uri)
            if args.action == 'validate-local':
                return 0
            from rosmaster.master import Master
            stopped = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stopped.set())
            master = Master(port)
            try:
                master.start()
                print(f'Local ROS1 Master ready: {uri}', flush=True)
                stopped.wait()
            finally:
                master.stop()
    except Exception as error:
        print(f'ROS1 Master {uri}: {error}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
