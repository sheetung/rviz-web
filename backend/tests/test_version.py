from app.core.version import BACKEND_VERSION, PYPROJECT_FILE, read_backend_version


def test_backend_version_comes_from_pyproject():
    pyproject = PYPROJECT_FILE.read_text(encoding="utf-8")
    assert f'version = "{BACKEND_VERSION}"' in pyproject
    assert read_backend_version() == BACKEND_VERSION
