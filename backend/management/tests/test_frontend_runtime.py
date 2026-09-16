"""Offline installer tests using a tiny fake Node distribution."""
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class FrontendRuntimeTests(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['.node-version', '.npm-version']:
                (root / name).write_text((ROOT / name).read_text())
            node = (root / '.node-version').read_text().strip()
            npm = (root / '.npm-version').read_text().strip()
            architecture = 'arm64' if os.uname().machine in ('aarch64', 'arm64') else 'x64'
            name = f'node-v{node}-linux-{architecture}'
            fixture = root / 'fixture'
            binaries = fixture / name / 'bin'
            binaries.mkdir(parents=True)
            for command, version in [('node', f'v{node}'), ('npm', npm)]:
                if mode == 'wrong-version' and command == 'npm':
                    version = '6.0.0'
                script = binaries / command
                script.write_text(f'#!/bin/sh\necho {version}\n')
                script.chmod(0o755)
            archive = fixture / f'{name}.tar.xz'
            with tarfile.open(archive, 'w:xz') as tar:
                tar.add(binaries.parent, arcname=name)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if mode == 'bad-checksum':
                digest = '0' * 64
            (fixture / 'SHASUMS256.txt').write_text(f'{digest}  {archive.name}\n')
            fakebin = root / 'fakebin'
            fakebin.mkdir()
            curl = fakebin / 'curl'
            curl.write_text('''#!/bin/bash

while [[ $# -gt 0 ]]; do
  case "$1" in
    https://*) url="$1"; shift ;;
    -o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s\n' "$url" >> "$PROJECT_ROOT/downloads"
[[ "$TEST_MODE" != download-failure ]] || exit 35
if [[ "$url" == https://unavailable.example/* ]]; then
  exit 35
fi
[[ "$url" == "https://mirror.example/node/v"* ]] || exit 99
cp "$PROJECT_ROOT/fixture/${url##*/}" "$output"
''')
            curl.chmod(0o755)
            # Force an incompatible pre-existing system runtime.
            for command in ['node', 'npm']:
                path = fakebin / command
                path.write_text('#!/bin/sh\necho 0.0.0\n')
                path.chmod(0o755)
            result = subprocess.run(
                ['bash', '-eu', '-c', 'source "$1"; ensure_frontend_runtime || exit 1; '
                 'ensure_frontend_runtime || exit 1; check_frontend_runtime',
                 'bash', str(ROOT / 'scripts/frontend-runtime.sh')],
                env={**os.environ, 'PROJECT_ROOT': str(root), 'TEST_MODE': mode,
                     'NODE_DOWNLOAD_URLS': ('https://unavailable.example/node ' if mode == 'fallback' else '') + 'https://mirror.example/node/',
                     'PATH': f'{fakebin}:{os.environ["PATH"]}'},
                capture_output=True, text=True,
            )
            if mode in ('success', 'fallback'):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len((root / 'downloads').read_text().splitlines()), 3 if mode == 'fallback' else 2)
                self.assertTrue((root / f'.cache/node-v{node}/bin/node').is_file())
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / f'.cache/node-v{node}').exists())
            self.assertEqual(list((root / '.cache').glob('node-install.*')), [])

    def test_installer(self):
        for mode in ['success', 'fallback', 'download-failure', 'bad-checksum', 'wrong-version']:
            with self.subTest(mode=mode):
                self.run_case(mode)


if __name__ == '__main__':
    unittest.main()
