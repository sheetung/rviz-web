import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = PROJECT_ROOT / "release.sh"


def test_release_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(RELEASE_SCRIPT)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_release_help_lists_independent_components():
    result = subprocess.run(
        ["bash", str(RELEASE_SCRIPT), "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "frontend" in result.stdout
    assert "backend" in result.stdout
    assert "--push" in result.stdout


def test_component_versions_are_synchronized_with_their_locks():
    for component in ("frontend", "backend"):
        result = subprocess.run(
            [
                "node",
                "scripts/sync-version.mjs",
                component,
                "--check",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_components_can_be_versioned_independently(tmp_path):
    temporary_root = tmp_path / "repo"
    (temporary_root / "scripts").mkdir(parents=True)
    (temporary_root / "frontend").mkdir()
    (temporary_root / "backend").mkdir()
    shutil.copy2(
        PROJECT_ROOT / "scripts/sync-version.mjs",
        temporary_root / "scripts/sync-version.mjs",
    )
    for relative_path in (
        "frontend/package.json",
        "frontend/package-lock.json",
        "backend/pyproject.toml",
        "backend/uv.lock",
    ):
        shutil.copy2(PROJECT_ROOT / relative_path, temporary_root / relative_path)

    original_backend = (temporary_root / "backend/pyproject.toml").read_text(
        encoding="utf-8"
    )
    frontend_result = subprocess.run(
        [
            "node",
            "scripts/sync-version.mjs",
            "frontend",
            "2.0.0",
        ],
        cwd=temporary_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert frontend_result.returncode == 0, frontend_result.stderr
    frontend_package = json.loads(
        (temporary_root / "frontend/package.json").read_text(encoding="utf-8")
    )
    assert frontend_package["version"] == "2.0.0"
    assert (temporary_root / "backend/pyproject.toml").read_text(
        encoding="utf-8"
    ) == original_backend

    original_frontend = (temporary_root / "frontend/package.json").read_text(
        encoding="utf-8"
    )
    backend_result = subprocess.run(
        [
            "node",
            "scripts/sync-version.mjs",
            "backend",
            "1.3.1",
        ],
        cwd=temporary_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert backend_result.returncode == 0, backend_result.stderr
    assert 'version = "1.3.1"' in (temporary_root / "backend/pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert (temporary_root / "frontend/package.json").read_text(
        encoding="utf-8"
    ) == original_frontend
