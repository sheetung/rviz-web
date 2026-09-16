import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_FILE = BACKEND_ROOT / "pyproject.toml"
VERSION_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_backend_version() -> str:
    try:
        content = PYPROJECT_FILE.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0+unknown"
    match = VERSION_PATTERN.search(content)
    return match.group(1) if match else "0.0.0+unknown"


BACKEND_VERSION = read_backend_version()
