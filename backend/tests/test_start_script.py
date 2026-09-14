import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = PROJECT_ROOT / "start.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(START_SCRIPT), *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_start_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_help_lists_supported_commands_without_starting_services():
    result = _run("help")
    assert result.returncode == 0
    assert "sync" in result.stdout
    assert "local" in result.stdout
    assert "dev" in result.stdout
    assert "docker" not in result.stdout


def test_unknown_command_returns_usage_error():
    result = _run("unknown")
    assert result.returncode == 2
    assert "Usage:" in result.stdout


def test_script_can_be_sourced_without_running_main():
    result = subprocess.run(
        ["bash", "-c", f'source "{START_SCRIPT}"; declare -F start_local main'],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "start_local" in result.stdout
    assert "main" in result.stdout


def test_health_checks_bypass_shell_proxy_settings():
    script = START_SCRIPT.read_text(encoding="utf-8")
    assert "curl --noproxy '*' -fsS" in script


def test_logging_is_disabled_without_creating_log_directory(tmp_path):
    log_dir = tmp_path / "logs"
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source "{START_SCRIPT}"; '
                f'LOG_DIR="{log_dir}"; LOG_ENABLED=false; '
                'configure_logging; '
                '[[ -z "$LOG_RUN_DIR" && -z "$START_LOG_FILE" '
                '&& -z "$BACKEND_LOG_FILE" && -z "$FRONTEND_LOG_FILE" '
                '&& ! -e "$LOG_DIR" ]]'
            ),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_logging_creates_unique_timestamped_run_directories(tmp_path):
    log_dir = tmp_path / "logs"
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source "{START_SCRIPT}"; '
                f'LOG_DIR="{log_dir}"; LOG_ENABLED=true; '
                'configure_logging; first="$LOG_RUN_DIR"; '
                'configure_logging; '
                '[[ "$first" != "$LOG_RUN_DIR" ]]'
            ),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    run_dirs = sorted(log_dir.iterdir())
    assert len(run_dirs) == 2
    assert all(
        path.is_dir()
        and re.fullmatch(r"\d{8}-\d{6}(?:-\d+)?", path.name)
        and (path / "start.log").is_file()
        for path in run_dirs
    )


def test_logging_routes_each_process_to_its_own_file(tmp_path):
    log_dir = tmp_path / "logs"
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source "{START_SCRIPT}"; '
                f'LOG_DIR="{log_dir}"; LOG_ENABLED=true; '
                'configure_logging; '
                'run_with_optional_log "$BACKEND_LOG_FILE" printf "backend-output\\n"; '
                'run_with_optional_log "$FRONTEND_LOG_FILE" printf "frontend-output\\n"'
            ),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    run_dir = next(log_dir.iterdir())
    assert "Logging to" in (run_dir / "start.log").read_text(encoding="utf-8")
    assert (run_dir / "backend.log").read_text(encoding="utf-8") == "backend-output\n"
    assert (run_dir / "frontend.log").read_text(encoding="utf-8") == "frontend-output\n"
