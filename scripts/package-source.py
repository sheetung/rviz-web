#!/usr/bin/env python3
"""Create a checksummed local-deployment source bundle, never a live config export."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "README.md", "LICENSE", ".env.example", ".node-version", ".npm-version",
    "start.sh", "install.sh", "release.sh",
    "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
    "frontend/vite.config.js", "frontend/.eslintrc.cjs",
    "backend/management/pyproject.toml", "backend/management/uv.lock",
    "backend/CMakeLists.txt", "backend/README.md", "backend/VERSION",
    "backend/include/rvizweb/version.hpp.in",
    "rvizweb_configs/default.rvizweb",
)
TREES = (
    "frontend/src", "frontend/public", "frontend/tests", "backend/management/app", "backend/management/tests",
    "backend/src", "backend/include", "backend/scripts", "backend/tests",
    "scripts",
)
EXTENSIONS = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".vue", ".css",
              ".html", ".json", ".cpp", ".hpp", ".h", ".svg", ".png", ".jpg", ".ico", ".md"}
SKIP = {"__pycache__", ".pytest_cache", "node_modules", "build", ".venv"}

def source_files(root):
    paths = {Path(name) for name in FILES if (root / name).is_file()}
    for tree in TREES:
        for path in (root / tree).rglob("*"):
            relative = path.relative_to(root)
            if any(part in SKIP or part.startswith(".") for part in relative.parts):
                continue
            if path.is_file() and (path.suffix in EXTENSIONS or path.name in {"LICENSE", "NOTICE"}):
                paths.add(relative)
    # Text documentation only; omit large benchmark datasets and screenshots.
    paths.update(path.relative_to(root) for path in (root / "docs").rglob("*.md"))
    for relative in sorted(paths):
        path = root / relative
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            raise ValueError(f"Refusing source symlink: {relative}")
        yield relative

def git_value(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def package(root, output, version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Version must be semantic, e.g. 2.0.0-dev.4")
    output.mkdir(parents=True, exist_ok=True)
    name = f"rvizweb-{version}-source"
    archive = output / f"{name}.tar.gz"
    checksums = output / f"{name}.tar.gz.sha256"
    if archive.exists() or checksums.exists():
        raise FileExistsError("Release output already exists; choose a new output directory/version")
    manifest = {"bundle_version": version, "kind": "source", "backend": "v2",
                "git_commit": git_value(root, "rev-parse", "HEAD"),
                "working_tree_dirty": bool(git_value(root, "status", "--porcelain")),
                "files": {}}
    try:
        with archive.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w") as tar:
            def add(relative, data, mode=0o644):
                info = tarfile.TarInfo(f"{name}/{relative}")
                info.size, info.mode, info.mtime = len(data), mode, 0
                tar.addfile(info, io.BytesIO(data))
            for relative in source_files(root):
                path = root / relative
                data = path.read_bytes()
                manifest["files"][relative.as_posix()] = hashlib.sha256(data).hexdigest()
                add(relative.as_posix(), data, 0o755 if path.stat().st_mode & 0o111 else 0o644)
            add("MANIFEST.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
        checksums.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    return archive

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(package(ROOT, args.output, args.version))
