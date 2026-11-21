#!/usr/bin/env python3
"""Phase 1 gate: specification, schemas, and golden vectors.

Exit tests from the plan, each checked below:
  1. matching vectors pass: both implementations match every golden vector (Fe decides);
  2. wrong selector/type/length fails with a specific category (Fe ABI validator and comparator);
  3. address normalization changes only approved fields;
  4. a deployment error cannot look like an expected application revert;
  5. values above JavaScript's safe-integer range round-trip exactly.
Also: the Phase 0 gate (regression), Fe unit tests on both backends, golden vectors
reproduced from the independent encoder, and strict schema/limit/version rejection.

--record writes docs/evidence/phase1/.
"""
import argparse
import contextlib
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402
import fecheck  # noqa: E402
import vectors  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase1'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    fe, fe_info = common.fe_compiler()
    _, solc_info = common.solc_compiler()
    commands = []

    def checked(command, show, expect=0, timeout=900):
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True, timeout=timeout)
        commands.append({'command': show, 'exit': result.returncode,
                         'stdout': result.stdout[-8000:].replace(str(ROOT), '<root>'),
                         'stderr': result.stderr[-3000:].replace(str(ROOT), '<root>')})
        if result.returncode != expect:
            raise RuntimeError(f'{show}: exit {result.returncode}\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}')
        print('PASS ' + ' '.join(show), flush=True)
        return result

    py = sys.executable
    checked([py, 'scripts/verify-phase0.py'], ['python3', 'scripts/verify-phase0.py'])
    tests = checked([fe, 'test', '.'], ['fe', 'test', '.'])
    native = checked([fe, 'test', '.', '--backend', 'native'], ['fe', 'test', '.', '--backend', 'native'])
    for result in (tests, native):
        match = re.search(r'test result: ok\. ([0-9]+) passed; 0 failed', result.stdout)
        if not match or int(match.group(1)) < 14:
            raise RuntimeError('Expected at least the 14 Phase 0-1 Fe checker tests to pass, with none failing')
    checked([py, 'scripts/make-vectors.py', '--check'], ['python3', 'scripts/make-vectors.py', '--check'])

    with contextlib.redirect_stdout(io.StringIO()):
        code = run_vectors()
    report = vectors.main.report
    if code != 0:
        raise RuntimeError(f'host/vectors.py expectations failed: {report.get("expectations")}')
    expectations = report['expectations']
    print(f'PASS python3 host/vectors.py: {sum(expectations.values())}/{len(expectations)} expectations', flush=True)
    fixture = vectors.load(vectors.FIXTURE)
    records = report['records']
    valid = [v for v in fixture['vectors'] if v['kind'] == 'valid']
    print(f'PASS exit 1: {len(valid)} valid + 10 reject vectors match golden on Solidity and Fe; '
          'the two implementations match each other', flush=True)

    # Exit 2: specific categories for wrong selector, type and length.
    declared = {c['id']: c['calldata']['category'] for c in report['classification']}
    needed = {'m-unknown-selector': 'selector', 'm-uint8-dirty': 'type', 'm-int16-unextended': 'type',
              'm-address-dirty': 'type', 'm-bool-two': 'type', 'm-uint64-dirty': 'type',
              'm-truncated-word': 'truncated', 'm-truncated-byte': 'truncated', 'm-empty': 'truncated',
              'm-echo-length-overrun': 'length', 'm-statics-trailing': 'extra', 'm-echo-offset-noncanonical': 'offset',
              'm-echo-dirty-padding': 'padding'}
    if any(declared[k] != c for k, c in needed.items()):
        raise RuntimeError(f'ABI categories differ: {declared}')
    sol = {s['id']: s for s in records['solidity']['steps']}
    by_id = {v['id']: v for v in fixture['vectors']}
    perturbed = []

    def returndata_case(name, vector, hex_text, category, index=None):
        got = fecheck.validate_abi(hex_text, by_id[vector]['outputs'])
        if got['category'] != category or (index is not None and got['index'] != index):
            raise RuntimeError(f'{name}: Fe gave {got}')
        perturbed.append({'name': name, 'fe': got})

    rd = sol['statics-max']['returndata']
    returndata_case('returned uint8 with high bits', 'statics-max', rd[:2] + '1ff'.rjust(64, '0') + rd[66:], 'type', 0)
    returndata_case('returned address with a dirty byte', 'statics-max', rd[:130] + '01' + rd[132:], 'type', 2)
    returndata_case('returned bool 2', 'statics-max', rd[:-1] + '2', 'type', 3)
    returndata_case('returndata missing a word', 'statics-max', rd[:-64], 'truncated', 3)
    returndata_case('returndata with an extra word', 'statics-max', rd + '0' * 64, 'extra')
    echo = sol['echo-max']['returndata']
    returndata_case('bytes length larger than data', 'echo-max', echo[:66] + hex(200)[2:].rjust(64, '0') + echo[130:],
                    'length')
    returndata_case('bytes offset not canonical', 'echo-max', echo[:2] + hex(64)[2:].rjust(64, '0') + echo[66:], 'offset')
    golden_revert = by_id['echo-too-long']['expected']['returndata']
    for name, observed, category, index in (
            ('wrong error selector', '0xad8e4f3d' + golden_revert[10:], 'error-selector', 0),
            ('error payload missing a word', golden_revert[:-64], 'returndata-length', 0)):
        expected = {'success': False, 'returndata': golden_revert, 'logs': []}
        decision = fecheck.sequence(vectors.EXPECTED_DEPLOYMENT, records['solidity']['deployment'],
                                    [({}, True, expected, {**expected, 'returndata': observed})])
        got = decision.get('first_divergence', {})
        if got.get('category') != category or got.get('index') != index:
            raise RuntimeError(f'{name}: Fe gave {decision}')
        perturbed.append({'name': name, 'fe': got})
    print(f'PASS exit 2: 13 malformed calldata vectors and {len(perturbed)} returndata perturbations get '
          'specific Fe categories', flush=True)

    # Exit 3: normalization changes only approved fields.
    n = report['normalized']
    if not (n['with_allowlist']['verdict'] == 'match' and n['without_normalization']['verdict'] == 'mismatch'
            and n['control_bytes_not_rewritten']['first_divergence']['category'] == 'returndata-byte'):
        raise RuntimeError(f'Normalization expectations failed: {n}')
    # Extending the allowlist to a uint word must be rejected when the fixture is loaded.
    print('PASS exit 3: differently addressed worlds match only through the allowlist; the target address '
          'inside bytes stays raw and differs', flush=True)

    # Exit 4: deployment failure.
    d = report['deployment']
    if not (d['differential']['verdict'] == 'not-comparable'
            and d['as_expected_application_revert']['verdict'] == 'not-comparable'
            and all(d['revert_bytes_equal_expected'].values())):
        raise RuntimeError(f'Deployment expectations failed: {d}')
    print('PASS exit 4: constructor revert InvalidOwner() in both worlds is not-comparable, including against '
          'a step expecting the same bytes', flush=True)

    # Exit 5: values above 2^53 round-trip exactly (bytes compared by Fe; decimal re-read here).
    roundtrip = []
    for vid in ('wide-max', 'wide-min', 'wide-beyond-double', 'point-max', 'point-beyond-double'):
        v = by_id[vid]
        args_flat = v['args'][0] if vid.startswith('point') else v['args']
        for target in ('solidity', 'fe'):
            words = bytes.fromhex(records[target]['steps'][fixture['vectors'].index(v)]['returndata'][2:])
            values = [int.from_bytes(words[i:i + 32], 'big', signed=(t == 'int256'))
                      for i, t in zip(range(0, len(words), 32), v['outputs'])]
            numbers = [str(x) for x, t in zip(values, v['outputs']) if t != 'address']
            want = [a for a in args_flat if isinstance(a, str) and not a.startswith('0x')]
            if numbers != want:
                raise RuntimeError(f'{vid}/{target}: {numbers} != {want}')
            roundtrip.append({'vector': vid, 'implementation': target, 'decimal': numbers})
    print(f'PASS exit 5: {len(roundtrip)} decimal values up to 2^256-1 and down to -2^255 round-trip exactly',
          flush=True)

    # Strict loader: schema versions, unknown fields, JSON numbers, limits, tampered allowlists.
    rejections = []
    base = json.loads(vectors.FIXTURE.read_text())

    def reject(name, mutate, raw=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            if raw is None:
                data = copy.deepcopy(base)
                mutate(data)
                path.write_text(json.dumps(data))
            else:
                path.write_text(raw)
            try:
                vectors.load(path)
            except vectors.CaseError as error:
                rejections.append({'name': name, 'error': str(error)})
                return
        raise RuntimeError(f'Loader accepted: {name}')

    reject('schema_version 2', lambda d: d.update(schema_version=2))
    reject('schema_version true', lambda d: d.update(schema_version=True))
    reject('unknown top-level field', lambda d: d.update(extra=1))
    reject('missing field', lambda d: d.pop('provenance'))
    reject('JSON number argument above 2^53', lambda d: d['vectors'][6]['args'].__setitem__(0, 9007199254740993))
    reject('float argument', lambda d: d['vectors'][4]['args'].__setitem__(0, 1.5e77))
    reject('leading-zero decimal', lambda d: d['vectors'][4]['args'].__setitem__(0, '01'))
    reject('uppercase hex', lambda d: d['vectors'][0].update(calldata=d['vectors'][0]['calldata'].upper()))
    reject('calldata over 256 bytes', lambda d: d['vectors'][0].update(calldata='0x' + '00' * 257))
    reject('65 vectors', lambda d: d.update(vectors=d['vectors'] * 3))
    reject('duplicate vector id', lambda d: d['vectors'][1].update(id=d['vectors'][0]['id']))
    reject('five topics', lambda d: d['vectors'][9]['expected']['logs'][0]['topics'].extend(['0x' + '00' * 32] * 3))
    reject('allowlist extended to a uint word', lambda d: d['vectors'][4]['normalize']['return_words'].append(0))
    reject('signature not in the frozen ABI', lambda d: d['vectors'][0].update(signature='statics(uint8)'))
    reject('different interface hash', lambda d: d.update(interface_sha256='0' * 64))
    reject('duplicate JSON key', None, raw=vectors.FIXTURE.read_text().replace('"fixture": "codec-v1",',
                                                                              '"fixture": "codec-v1", "fixture": "x",', 1))
    reject('vectors not a list', lambda d: d.update(vectors={'a': 1}))
    reject('vector entry not an object', lambda d: d['vectors'].__setitem__(0, 'statics'))
    reject('NaN', None, raw=vectors.FIXTURE.read_text().replace('"schema_version": 1', '"schema_version": NaN', 1))
    invalid = subprocess.run([py, 'host/vectors.py', '--fixture', '/nonexistent.json'], capture_output=True, text=True)
    if invalid.returncode != 2:
        raise RuntimeError(f'Missing fixture must exit 2, got {invalid.returncode}')
    rejections.append({'name': 'missing fixture file (CLI)', 'error': json.loads(invalid.stdout)['error']})
    print(f'PASS strict loader rejects {len(rejections)} invalid fixtures (exit 2, never a verdict)', flush=True)

    if args.record:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for name, record in records.items():
            (EVIDENCE / f'raw-{name}.json').write_text(json.dumps(record, indent=2) + '\n')
        public = {k: v for k, v in report.items() if k != 'records'}
        (EVIDENCE / 'report.json').write_text(json.dumps(public, indent=2) + '\n')
        stamp = common.load_stamp()
        malformed = [{'id': v['id'], 'expected_outcome': v['expected_outcome'], 'category': v['calldata_category'],
                      **{t: {'success': records[t]['steps'][i]['success'],
                             'returndata': records[t]['steps'][i]['returndata']} for t in ('solidity', 'fe')}}
                     for i, v in enumerate(fixture['vectors']) if v['kind'] == 'malformed']
        gate = {'format': 'fe-compatibility-phase1-gate-v1', 'result': 'Phase 1 exit gate passed',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': fe_info, 'solc': solc_info,
                'foundry': records['solidity']['tools'],
                'targets': {k: stamp['targets'][k] for k in ('solidity-codec', 'fe-codec')},
                'fixture_sha256': report['fixture_sha256'], 'expectations': expectations,
                'malformed_behavior': malformed, 'returndata_perturbations': perturbed,
                'roundtrip': roundtrip, 'loader_rejections': rejections, 'commands': commands,
                'sources': stamp['sources']}
        (EVIDENCE / 'gate.json').write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}/', flush=True)
    print('PASS Phase 1 exit gate: frozen interfaces, schema, and golden vectors, with every decision made in Fe',
          flush=True)


def run_vectors():
    saved = sys.argv
    sys.argv = ['host/vectors.py']
    try:
        return vectors.main()
    finally:
        sys.argv = saved


if __name__ == '__main__':
    main()
