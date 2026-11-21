"""Shared pins, digests and build-identity checks for the Phase 0 host."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / '.tools/build'
STAMP = BUILD / 'build.json'
CHECKER = ROOT / 'host/checker-native/out/compat_checker'
SOURCES = ('fe.toml', 'src/lib.fe', 'src/observation.fe', 'src/conformance.fe', 'src/abi.fe', 'src/normalize.fe',
           'src/phase1_tests.fe', 'contracts/solidity/Codec.sol', 'contracts/fe/codec/fe.toml',
           'contracts/fe/codec/src/lib.fe',
           'host/checker-native/fe.toml', 'host/checker-native/src/lib.fe',
           'contracts/solidity/Meter.sol', 'contracts/fe/meter/fe.toml', 'contracts/fe/meter/src/lib.fe', 'contracts/fe/meter/src/tests.fe', 'src/tests.fe',
           'scripts/build.py', 'host/common.py')
# Phase 0 seeded fault: the Fe port reports limit 101 in TooLarge, one byte off.
MUTATION = ('revert_error(TooLarge { quantity, limit: LIMIT })',
            'revert_error(TooLarge { quantity, limit: LIMIT + 1 })  // INTENTIONAL PHASE 0 FAULT')


class InfrastructureError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hex_sha(path):
    return hashlib.sha256(bytes.fromhex(Path(path).read_text().strip().removeprefix('0x'))).hexdigest()


def pins():
    return json.loads((ROOT / 'toolchain.json').read_text())


def tool(name, env, default):
    return Path(os.environ.get(env, ROOT / '.tools/bin' / default)).resolve()


def fe_compiler():
    fe = tool('fe', 'FE_BIN', 'fe')
    system = {'Darwin': 'mac', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64'}.get(platform.machine())
    asset = pins()['fe']['assets'].get(f'fe_{system}_{arch}')
    if not fe.exists() or not asset or 'sha256:' + sha(fe) != asset['digest']:
        raise InfrastructureError('Fe compiler missing or not the pinned digest; run scripts/bootstrap-fe.py')
    version = subprocess.check_output([str(fe), '--version'], text=True, timeout=10).strip()
    if version != 'fe 26.5.0 (3dab95f)':
        raise InfrastructureError(f'Unexpected Fe version {version}')
    return fe, {'version': version, 'sha256': sha(fe)}


def solc_compiler():
    solc = tool('solc', 'SOLC_BIN', 'solc')
    pinned = pins()['solidity']
    if not solc.exists() or sha(solc) not in {a['sha256'] for a in pinned['assets'].values()}:
        raise InfrastructureError('solc missing or not the pinned digest; run scripts/bootstrap-solc.py')
    version = subprocess.check_output([str(solc), '--version'], text=True, timeout=10).strip().splitlines()[-1]
    if pinned['version'] not in version:
        raise InfrastructureError(f'Unexpected solc version {version}')
    return solc, {'version': version, 'sha256': sha(solc)}


def source_manifest():
    return {p: sha(ROOT / p) for p in SOURCES}


def load_stamp():
    """Refuse missing, stale or modified builds."""
    try:
        stamp = json.loads(STAMP.read_text())
    except (OSError, ValueError) as error:
        raise InfrastructureError('Missing build; run scripts/build.py') from error
    if stamp.get('sources') != source_manifest():
        raise InfrastructureError('Stale build (sources changed); run scripts/build.py')
    for path, digest in stamp['artifacts'].items():
        if not (ROOT / path).exists() or sha(ROOT / path) != digest:
            raise InfrastructureError(f'Modified or missing build artifact {path}; run scripts/build.py')
    return stamp
