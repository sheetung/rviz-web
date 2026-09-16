import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("package_source", ROOT / "scripts/package-source.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bundle_excludes_runtime_secrets_and_records_exact_sources(tmp_path):
    source = tmp_path / "source"
    for name, data in {
        "README.md": "test", ".env": "SECRET=private",
        ".env.example": "ROS_WS_URL=/ws/ros2",
        "rvizweb_configs/default.rvizweb": "{}",
        "rvizweb_configs/private.rvizweb": "credentials",
        "frontend/src/App.vue": "<template/>",
        "frontend/src/.env": "secret",
        "backend/.venv/token": "secret",
        "backend_v2/build/key.cpp": "secret",
        "Dockerfile": "obsolete",
        "scripts/run.sh": "#!/bin/bash\ntrue\n",
    }.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    (source / "scripts/run.sh").chmod(0o755)
    archive = module.package(source, tmp_path / "out", "2.0.0-dev.4")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        prefix = "rvizweb-2.0.0-dev.4-source/"
        assert prefix + "frontend/src/App.vue" in names
        for suffix in (".env", "rvizweb_configs/private.rvizweb", "Dockerfile", "backend/.venv/token"):
            assert prefix + suffix not in names
        manifest = json.load(tar.extractfile(prefix + "MANIFEST.json"))
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(tar.extractfile(prefix + name).read()).hexdigest() == digest
        assert tar.getmember(prefix + "scripts/run.sh").mode == 0o755
    assert archive.with_suffix(".gz.sha256").read_text().split()[0] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        module.package(source, tmp_path / "out", "2.0.0-dev.4")


def test_bundle_rejects_symlink_sources(tmp_path):
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    secret = tmp_path / "private"
    secret.write_text("secret")
    (source / "scripts/unsafe.py").symlink_to(secret)
    with pytest.raises(ValueError, match="symlink"):
        module.package(source, tmp_path / "out", "2.0.0-dev.4")
    assert not list((tmp_path / "out").glob("*.tar.gz"))
