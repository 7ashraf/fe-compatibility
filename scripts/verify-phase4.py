#!/usr/bin/env python3
"""Phase 4 gate: bounded layout adapter and validator.

Exit tests from the plan:
  * individual writes preserve unrelated bits;
  * boundary-width values round-trip;
  * distinct keys remain independent;
  * an intentionally shifted offset is detected;
  * overlapping or out-of-range field descriptions are rejected;
  * a passing result says exactly which slots and keys were tested.
Includes the Phase 3 gate (and therefore Phases 0-2). --record writes docs/evidence/phase4/.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402
import fecheck  # noqa: E402
import layout  # noqa: E402
import vectors  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase4'
# Seeded layout faults: Fe's first violation (category, action, index), and whether a getter-only comparison sees it.
INTENDED = {
    'fe-layout-shifted': (('neighbor', 1, 20 + 1), 'match'),
    'fe-layout-wrong-root': (('mapping-entry', 9, 0), 'match'),
    'fe-layout-clobber': (('neighbor', 3, 20), 'mismatch'),
}
MAX_ADDRESS = (1 << 160) - 1
MAX_LIMIT = (1 << 88) - 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    fe, fe_info = common.fe_compiler()
    _, solc_info = common.solc_compiler()
    commands = []

    def checked(command, show, expect=0, timeout=1800):
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True, timeout=timeout)
        commands.append({'command': show, 'exit': result.returncode,
                         'stdout': result.stdout[-4000:].replace(str(ROOT), '<root>'),
                         'stderr': result.stderr[-2000:].replace(str(ROOT), '<root>')})
        if result.returncode != expect:
            raise RuntimeError(f'{show}: exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-2000:]}')
        print('PASS ' + ' '.join(show), flush=True)
        return result

    py = sys.executable
    checked([py, 'scripts/verify-phase3.py'], ['python3', 'scripts/verify-phase3.py'])
    for backend in ([], ['--backend', 'native']):
        result = checked([fe, 'test', '.', *backend], ['fe', 'test', '.', *backend])
        if not re.search(r'test result: ok\. 30 passed; 0 failed', result.stdout):
            raise RuntimeError('Expected all 30 Fe tests, including 6 Phase 4 layout tests, to pass')
    print('PASS 6 Phase 4 layout tests (30 total) on the EVM and native backends', flush=True)

    stamp = common.load_stamp()
    fixture = layout.load()
    # The reviewed schema equals solc's own storage layout for the Solidity reference.
    solc_layout = json.loads((common.BUILD / stamp['targets']['solidity-layout']['storage_layout']).read_text())
    by_label = {s['label'].lstrip('_'): s for s in solc_layout['storage']}
    types = {'address': 't_address', 'bool': 't_bool', 'uint': 't_uint88'}
    for f in fixture['schema']['fields']:
        s = by_label[f['name']]
        if (s['slot'], s['offset'], s['type']) != (f['slot'], f['offset'], types[f['kind']]):
            raise RuntimeError(f'Schema field {f["name"]} differs from solc storage layout: {s}')
    m = fixture['schema']['mappings'][0]
    if by_label[m['name']]['slot'] != m['root'] or not by_label[m['name']]['type'].startswith('t_mapping(t_address'):
        raise RuntimeError('Mapping root differs from solc storage layout')
    print('PASS reviewed schema equals solc 0.8.31 --storage-layout for the Solidity reference', flush=True)

    # Declarations: identical except that Fe emits RawStorage getters as nonpayable instead of view.
    def canonical(target, mutability=True):
        entries = json.loads((common.BUILD / stamp['targets'][target]['abi']).read_text())
        if not mutability:
            entries = [{k: v for k, v in e.items() if k != 'stateMutability'} for e in entries]
        return vectors.canonical_abi(entries)
    if canonical('solidity-layout', False) != canonical('fe-layout', False):
        raise RuntimeError('Layout ABIs differ beyond state mutability')
    mutability = sorted(set(canonical('solidity-layout')) ^ set(canonical('fe-layout')))
    getters = {'owner', 'paused', 'limit', 'balanceOf'}
    if {json.loads(x)[1] for x in mutability} != getters or len(mutability) != 8:
        raise RuntimeError(f'Unexpected declaration differences: {mutability}')
    print('PASS layout ABIs equal apart from one recorded finding: Fe emits the 4 RawStorage getters as '
          'nonpayable, Solidity as view', flush=True)

    # Correct pair.
    result = checked([py, 'host/layout.py'], ['python3', 'host/layout.py'])
    correct = json.loads(result.stdout)
    if any(v['verdict'] != 'conforms' for v in correct['layout'].values()) or correct['differential']['verdict'] != 'match':
        raise RuntimeError(f'Correct pair failed: {correct}')
    scope = correct['layout']['right']['scope']
    if scope['slots'] != [0, 1] or len(scope['mapping_keys']) != 3 or scope['actions'] != 19:
        raise RuntimeError(f'Scope statement wrong: {scope}')
    print('PASS Solidity and Fe both conform to the schema on 19 actions (neighbors, field values, 3 keys, write '
          'sets) and match each other on raw slots and getter returns', flush=True)

    # Known slot-0 vectors: field-by-field and neighbor checks pin the full word; cross-check it exactly.
    sol = layout.run('solidity-layout', fixture, stamp)
    fe_rec = layout.run('fe-layout', fixture, stamp)
    known = []
    for i, step in enumerate(sol['steps']):
        f = step['expected_fields']
        word = int(f['owner'], 16) | (int(f['paused']) << 160) | (int(f['limit']) << 168)
        for rec in (sol, fe_rec):
            if int(rec['steps'][i]['state'][0]['value']) != word or rec['steps'][i]['state'][1]['value'] != '0':
                raise RuntimeError(f'{rec["implementation"]} action {i}: slot 0 differs from the known vector')
        known.append(f'0x{word:064x}')
    if int(known[3], 16) != MAX_ADDRESS | (1 << 160) | (MAX_LIMIT << 168):
        raise RuntimeError('Boundary vector wrong')
    print(f'PASS {len(known)} known slot-0 vectors hold on both implementations, including all-maximal '
          f'{known[3]} (max address, true, 2^88-1); slot 1 stays zero', flush=True)

    # Seeded layout faults.
    seeded = {}
    for variant, (first, getters_only) in INTENDED.items():
        r = checked([py, 'host/layout.py', '--right', variant], ['python3', 'host/layout.py', '--right', variant],
                    expect=1)
        out = json.loads(r.stdout)
        got = out['layout']['right']
        if (got['category'], got['step'], got['index']) != first or out['layout']['left']['verdict'] != 'conforms':
            raise RuntimeError(f'{variant}: Fe reported {got}, intended {first}')
        record = layout.run(variant, fixture, stamp)
        behavior = fecheck.sequence(sol['deployment'], record['deployment'],
                                    [({}, True, {**a, 'state': []}, {**b, 'state': []})
                                     for a, b in zip(sol['steps'], record['steps'])])
        if behavior['verdict'] != getters_only:
            raise RuntimeError(f'{variant}: getter-only comparison {behavior["verdict"]}, expected {getters_only}')
        seeded[variant] = {'layout': got, 'getter_only_comparison': behavior, 'layout_differential': out['differential']}
    print('PASS shifted offset (neighbor, action 1, byte 21), wrong mapping root (entry, action 9) and '
          'slot clobber (neighbor, action 3, byte 20) detected; the first two are invisible to a getter-only '
          'comparison of the same actions', flush=True)

    # Invalid schema descriptions are rejected by Fe before any action is checked.
    base = fixture['schema']
    rejections = []

    def reject(name, edit, category):
        schema = json.loads(json.dumps(base))
        edit(schema)
        got = layout.layout_check(fixture, sol, schema)
        if got['category'] != category or got['verdict'] != 'invalid-schema':
            raise RuntimeError(f'{name}: Fe gave {got}')
        rejections.append({'name': name, 'category': got['category'], 'index': got['index']})

    reject('limit overlaps paused (offset 20)', lambda s: s['fields'][2].update(offset=20), 'overlap')
    reject('limit runs past the word (offset 22)', lambda s: s['fields'][2].update(offset=22), 'out-of-range')
    reject('paused at offset 32', lambda s: s['fields'][1].update(offset=32), 'out-of-range')
    reject('19-byte address', lambda s: s['fields'][0].update(bytes=19), 'width')
    reject('33-byte uint', lambda s: s['fields'][2].update(bytes=33), 'width')
    reject('2-byte bool', lambda s: s['fields'][1].update(bytes=2), 'width')
    reject('mapping root on the packed slot', lambda s: s['mappings'][0].update(root='0'), 'root-reserved')
    reject('repeated mapping root', lambda s: s['mappings'].append(dict(s['mappings'][0])), 'duplicate-root')
    reject('nine fields', lambda s: s['fields'].extend([dict(s['fields'][2], slot='5')] * 6), 'too-many')
    print(f'PASS {len(rejections)} invalid schema descriptions rejected by Fe with specific categories', flush=True)

    if args.record:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for rec in (sol, fe_rec):
            (EVIDENCE / f'raw-{rec["implementation"]}.json').write_text(json.dumps(rec, indent=2) + '\n')
        (EVIDENCE / 'correct-pair.json').write_text(json.dumps(correct, indent=2, sort_keys=True) + '\n')
        (EVIDENCE / 'seeded.json').write_text(json.dumps(seeded, indent=2, sort_keys=True) + '\n')
        gate = {'format': 'fe-compatibility-phase4-gate-v1', 'result': 'Phase 4 exit gate passed',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': fe_info, 'solc': solc_info,
                'targets': {k: v for k, v in stamp['targets'].items() if 'layout' in k},
                'scope': scope, 'known_slot0_vectors': known, 'solc_storage_layout': solc_layout['storage'],
                'declaration_finding': mutability, 'schema_rejections': rejections,
                'seeded': {k: {'layout': v['layout'], 'getter_only': v['getter_only_comparison']['verdict']}
                           for k, v in seeded.items()},
                'commands': commands, 'sources': stamp['sources']}
        (EVIDENCE / 'gate.json').write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}/', flush=True)
    print('PASS Phase 4 exit gate: explicit layout validated in Fe over slots 0-1 and 3 declared keys', flush=True)


if __name__ == '__main__':
    main()
