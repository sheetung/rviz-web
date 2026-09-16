"""Exercise startup caching without needing either ROS installation."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_startup_build_reuses_cache_and_reconfigures_for_ros_environment(tmp_path):
    scripts = tmp_path / "backend_v2/scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "backend_v2/scripts/build.sh", scripts / "build.sh")
    command = [
        "bash", "-eu", "-c",
        'cmake() { '
        'printf "cmake:%s\\n" "$*"; '
        'if [[ "$1" == -S ]]; then mkdir -p "$4"; touch "$4/CMakeCache.txt"; fi; '
        'if [[ "$1" == --build ]]; then return "${BUILD_RESULT:-0}"; fi; }; '
        'ctest() { echo ctest-called; }; export -f cmake ctest; '
        'bash "$1" --startup',
        "bash", str(scripts / "build.sh"),
    ]
    for version in ("1", "2"):
        env = {**os.environ, "ROS_VERSION": version, "CMAKE_PREFIX_PATH": "/ros/first"}
        def run(**updates):
            return subprocess.run(command, env={**env, **updates}, text=True, capture_output=True)
        first = run()
        assert first.returncode == 0, first.stderr
        assert f"-DROS_VERSION={version}" in first.stdout
        second = run()
        assert second.returncode == 0, second.stderr
        assert "cmake:-S" not in second.stdout
        assert "--target rvizweb_native" in second.stdout
        assert "ctest-called" not in second.stdout
        changed = run(CMAKE_PREFIX_PATH="/ros/second")
        assert changed.returncode == 0, changed.stderr
        assert "cmake:-S" in changed.stdout
        failed = run(CMAKE_PREFIX_PATH="/ros/second", BUILD_RESULT="7")
        assert failed.returncode == 7
