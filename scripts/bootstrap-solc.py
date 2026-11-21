#!/usr/bin/env python3
"""Install the pinned comparison compiler locally after checksum validation."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

root = Path(__file__).resolve().parent.parent
pins = json.loads((root / 'toolchain.json').read_text())['solidity']
system = platform.system()
machine = platform.machine()
key = 'macos' if system == 'Darwin' else ('linux-arm64' if machine in ('arm64', 'aarch64') else 'linux-amd64') if system == 'Linux' else None
if key is None or machine not in ('arm64', 'aarch64', 'x86_64', 'AMD64'):
    raise SystemExit('Unsupported host; inspect toolchain.json')
asset = pins['assets'][key]
destination = root / '.tools/bin/solc'
destination.parent.mkdir(parents=True, exist_ok=True)
temporary = destination.with_suffix('.download')
subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20', '--max-time', '600',
                asset['url'], '-o', str(temporary)], check=True)
if hashlib.sha256(temporary.read_bytes()).hexdigest() != asset['sha256']:
    temporary.unlink()
    raise SystemExit('Solc checksum mismatch')
temporary.chmod(0o755)
os.replace(temporary, destination)
subprocess.run([str(destination), '--version'], check=True)
