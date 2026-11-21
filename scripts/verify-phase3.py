#!/usr/bin/env python3
"""Phase 3 gate: differential treasury execution.

Exit tests from the plan:
  * cap boundary, expiry equality, unauthorized access, revocation, insufficient
    funds, recipient revert, and reentry cases agree on the specified result;
  * seeded mistakes (inclusive expiry, missing event indexing, and four more)
    are detected at the earliest relevant observation;
  * a correct pair passes the same corpus.

Both implementations are built from the frozen treasury v0 spec: Solidity
written for this project, and Fe vendored from Fe Capabilities. Includes the
Phase 2 gate (and therefore Phases 0-1). --record writes docs/evidence/phase3/.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402
import treasury  # noqa: E402
import vectors  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase3'
# First divergence per scenario: (step, category). Every scenario not listed must match.
INTENDED = {
    'fe-inclusive-expiry': {'expiry-equality': (4, 'status')},
    'fe-cap-off-by-one': {'deposit-spend': (4, 'status'), 'cap-boundary': (3, 'status'), 'revocation': (11, 'status')},
    'fe-unindexed-delegate': {s: (st, 'topic-count') for s, st in (
        ('deposit-spend', 3), ('cap-boundary', 3), ('expiry-equality', 2), ('revocation', 2),
        ('insufficient-funds', 3), ('reentry', 2), ('same-transaction', 2))},
    'fe-auth-after-active': {'revocation': (6, 'error-selector')},
    'fe-revoke-event-twice': {'revocation': (4, 'log-extra')},
    'fe-no-reserve': {**{s: (st, 'state-value') for s, st in (
        ('deposit-spend', 3), ('cap-boundary', 3), ('expiry-equality', 2), ('revocation', 2),
        ('insufficient-funds', 3), ('reentry', 2))}, 'same-transaction': (2, 'log-data-byte')},
}
REQUIRED = ('cap boundary', 'expiry equality', 'unauthorized access', 'revocation', 'insufficient funds',
            'recipient revert', 'reentry', 'second operation in the same transaction works')


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
    checked([py, 'scripts/verify-phase2.py'], ['python3', 'scripts/verify-phase2.py'])
    checked([py, 'scripts/make-corpus.py', '--check'], ['python3', 'scripts/make-corpus.py', '--check'])
    stamp = common.load_stamp()
    frozen = vectors.canonical_abi(json.loads(treasury.FROZEN_ABI.read_text()))
    for target in ('solidity-treasury', 'fe-treasury'):
        if vectors.canonical_abi(json.loads((common.BUILD / stamp['targets'][target]['abi']).read_text())) != frozen:
            raise RuntimeError(f'{target}: compiled ABI differs from the frozen treasury v0 ABI')
    print('PASS Solidity and Fe treasury ABIs equal the frozen treasury v0 ABI (functions, errors, events, '
          'fallback, mutability)', flush=True)

    # Correct pair: spec oracle on both sides and full differential, all 85 actions.
    result = checked([py, 'host/treasury.py'], ['python3', 'host/treasury.py'])
    correct = json.loads(result.stdout)
    s = correct['summary']
    if not (s['spec_oracle_left'] and s['spec_oracle_right'] and s['differential_match']):
        raise RuntimeError(f'Correct pair failed: {s}')
    corpus = treasury.load()
    covered = {c for sc in corpus['scenarios'] for st in sc['steps'] for c in st['covers']}
    missing = [r for r in REQUIRED if not any(c.startswith(r) for c in covered)]
    if missing:
        raise RuntimeError(f'Corpus does not cover: {missing}')
    print(f'PASS correct pair: Solidity and Fe each meet the spec oracle on {s["actions"]} actions in '
          f'{len(corpus["scenarios"])} scenarios, and match each other step by step (12 state fields)', flush=True)
    rerun = checked([py, 'host/treasury.py'], ['python3', 'host/treasury.py'])
    if rerun.stdout != result.stdout:
        raise RuntimeError('Treasury run output is not byte-identical across runs')
    print('PASS treasury run output and reports are byte-identical across runs', flush=True)

    # Seeded faults: exactly the intended first divergence per scenario, nothing elsewhere.
    variants = {}
    for variant, intended in INTENDED.items():
        r = checked([py, 'host/treasury.py', '--right', variant], ['python3', 'host/treasury.py', '--right', variant],
                    expect=1)
        out = json.loads(r.stdout)
        got = {sid: tuple(v) for sid, v in out['summary']['first_divergence'].items()}
        if got != intended or not out['summary']['spec_oracle_left'] or out['summary']['spec_oracle_right']:
            raise RuntimeError(f'{variant}: first divergences {got}, intended {intended}; summary {out["summary"]}')
        spec_first = {sid: (v['spec_oracle']['right']['mismatches'][0]['step'],
                            v['spec_oracle']['right']['mismatches'][0]['category'])
                      for sid, v in out['scenarios'].items() if v['spec_oracle']['right']['mismatches']}
        variants[variant] = {'first_divergence': {k: list(v) for k, v in got.items()},
                             'spec_oracle_first': {k: list(v) for k, v in spec_first.items()},
                             'mismatching_steps': {sid: v['report']['decision']['mismatching_steps']
                                                   for sid, v in out['scenarios'].items()},
                             'reports': {sid: out['scenarios'][sid]['report'] for sid in intended}}
    print(f'PASS {len(INTENDED)} seeded Fe treasury faults each detected at the intended step and category in '
          'exactly the scenarios that exercise them; all other scenarios match', flush=True)
    late = {sid: (variants['fe-no-reserve']['first_divergence'][sid][0], first[0])
            for sid, first in variants['fe-no-reserve']['spec_oracle_first'].items()
            if sid in INTENDED['fe-no-reserve'] and INTENDED['fe-no-reserve'][sid][1] == 'state-value'}
    if not late or any(state >= spec for state, spec in late.values()):
        raise RuntimeError(f'State comparison should precede return/event detection for fe-no-reserve: {late}')
    print('PASS unpersisted accounting is caught by typed state at the spend itself, while return values and '
          f'events still match there (spec oracle notices {min(b - a for a, b in late.values())}-'
          f'{max(b - a for a, b in late.values())} actions later)', flush=True)

    # The spec oracle is not vacuous: a tampered expectation fails on both correct implementations.
    data = json.loads(treasury.CORPUS.read_text())
    tampered = copy.deepcopy(data)
    step = next(st for sc in tampered['scenarios'] if sc['id'] == 'cap-boundary' for st in sc['steps']
                if st['expect'].get('error') == 'CapExceeded(uint256,uint256)')
    step['expect']['args'][0] = '9'
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'corpus.json'
        path.write_text(json.dumps(tampered))
        out = treasury.run('solidity-treasury', 'fe-treasury', only=['cap-boundary'], corpus_path=path)
        oracle = out['scenarios']['cap-boundary']['spec_oracle']
        firsts = [oracle[side]['mismatches'][0] for side in ('left', 'right')]
        if not all(m['category'] == 'error-argument' and m['step'] == 2 for m in firsts) or \
                not out['summary']['differential_match']:
            raise RuntimeError(f'Tampered expectation was not caught: {oracle}')
        bad = copy.deepcopy(data)
        bad['scenarios'][0]['steps'][3]['t'] = 7
        path.write_text(json.dumps(bad))
        try:
            treasury.load(path)
        except treasury.CaseError:
            pass
        else:
            raise RuntimeError('Corpus with an inconsistent schedule was accepted')
    print('PASS a tampered expected error argument fails the spec oracle on both implementations '
          '(error-argument at the right step); an inconsistent schedule is rejected', flush=True)

    if args.record:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        raw = EVIDENCE / 'raw'
        treasury.run('solidity-treasury', 'fe-treasury', record_dir=raw)
        (EVIDENCE / 'correct-pair.json').write_text(json.dumps(correct, indent=2, sort_keys=True) + '\n')
        for variant, v in variants.items():
            (EVIDENCE / f'seeded-{variant}.json').write_text(json.dumps(v, indent=2, sort_keys=True) + '\n')
        gate = {'format': 'fe-compatibility-phase3-gate-v1', 'result': 'Phase 3 exit gate passed',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': fe_info, 'solc': solc_info,
                'targets': {k: v for k, v in stamp['targets'].items()
                            if 'treasury' in k or k in INTENDED or k.startswith('harness-')},
                'corpus_sha256': correct['corpus_sha256'], 'summary': s,
                'intended': {k: {s2: list(v2) for s2, v2 in v.items()} for k, v in INTENDED.items()},
                'state_before_spec_oracle': {k: list(v) for k, v in late.items()},
                'commands': commands, 'sources': stamp['sources']}
        (EVIDENCE / 'gate.json').write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}/', flush=True)
    print('PASS Phase 3 exit gate: the correct pair passes the treasury corpus; every seeded fault is caught at '
          'its earliest relevant observation', flush=True)


if __name__ == '__main__':
    main()
