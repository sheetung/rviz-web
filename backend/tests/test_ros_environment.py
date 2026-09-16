"""Exercise the shell loader without requiring a ROS installation."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RosEnvironmentTests(unittest.TestCase):
    def test_management_install_is_independent_of_ros_python(self):
        for version in ("1", "2"):
            for imports_ok in (True, False):
                with self.subTest(version=version, imports_ok=imports_ok), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "backend").mkdir()
                    (root / "frontend").mkdir()
                    result = subprocess.run(
                        ["bash", "-eu", "-c",
                         'source "$1"; BACKEND_DIR="$2/backend"; FRONTEND_DIR="$2/frontend"; '
                         'uv() { printf "uv:%s\\n" "$*"; }; '
                         'npm() { echo npm-called; }; '
                         'check_ros_python() { echo unexpected-ros-import; return 1; }; '
                         'check_management_python() { return "$IMPORT_RESULT"; }; '
                         'install_dependencies', "bash", str(ROOT / "install.sh"), str(root)],
                        env={**os.environ, "ROS_VERSION": version, "ROS1_AUTOSTART_MASTER": "false",
                             "IMPORT_RESULT": "0" if imports_ok else "1"},
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, imports_ok, result.stderr)
                    self.assertIn("venv --python >=3.10,<3.13 --system-site-packages .venv", result.stdout)
                    self.assertIn("--frozen --no-dev", result.stdout)
                    self.assertNotIn("--extra ros1", result.stdout)
                    self.assertNotIn("unexpected-ros-import", result.stdout)
                    self.assertEqual("npm-called" in result.stdout, imports_ok)

    def test_native_build_only_targets_selected_ros_version(self):
        for version in ("1", "2"):
            result = subprocess.run(
                ["bash", "-eu", "-c",
                 'cmake() { printf "%s\\n" "$*"; }; '
                 'ctest() { printf "%s\\n" "$*"; }; export -f cmake ctest; bash "$1"',
                 "bash", str(ROOT / "backend_v2/scripts/build.sh")],
                env={**os.environ, "ROS_VERSION": version},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"-DROS_VERSION={version}", result.stdout)
            self.assertIn(f"build/ros{version}", result.stdout)
            self.assertNotIn(f"build/ros{3 - int(version)}", result.stdout)

    def test_ros2_import_check_ignores_ros1_master_settings(self):
        result = subprocess.run(
            ['bash', '-eu', '-c', 'source "$1"; '
             'fake_python() { printf "%s" "$*"; }; check_ros_python fake_python',
             'bash', str(ROOT / 'scripts/ros-environment.sh')],
            env={**os.environ, 'ROS_VERSION': '2', 'ROS1_AUTOSTART_MASTER': 'true'},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '-c import rclpy')

    def test_version_selection_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            one = Path(directory) / "ros1.bash"
            two = Path(directory) / "ros2.bash"
            overlay = Path(directory) / "overlay.bash"
            one.write_text("export ROS_VERSION=1 ROS_DISTRO=noetic\n")
            two.write_text("export ROS_VERSION=2 ROS_DISTRO=humble\n")
            overlay.write_text('export OVERLAY_LOADED="$ROS_VERSION"\n')
            env = {k: v for k, v in os.environ.items() if not k.startswith("ROS")}
            env.update(ROS1_SETUP_PATHS=str(one), ROS2_SETUP_PATHS=str(two))
            cases = [
                ({}, "2", None),
                ({"ROS_WS_URL": ""}, "2", None),
                ({"ROS_WS_URL": "/ws"}, "2", None),
                ({"ROS_WS_URL": "/ws/ros2"}, "2", None),
                ({"ROS_WS_URL": "/ws/ros2", "ROS1_AUTOSTART_MASTER": "true",
                  "ROS_IP": "unused", "ROS_HOSTNAME": "unused",
                  "ROS_MASTER_URI": "invalid"}, "2", None),
                ({"ROS_WS_URL": "/ws/ros1"}, "1", None),
                ({"ROS_WS_URL": "wss://example.test/prefix/ws/ros1?x=1#f"}, "1", None),
                ({"ROS_WS_URL": "/ws/ros1", "ROS2_SETUP_PATHS": "/missing"}, "1", None),
                ({"ROS1_SETUP_PATHS": "/missing"}, "2", None),
                ({"ROS2_SETUP_PATHS": ""}, None, "Set ROS2_SETUP_PATHS"),
                ({"ROS2_SETUP_PATHS": "/missing"}, None, "ROS setup file missing"),
                ({"ROS2_SETUP_PATHS": str(one)}, None, "must provide ROS_VERSION=2"),
                ({"ROS2_SETUP_PATHS": f"{two} {one}"}, None, "Mixed ROS environments"),
                ({"ROS_VERSION": "1", "ROS_DISTRO": "noetic"}, None, "Mixed ROS environments"),
                ({"ROS2_SETUP_PATHS": f"{two} {overlay}"}, "2:2", None),
                ({"ROS_WS_URL": "/ws/ros1", "ROS1_SETUP_PATHS": f"{one} {overlay}"}, "1:1", None),
            ]
            for overrides, expected, error in cases:
                with self.subTest(overrides=overrides):
                    result = subprocess.run(
                        ["bash", "-eu", "-c",
                         'source "$1"; load_ros_environment; '
                         'printf "%s" "$ROS_VERSION${OVERLAY_LOADED:+:$OVERLAY_LOADED}"',
                         "bash", str(ROOT / "scripts/ros-environment.sh")],
                        env={**env, **overrides}, capture_output=True, text=True,
                    )
                    if error:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(error, result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
