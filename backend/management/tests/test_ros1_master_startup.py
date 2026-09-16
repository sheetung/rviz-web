"""Checks for the opt-in local ROS1 Master launcher; no ROS install needed."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('ros1_master', ROOT / 'scripts/ros1-master.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class MasterStartupTests(unittest.TestCase):
    def test_only_explicit_loopback_addresses_allow_autostart(self):
        for uri in ['http://127.0.0.1:11311', 'http://localhost:11311', 'http://[::1]:11311']:
            self.assertEqual(helper.local_port(uri), 11311)
        for uri in ['http://192.168.1.10:11311', 'http://robot:11311', 'https://localhost:11311']:
            with self.assertRaises(ValueError):
                helper.local_port(uri)

    def test_ros2_does_not_require_master(self):
        result = subprocess.run(
            ['bash', '-eu', '-c', 'source "$1"; ROS_VERSION=2; ROS1_AUTOSTART_MASTER=true; ensure_ros_master',
             'bash', str(ROOT / 'start.sh')], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_remote_master_cannot_be_started(self):
        result = subprocess.run(
            ['python3', str(ROOT / 'scripts/ros1-master.py'), 'validate-local'],
            env={**os.environ, 'ROS_MASTER_URI': 'http://192.0.2.1:11311'},
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('loopback', result.stdout)


if __name__ == '__main__':
    unittest.main()
