#!/usr/bin/env python3
"""Phase 2 gate: the reusable Fe conformance engine.

Exit tests from the plan:
  * detect missing / reordered / extra logs, changed indexed values, a wrong
    custom-error payload, success versus revert, mismatched state after a
    superficially matching return, and oversized payloads;
  * every negative test fails because of its intended difference.

Checked three ways:
  1. pure Fe unit tests on both backends (src/phase2_tests.fe: each negative
     case changes one thing from a matching positive control);
  2. real EVM: six seeded Fe ports of Meter v0, each with one porting mistake,
     against the Solidity reference. Every listed mismatch must be exactly the
     intended one, and the correct Fe port must match;
  3. perturbations of real records sent through the native Fe checker, for the
     cases the Meter cannot produce (reordering, oversize, over-limit
     listing), plus report-format and determinism checks.
Includes the Phase 1 gate, which includes Phase 0. --record writes docs/evidence/phase2/.
"""
import argparse
import copy
from datetime import datetime, timezone
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
import observe  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase2'
# Intended detection per seeded variant: every listed mismatch as (step, category, log, index, slot).
INTENDED = {
    'fe': [],
    'fe-faulty': [(2, 'error-argument', 0, 67, 1)],
    'fe-state': [(3, 'state-value', 0, 0, 0), (4, 'returndata-byte', 0, 31, 0)],
    'fe-unindexed': [(0, 'topic-count', 0, 0, 0), (3, 'topic-count', 0, 0, 0)],
    'fe-extra-log': [(0, 'log-extra', 1, 1, 0), (3, 'log-extra', 1, 1, 0)],
    'fe-wrong-error': [(1, 'error-selector', 0, 0, 0)],
    'fe-no-empty-check': [(1, 'status', 0, 0, 0)],
}
# Declaration differences the ABI comparison must report (Fe emits only errors that are raised).
DECLARATIONS = {'fe-wrong-error': ['EmptyQuantity()'], 'fe-no-empty-check': ['EmptyQuantity()']}
TOP = {'format', 'version', 'mode', 'corpus', 'configuration', 'tools', 'environment', 'raw_records_sha256',
       'decision', 'claim', 'state_declared', 'mismatches', 'gas_used', 'abi_declarations'}
CATEGORIES = {'status', 'returndata-length', 'returndata-byte', 'log-count', 'log-emitter', 'topic-count', 'topic',
              'log-data-length', 'log-data-byte', 'error-selector', 'error-argument', 'log-missing', 'log-extra',
              'log-reordered', 'state-count', 'state-kind', 'state-value'}


def validate_report(report):
    """Structural check of fe-compatibility-report v1 (spec/report.md)."""
    if not TOP <= set(report) or report['format'] != 'fe-compatibility-report' or report['version'] != 1:
        raise RuntimeError(f'Report keys/format wrong: {sorted(report)}')
    d = report['decision']
    if d['verdict'] not in ('match', 'mismatch', 'malformed', 'not-comparable') or d['listed'] > 8 \
            or d['listed'] != len(report['mismatches']) or d['truncated'] != (d['mismatching_steps'] > d['listed']):
        raise RuntimeError(f'Report decision inconsistent: {d}')
    for m in report['mismatches']:
        if m['category'] not in CATEGORIES or not {'strict', 'explanation', 'location', 'fe', 'action'} <= set(m) \
                or not m['explanation'].get('what'):
            raise RuntimeError(f'Report mismatch entry incomplete: {m}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    fe, fe_info = common.fe_compiler()
    _, solc_info = common.solc_compiler()
    commands = []

    def checked(command, show, expect=(0,), timeout=900):
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True, timeout=timeout)
        commands.append({'command': show, 'exit': result.returncode,
                         'stdout': result.stdout[-6000:].replace(str(ROOT), '<root>'),
                         'stderr': result.stderr[-2000:].replace(str(ROOT), '<root>')})
        if result.returncode not in expect:
            raise RuntimeError(f'{show}: exit {result.returncode}\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}')
        print('PASS ' + ' '.join(show), flush=True)
        return result

    py = sys.executable
    checked([py, 'scripts/verify-phase1.py'], ['python3', 'scripts/verify-phase1.py'])
    phase2_tests = ('positive_controls_match', 'missing_extra_and_reordered_logs', 'changed_indexed_value',
                    'wrong_custom_error_and_payload', 'success_versus_revert',
                    'state_mismatch_behind_matching_return_and_logs', 'earlier_observation_classes_win_within_a_step',
                    'address_state_is_normalized_by_type_only', 'malformed_reasons_are_specific',
                    'listing_is_bounded_ordered_and_counted')
    for backend in ([], ['--backend', 'native']):
        result = checked([fe, 'test', '.', *backend], ['fe', 'test', '.', *backend])
        count = re.search(r'test result: ok\. ([0-9]+) passed; 0 failed', result.stdout)
        if not count or int(count.group(1)) < 24 or \
                any(f'PASS  [' not in line for t in phase2_tests for line in result.stdout.splitlines()
                    if line.endswith(' ' + t)):
            raise RuntimeError('Expected at least 24 Fe tests, including the 10 Phase 2 tests, to pass with none failing')
    print('PASS 10 Phase 2 engine tests (all Fe tests pass) on the EVM and native backends', flush=True)

    # Real EVM corpus: the Solidity reference against the correct and six seeded Fe ports.
    reports = {}
    for variant, intended in INTENDED.items():
        result = checked([py, 'host/observe.py', '--left', 'solidity', '--right', variant],
                         ['python3', 'host/observe.py', '--left', 'solidity', '--right', variant],
                         expect=(1,) if intended or variant in DECLARATIONS else (0,))
        report = json.loads(result.stdout)
        validate_report(report)
        got = [(m['step'], m['category'], m['location']['log'], m['location']['index'], m['location']['slot'])
               for m in report['mismatches']]
        if got != intended or report['decision']['mismatching_steps'] != len(intended):
            raise RuntimeError(f'{variant}: Fe listed {got}, intended {intended}')
        missing = report['abi_declarations']['right']['missing']
        if missing != DECLARATIONS.get(variant, []) or report['abi_declarations']['left']['missing']:
            raise RuntimeError(f'{variant}: declaration differences {report["abi_declarations"]}')
        reports[variant] = report
    print(f'PASS correct Fe port matches; {len(INTENDED) - 1} seeded ports each detected exactly at the intended '
          'step, category, and location (and nowhere else)', flush=True)
    repeat = checked([py, 'host/observe.py', '--left', 'solidity', '--right', 'fe-state'],
                     ['python3', 'host/observe.py', '--left', 'solidity', '--right', 'fe-state'], expect=(1,))
    if repeat.stdout != observe.reporting.render(reports['fe-state']):
        raise RuntimeError('Report is not byte-identical across runs')
    print('PASS reports are deterministic (byte-identical rerun) and valid fe-compatibility-report v1', flush=True)

    # Perturbations of the real Solidity record through the Fe checker.
    stamp = common.load_stamp()
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run([py, 'host/observe.py', '--left', 'solidity', '--right', 'fe', '--record-dir', directory],
                       capture_output=True, check=True)
        base = json.loads((Path(directory) / 'raw-solidity.json').read_text())
    cases = []

    def case(name, mutate, expected, left_mutate=None):
        left, right = copy.deepcopy(base), copy.deepcopy(base)
        if left_mutate:
            left_mutate(left['steps'])
        mutate(right['steps'])
        decision, _ = observe.check(left, right, raise_malformed=False)
        first = decision['mismatches'][0] if decision['mismatches'] else {}
        got = ('malformed', decision['malformed']['reason']) if decision['verdict'] == 'malformed' else \
            (first.get('step'), first.get('category'), first.get('index'))
        if got != expected:
            raise RuntimeError(f'{name}: Fe gave {decision}')
        cases.append({'name': name, 'expected': list(expected), 'decision': decision})

    def second_log(steps):
        log = copy.deepcopy(steps[0]['logs'][0])
        log['data'] = log['data'][:-2] + '07'
        steps[0]['logs'].append(log)

    def swap(steps):
        second_log(steps)
        steps[0]['logs'].reverse()

    def drop_first(steps):
        second_log(steps)
        steps[0]['logs'].pop(0)

    def flip_topic(steps):
        topic = steps[3]['logs'][0]['topics'][1]
        steps[3]['logs'][0]['topics'][1] = topic[:-1] + ('0' if topic[-1] != '0' else '1')

    def flip_arg(steps):
        data = steps[2]['returndata']
        steps[2]['returndata'] = data[:-1] + ('5' if data[-1] != '5' else '6')

    case('reordered logs', swap, (0, 'log-reordered', 0), left_mutate=second_log)
    case('missing first of two logs', drop_first, (0, 'log-missing', 0), left_mutate=second_log)
    case('extra log', second_log, (0, 'log-extra', 1))
    case('changed indexed caller', flip_topic, (3, 'topic', 1))
    case('wrong error payload', flip_arg, (2, 'error-argument', 67))
    case('success instead of revert', lambda s: s[1].update(success=True), (1, 'status', 0))
    case('state after a matching return', lambda s: s[3]['state'][0].update(value='106'), (3, 'state-value', 0))
    case('oversized returndata', lambda s: s[0].update(returndata='0x' + '00' * 300), ('malformed', 'oversized'))
    case('five logs', lambda s: s[0].update(logs=s[0]['logs'] * 5), ('malformed', 'too-many-logs'))
    case('oversized log data', lambda s: s[0]['logs'][0].update(data='0x' + '00' * 257), ('malformed', 'oversized'))

    # Output limit: 15 steps that all differ list 8, count 15, and keep step order.
    left, right = copy.deepcopy(base), copy.deepcopy(base)
    left['steps'] = left['steps'] * 3
    right['steps'] = copy.deepcopy(left['steps'])
    for s in right['steps']:
        s['state'][0]['value'] = str(int(s['state'][0]['value']) + 1)
    decision, _ = observe.check(left, right)
    if not (decision['mismatching_steps'] == 15 and decision['listed'] == 8 and decision['truncated']
            and [m['step'] for m in decision['mismatches']] == list(range(8))):
        raise RuntimeError(f'Output limit wrong: {decision}')
    cases.append({'name': '15 mismatching steps', 'expected': ['listed 8 of 15, truncated, step order'],
                  'decision': {k: decision[k] for k in ('mismatching_steps', 'listed', 'truncated')}})
    print(f'PASS {len(cases)} perturbations of real records classified by Fe as intended '
          '(reorder, missing, extra, indexed value, error payload, status, state, oversize, limits)', flush=True)

    if args.record:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        for variant, report in reports.items():
            (EVIDENCE / f'report-solidity-vs-{variant}.json').write_text(observe.reporting.render(report))
        gate = {'format': 'fe-compatibility-phase2-gate-v1', 'result': 'Phase 2 exit gate passed',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': fe_info, 'solc': solc_info,
                'targets': {k: stamp['targets'][k] for k in ('solidity', *INTENDED)},
                'intended': {k: [list(x) for x in v] for k, v in INTENDED.items()},
                'perturbations': cases, 'commands': commands, 'sources': stamp['sources']}
        (EVIDENCE / 'gate.json').write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}/', flush=True)
    print('PASS Phase 2 exit gate: every intended difference detected by the Fe engine, and only that difference',
          flush=True)


if __name__ == '__main__':
    main()
