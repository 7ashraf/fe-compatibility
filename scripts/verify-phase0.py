#!/usr/bin/env python3
"""Phase 0 gate: the full raw observation path, decided by a Fe checker.

1. Pinned tools: Fe 26.5.0 digest, solc 0.8.31 digest, Anvil/Cast 1.5.1 commit.
2. Fe unit tests for the checker on the EVM and native backends; the Fe
   `try_call` exact-bytes test on the correct port, and that test failing on the
   seeded variant.
3. Build, then run the Meter v0 sequence in isolated Osaka worlds:
   Solidity vs Fe (match, both orders), Solidity vs seeded Fe (one-byte
   mismatch located at step 2, returndata byte 67, 0x64 vs 0x65).
4. Targeted perturbations of the recorded raw observations, each passed
   through the native Fe checker, must be classified as intended. Malformed
   transport and stale builds must be infrastructure errors, never verdicts.

--record writes docs/evidence/phase0/ (the raw execution records and gate.json).
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402
import observe  # noqa: E402
from evm_chain import LocalChain  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase0'
TOOLS = {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    fe, fe_info = common.fe_compiler()
    _, solc_info = common.solc_compiler()
    with LocalChain(ROOT) as chain:
        TOOLS.update(chain.versions)
    print(f'PASS pinned tools: {fe_info["version"]}, {solc_info["version"]}, anvil/cast 1.5.1 b0a9dd9c', flush=True)
    commands = []

    def checked(command, expect=0, show=None):
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True, timeout=600)
        display = show or [Path(str(command[0])).name if i == 0 else str(c).replace(str(ROOT) + '/', '')
                           for i, c in enumerate(command)]
        commands.append({'command': display, 'exit': result.returncode,
                         'stdout': result.stdout[-12000:].replace(str(ROOT), '<root>'),
                         'stderr': result.stderr[-4000:].replace(str(ROOT), '<root>')})
        if result.returncode != expect:
            raise RuntimeError(f'{display}: exit {result.returncode}, expected {expect}\n{result.stdout}\n{result.stderr}')
        print(f'PASS {" ".join(display)}' + (f'  (expected exit {expect})' if expect else ''), flush=True)
        return result

    py = sys.executable
    checked([fe, 'check', '.'])
    checked([fe, 'test', '.'])
    checked([fe, 'test', '.', '--backend', 'native'])
    checked([fe, 'test', 'contracts/fe/meter'])
    checked([py, 'scripts/build.py'], show=['python3', 'scripts/build.py'])
    # Negative control: the exact-bytes Fe test must fail on the seeded port.
    negative = checked([fe, 'test', '.tools/build/sources/meter-faulty'], expect=1)
    if 'Test reverted: 0x4e487b71' + '0' * 63 + '1' not in negative.stdout + negative.stderr:
        raise RuntimeError('Seeded-port Fe test failed for a reason other than its exact-bytes assertion')

    records, reports = {}, {}
    with tempfile.TemporaryDirectory(prefix='fe-compat-phase0-') as directory:
        for left, right, expect in (('solidity', 'fe', 0), ('fe', 'solidity', 0), ('solidity', 'fe-faulty', 1)):
            out = Path(directory) / f'{left}-{right}'
            result = checked([py, 'host/observe.py', '--left', left, '--right', right, '--record-dir', out],
                             expect=expect, show=['python3', 'host/observe.py', '--left', left, '--right', right])
            reports[f'{left}-vs-{right}'] = json.loads(result.stdout)
            for f in out.glob('raw-*.json'):
                records[f.stem.removeprefix('raw-')] = json.loads(f.read_text())
    divergence = reports['solidity-vs-fe-faulty']['first_divergence']
    expected = {'step': 2, 'category': 'returndata-byte', 'index': 67, 'left': '100', 'right': '101'}
    if {k: divergence[k] for k in expected} != expected:
        raise RuntimeError(f'Seeded fault located incorrectly: {divergence}')
    if reports['solidity-vs-fe']['verdict'] != 'match' or reports['fe-vs-solidity']['verdict'] != 'match':
        raise RuntimeError('Correct pair did not match')
    print('PASS seeded one-byte fault located by Fe: step 2 add(200), returndata byte 67, 0x64 vs 0x65', flush=True)

    # Targeted perturbations of the real Solidity record, one at a time.
    base = records['solidity']

    def flip(hex_text, offset):
        raw = bytearray.fromhex(hex_text[2:])
        raw[offset] ^= 1
        return '0x' + raw.hex()

    def drop_leading(hex_text):
        return '0x' + hex_text[4:]

    cases = []

    def case(name, mutate, step, category, index=0):
        mutated = copy.deepcopy(base)
        mutate(mutated['steps'])
        decision, _ = observe.check(base, mutated)
        got = decision.get('first_divergence', {})
        ok = (decision['verdict'] == 'mismatch' and got.get('step') == step and got.get('category') == category
              and got.get('index') == index)
        cases.append({'name': name, 'expected': {'step': step, 'category': category, 'index': index},
                      'fe_decision': got or decision['verdict'], 'passed': ok})
        if not ok:
            raise RuntimeError(f'{name}: Fe classified {decision}')

    case('last returndata byte', lambda s: s[0].update(returndata=flip(s[0]['returndata'], 31)), 0, 'returndata-byte', 31)
    case('lost leading zero byte', lambda s: s[0].update(returndata=drop_leading(s[0]['returndata'])), 0,
         'returndata-length')
    case('empty returndata', lambda s: s[4].update(returndata='0x'), 4, 'returndata-length')
    case('extra trailing zero in revert data', lambda s: s[1].update(returndata=s[1]['returndata'] + '00'), 1,
         'returndata-length')
    case('error selector byte', lambda s: s[1].update(returndata=flip(s[1]['returndata'], 0)), 1, 'returndata-byte', 0)
    case('error argument byte', lambda s: s[2].update(returndata=flip(s[2]['returndata'], 35)), 2,
         'returndata-byte', 35)
    case('success instead of revert', lambda s: s[1].update(success=True), 1, 'status')
    case('missing event', lambda s: s[3].update(logs=[]), 3, 'log-count')
    case('extra event', lambda s: s[4].update(logs=copy.deepcopy(s[3]['logs'])), 4, 'log-count')
    case('different emitter', lambda s: s[0]['logs'][0].update(address='0x' + '11' * 20), 0, 'log-emitter')
    case('indexed caller moved to data', lambda s: s[0]['logs'][0].update(
        topics=s[0]['logs'][0]['topics'][:1], data='0x' + s[0]['logs'][0]['topics'][1][2:] + s[0]['logs'][0]['data'][2:]),
        0, 'topic-count')
    case('event signature topic byte', lambda s: s[0]['logs'][0]['topics'].__setitem__(
        0, flip(s[0]['logs'][0]['topics'][0], 31)), 0, 'topic', 0)
    case('indexed caller byte', lambda s: s[0]['logs'][0]['topics'].__setitem__(
        1, flip(s[0]['logs'][0]['topics'][1], 31)), 0, 'topic', 1)
    case('event data byte', lambda s: s[3]['logs'][0].update(data=flip(s[3]['logs'][0]['data'], 63)), 3,
         'log-data-byte', 63)
    case('state after matching return (total)', lambda s: s[4].update(returndata=flip(s[4]['returndata'], 31)), 4,
         'returndata-byte', 31)
    for name in ('solidity', 'fe', 'fe-faulty'):
        if observe.check(records[name], records[name])[0]['verdict'] != 'match':
            raise RuntimeError(f'{name} does not match itself')
    print(f'PASS {len(cases)} targeted perturbations classified by Fe; each record matches itself', flush=True)

    infrastructure = []

    def must_be_infrastructure(name, mutate):
        mutated = copy.deepcopy(base)
        mutate(mutated['steps'])
        try:
            observe.check(base, mutated)
        except common.InfrastructureError as error:
            infrastructure.append({'name': name, 'error': str(error)})
            return
        raise RuntimeError(f'{name}: accepted as a behavior verdict')

    must_be_infrastructure('oversized returndata (300 bytes)', lambda s: s[0].update(returndata='0x' + '00' * 300))
    must_be_infrastructure('log on a reverted call', lambda s: s[1].update(logs=copy.deepcopy(s[0]['logs'])))
    must_be_infrastructure('five logs', lambda s: s[0].update(logs=s[0]['logs'] * 5))
    must_be_infrastructure('step count differs', lambda s: s.pop())
    backup = Path(tempfile.mkdtemp(prefix='fe-compat-checker-')) / 'compat_checker'
    shutil.copy2(common.CHECKER, backup)
    try:
        with common.CHECKER.open('ab') as handle:
            handle.write(b'\0')
        stale = subprocess.run([py, 'host/observe.py'], capture_output=True, text=True, timeout=120)
        if stale.returncode != 3 or 'Modified or missing build artifact' not in stale.stdout:
            raise RuntimeError(f'Modified checker binary was not refused: {stale.stdout}')
        infrastructure.append({'name': 'modified checker binary', 'error': json.loads(stale.stdout)['error']})
    finally:
        shutil.copy2(backup, common.CHECKER)
        shutil.rmtree(backup.parent)
    common.load_stamp()
    print(f'PASS {len(infrastructure)} malformed/stale inputs are infrastructure errors, not verdicts', flush=True)

    if args.record:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for name, record in records.items():
            (EVIDENCE / f'raw-{name}.json').write_text(json.dumps(record, indent=2) + '\n')
        stamp = common.load_stamp()
        gate = {'format': 'fe-compatibility-phase0-gate-v1', 'result': 'Phase 0 exit gate passed',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': fe_info, 'solc': solc_info, 'foundry': TOOLS,
                'targets': stamp['targets'], 'reports': reports, 'perturbations': cases,
                'infrastructure_controls': infrastructure, 'commands': commands,
                'sources': stamp['sources']}
        (EVIDENCE / 'gate.json').write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}/', flush=True)
    print('PASS Phase 0 exit gate: comparison decided in Fe; a one-byte difference is detected', flush=True)


if __name__ == '__main__':
    main()
