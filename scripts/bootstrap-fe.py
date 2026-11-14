#!/usr/bin/env python3
"""Install the pinned release locally, verifying its recorded SHA-256."""
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent.parent
manifest = json.loads((root / 'toolchain.json').read_text())
system = {'Darwin': 'mac', 'Linux': 'linux'}.get(platform.system())
arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64', 'AMD64': 'amd64'}.get(platform.machine())
if not system or not arch:
    raise SystemExit('Unsupported platform; inspect the pinned release assets.')
asset = manifest['fe']['assets'][f'fe_{system}_{arch}']
destination = root / '.tools' / 'bin' / 'fe'
destination.parent.mkdir(parents=True, exist_ok=True)
temporary = destination.with_suffix('.download')
subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20',
                '--max-time', '600', asset['url'], '-o', str(temporary)], check=True)
digest = 'sha256:' + hashlib.sha256(temporary.read_bytes()).hexdigest()
if digest != asset['digest']:
    temporary.unlink()
    raise SystemExit('Compiler checksum mismatch; installation aborted.')
temporary.chmod(0o755)
os.replace(temporary, destination)
subprocess.run([str(destination), '--version'], check=True)
