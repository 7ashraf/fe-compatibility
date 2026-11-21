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
           'contracts/solidity/Treasury.sol', 'contracts/solidity/Harness.sol', 'contracts/fe/treasury/provenance.json',
           'contracts/fe/treasury/policy/fe.toml', 'contracts/fe/treasury/policy/src/lib.fe',
           'contracts/fe/treasury/policy/src/policy.fe', 'contracts/fe/treasury/policy/src/types.fe',
           'contracts/fe/treasury/treasury/fe.toml', 'contracts/fe/treasury/treasury/src/lib.fe',
           'contracts/solidity/PackedLayout.sol', 'contracts/fe/layout/fe.toml', 'contracts/fe/layout/src/lib.fe',
           'src/layout.fe', 'src/phase2_tests.fe', 'src/phase4_tests.fe',
           'scripts/build.py', 'host/common.py')
EMIT = '            log.emit(Added { caller: ctx.caller(), quantity, total })\n'
# Seeded faults in copies of contracts/fe/meter, applied at build time. Each one
# is a single, documented porting mistake. `fe-faulty` is the Phase 0 one-byte fault.
VARIANTS = {
    'fe-faulty': [('revert_error(TooLarge { quantity, limit: LIMIT })',
                   'revert_error(TooLarge { quantity, limit: LIMIT + 1 })  // INTENTIONAL PHASE 0 FAULT: TooLarge reports limit 101')],
    'fe-state': [('            total += quantity\n' + EMIT + '            total\n',
                  '            let next = total + quantity\n'
                  '            // INTENTIONAL PHASE 2 FAULT: stores one extra unit at the limit; return and event stay correct.\n'
                  '            total = if quantity == LIMIT { next + 1 } else { next }\n'
                  '            log.emit(Added { caller: ctx.caller(), quantity, total: next })\n'
                  '            next\n')],
    'fe-unindexed': [('    #[indexed]\n    pub caller: Address,',
                      '    pub caller: Address,  // INTENTIONAL PHASE 2 FAULT: caller is not indexed')],
    'fe-extra-log': [(EMIT, EMIT + '            log.emit(Added { caller: ctx.caller(), quantity, total })'
                      '  // INTENTIONAL PHASE 2 FAULT: event emitted twice\n')],
    'fe-wrong-error': [('revert_error(EmptyQuantity {})',
                        'revert_error(TooLarge { quantity, limit: LIMIT })  // INTENTIONAL PHASE 2 FAULT: wrong error')],
    'fe-no-empty-check': [('            if quantity == 0 {\n                revert_error(EmptyQuantity {})\n            }\n',
                           '            // INTENTIONAL PHASE 2 FAULT: zero quantity is not rejected\n')],
}
MUTATION = VARIANTS['fe-faulty'][0]

# Phase 3 seeded faults in copies of the vendored Fe treasury: (file, old, new), each applied exactly once.
TREASURY_VARIANTS = {
    'fe-inclusive-expiry': [('policy/src/policy.fe', '    if context.now >= grant.expires_at {',
                             '    if context.now > grant.expires_at {  // INTENTIONAL PHASE 3 FAULT: inclusive expiry')],
    'fe-cap-off-by-one': [('policy/src/policy.fe', '    if amount > remaining {',
                           '    if amount >= remaining {  // INTENTIONAL PHASE 3 FAULT: exact remaining rejected')],
    'fe-unindexed-delegate': [('treasury/src/lib.fe',
                               'pub struct Spent {\n    #[indexed]\n    pub grantId: u256,\n    #[indexed]\n'
                               '    pub delegate: Address,',
                               'pub struct Spent {\n    #[indexed]\n    pub grantId: u256,\n'
                               '    pub delegate: Address,  // INTENTIONAL PHASE 3 FAULT: Spent.delegate not indexed')],
    'fe-auth-after-active': [('policy/src/policy.fe',
                              '    if context.caller != grant.delegate {\n        return Err(PolicyError::Unauthorized)\n'
                              '    }\n    if !grant.active {\n        return Err(PolicyError::InactiveGrant)\n    }\n',
                              '    // INTENTIONAL PHASE 3 FAULT: active checked before authority\n'
                              '    if !grant.active {\n        return Err(PolicyError::InactiveGrant)\n    }\n'
                              '    if context.caller != grant.delegate {\n        return Err(PolicyError::Unauthorized)\n'
                              '    }\n')],
    'fe-revoke-event-twice': [('policy/src/policy.fe', '    Ok(grant.active)\n}',
                               '    Ok(true)  // INTENTIONAL PHASE 3 FAULT: repeated revocation emits again\n}')],
    'fe-no-reserve': [('treasury/src/lib.fe',
                       '                    grant.spent = decision.new_spent\n'
                       '                    state.value().grants.set(key: grantId, value: grant)\n',
                       '                    // INTENTIONAL PHASE 3 FAULT: spent is not persisted\n')],
}


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

# Phase 4 seeded faults in copies of contracts/fe/layout (file, old, new). The first two
# keep the contract's own getters consistent, so only the raw layout reveals them.
LAYOUT_VARIANTS = {
    'fe-layout-shifted': [('src/lib.fe', 'pub const PAUSED_OFFSET: u256 = 20',
                           'pub const PAUSED_OFFSET: u256 = 21  // INTENTIONAL PHASE 4 FAULT: paused one byte too high')],
    'fe-layout-wrong-root': [('src/lib.fe', 'pub const BALANCES_ROOT: u256 = 1',
                              'pub const BALANCES_ROOT: u256 = 2  // INTENTIONAL PHASE 4 FAULT: wrong mapping root')],
    'fe-layout-clobber': [('src/lib.fe', '            slot.write(offset: OWNER_OFFSET, value)\n',
                           '            slot.store(std::evm::SolWord { word: 0 })'
                           '  // INTENTIONAL PHASE 4 FAULT: setOwner clears the slot first\n'
                           '            slot.write(offset: OWNER_OFFSET, value)\n')],
}
