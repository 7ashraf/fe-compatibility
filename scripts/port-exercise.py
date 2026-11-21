#!/usr/bin/env python3
"""Porting exercise: introduce, locate, and fix a porting mistake without touching the checker.

  python3 scripts/port-exercise.py start     # copy the Fe treasury port into exercise/ (git-ignored)
  # ...edit exercise/policy/src/*.fe or exercise/treasury/src/lib.fe...
  python3 scripts/port-exercise.py check     # build exercise/ and compare it with the Solidity reference
  python3 scripts/port-exercise.py diff      # what differs from the reviewed Fe port
  python3 scripts/port-exercise.py status    # timings: start -> first mismatch -> passing again

`check` runs the whole treasury corpus (11 scenarios, 85 actions) against the
Solidity reference. It prints the first divergence per scenario (action,
category, explanation, and both values) and writes the full
fe-compatibility-report to exercise/report-N.json. Every check is logged in
exercise/session.json with its elapsed time, so time-to-locate and
time-to-fix can be measured.

Exit status: 0 passing report, 1 mismatch found, 2 no exercise started,
3 the edited port does not compile (or another infrastructure error).
"""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402

WORK = ROOT / 'exercise'
SESSION = WORK / 'session.json'
SOURCE = ROOT / 'contracts/fe/treasury'
OUT = common.BUILD / 'exercise'
FILES = ('policy/src/policy.fe', 'policy/src/types.fe', 'policy/src/lib.fe', 'treasury/src/lib.fe')


def now():
    return datetime.now(timezone.utc).isoformat()


def digest():
    h = hashlib.sha256()
    for f in FILES:
        h.update((WORK / f).read_bytes())
    return h.hexdigest()


def start(force):
    if WORK.exists() and not force:
        print(f'{WORK.relative_to(ROOT)}/ already exists; use --force to start over')
        return 2
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(SOURCE, WORK, ignore=shutil.ignore_patterns('out', 'upstream', 'provenance.json'))
    SESSION.write_text(json.dumps({'started_utc': now(), 'started_monotonic': time.time(),
                                   'reviewed_sha256': digest(), 'checks': []}, indent=2) + '\n')
    print(f'Copied the reviewed Fe treasury port to {WORK.relative_to(ROOT)}/. Edit the .fe files there, then run '
          '`python3 scripts/port-exercise.py check`.')
    return 0


def summarize(out):
    lines, firsts = [], {}
    for sid, v in out['scenarios'].items():
        report = v['report']
        if report['decision']['verdict'] == 'match':
            continue
        m = report['mismatches'][0]
        e = m['explanation']
        firsts[sid] = {'action': m['action'].get('id'), 'category': m['category'], 'what': e.get('what')}
        lines.append(f'  {sid}: action {m["action"].get("id")} ({m["action"].get("call")} '
                     f'{m["action"].get("argument")} from {m["action"].get("from")})')
        lines.append(f'      {m["category"]}: {e.get("what")}')
        if 'left' in e or 'right' in e:
            lines.append(f'      Solidity reference: {e.get("left")}    your port: {e.get("right")}')
        lines.append(f'      ({report["decision"]["mismatching_steps"]} of {report["decision"]["steps_compared"]} '
                     'actions differ in this scenario)')
    return lines, firsts


def check():
    if not SESSION.exists():
        print('No exercise started; run `python3 scripts/port-exercise.py start` first')
        return 2
    session = json.loads(SESSION.read_text())
    fe, _ = common.fe_compiler()
    shutil.rmtree(OUT, ignore_errors=True)
    built = subprocess.run([str(fe), 'build', str(WORK / 'treasury'), '--backend', 'sonatina', '--profile', 'release',
                            '-O', '1', '--emit', 'bytecode,runtime-bytecode,abi,metadata', '--out-dir', str(OUT)],
                           capture_output=True, text=True, timeout=300)
    entry = {'utc': now(), 'elapsed_seconds': round(time.time() - session['started_monotonic'], 1),
             'source_sha256': digest(), 'unchanged': digest() == session['reviewed_sha256']}
    if built.returncode:
        entry['result'] = 'does-not-compile'
        session['checks'].append(entry)
        SESSION.write_text(json.dumps(session, indent=2) + '\n')
        print('Your edited port does not compile (this is not a conformance result):\n')
        print((built.stdout + built.stderr).replace(str(ROOT) + '/', '')[-4000:])
        return 3
    identity = {'creation': 'exercise/Treasury.bin', 'runtime': 'exercise/Treasury.runtime.bin',
                'abi': 'exercise/Treasury.abi.json', 'compiler': 'fe 26.5.0 (3dab95f)',
                'settings': 'fe build --backend sonatina --profile release -O 1',
                'source': 'exercise/ (edited copy of contracts/fe/treasury)',
                'creation_sha256': common.hex_sha(OUT / 'Treasury.bin')}
    import treasury
    try:
        out = treasury.run('solidity-treasury', 'exercise', extra_targets={'exercise': identity})
    except (common.InfrastructureError, OSError) as error:
        print(f'Infrastructure error (not a conformance result): {error}')
        return 3
    n = len(session['checks']) + 1
    (WORK / f'report-{n}.json').write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    lines, firsts = summarize(out)
    passing = out['summary']['differential_match'] and out['summary']['spec_oracle_right']
    entry.update(result='pass' if passing else 'mismatch', first_divergences=firsts, report=f'report-{n}.json')
    session['checks'].append(entry)
    SESSION.write_text(json.dumps(session, indent=2) + '\n')
    actions = out['summary']['actions']
    if passing:
        print(f'PASS: no mismatch observed on {actions} actions in {len(out["scenarios"])} scenarios '
              '(status, returndata, events, and 12 state fields after every action). '
              f'Full report: exercise/report-{n}.json')
        return 0
    print(f'MISMATCH: your port differs from the Solidity reference in {len(firsts)} of {len(out["scenarios"])} '
          'scenarios. The first divergence in each:\n')
    print('\n'.join(lines))
    print(f'\nFull report (raw bytes and every listed mismatch): exercise/report-{n}.json')
    return 1


def diff():
    if not WORK.exists():
        print('No exercise started')
        return 2
    changed = False
    for f in FILES:
        a, b = (SOURCE / f).read_text().splitlines(), (WORK / f).read_text().splitlines()
        for line in difflib.unified_diff(a, b, f'reviewed/{f}', f'exercise/{f}', lineterm=''):
            print(line)
            changed = True
    if not changed:
        print('exercise/ is identical to the reviewed port')
    return 0


def status():
    if not SESSION.exists():
        print('No exercise started')
        return 2
    session = json.loads(SESSION.read_text())
    checks = session['checks']
    first_bad = next((c for c in checks if c['result'] == 'mismatch'), None)
    fixed = next((c for c in checks if first_bad and c['result'] == 'pass' and
                  c['elapsed_seconds'] > first_bad['elapsed_seconds']), None)
    summary = {'started_utc': session['started_utc'], 'checks': len(checks),
               'first_mismatch_at_seconds': first_bad and first_bad['elapsed_seconds'],
               'first_mismatch': first_bad and first_bad['first_divergences'],
               'passing_again_at_seconds': fixed and fixed['elapsed_seconds'],
               'fix_seconds_after_first_mismatch': fixed and round(fixed['elapsed_seconds'] -
                                                                   first_bad['elapsed_seconds'], 1)}
    print(json.dumps(summary, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('start', 'check', 'diff', 'status'))
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    return {'start': lambda: start(args.force), 'check': check, 'diff': diff, 'status': status}[args.command]()


if __name__ == '__main__':
    sys.exit(main())
