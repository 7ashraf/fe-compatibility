#!/usr/bin/env python3
"""Phase 5 gate: release, clean checkout, and the outside-user exercise.

Static checks on this checkout:
  * MIT LICENSE, the retained Fe Apache-2.0 license, and NOTICE disclosures
    (vendored inputs, seeded faults, AI assistance);
  * every vendored file matches its provenance.json;
  * every Solidity source declares SPDX MIT;
  * no tracked file contains an absolute home-directory path.
Clean checkout: `git clone` HEAD into a fresh directory (no .tools/ or build
outputs), bootstrap the pinned compilers there (or --reuse-tools), build, and
run the full gate chain (verify-phase4.py, which includes Phases 0-3), the
demo, and a scripted dry run of the porting exercise (plant -> mismatch at the
intended action -> fix -> passing report, with no checker edit).
The outside-user exercise itself needs a person; this runner reports it from
docs/reviewer-feedback.md and never marks it complete itself.
Requires a clean working tree. --record writes docs/evidence/phase5.json.
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
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'host'))
import common  # noqa: E402

EVIDENCE = ROOT / 'docs/evidence/phase5.json'
PLANT = ('    if amount > context.available {', '    if amount >= context.available {')


def git(*args, cwd=ROOT):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def static_checks():
    if not (ROOT / 'LICENSE').read_text().startswith('MIT License\n\nCopyright (c) 2026 Fe Compatibility contributors'):
        raise RuntimeError('LICENSE is not the project MIT license')
    if 'Version 2.0, January 2004' not in (ROOT / 'licenses/Fe-APACHE-2.0.txt').read_text()[:300]:
        raise RuntimeError('Retained Fe Apache-2.0 license missing')
    notice = (ROOT / 'NOTICE.md').read_text()
    for needle in ('ba6893c5e847b9f1e2c7479ef00f2489972a2691', 'AI assistance', 'Claude Opus 5.5',
                   'deliberately seeded', 'contracts/fe/treasury/', 'fully independent oracle'):
        if needle not in notice:
            raise RuntimeError(f'NOTICE.md does not disclose {needle!r}')
    vendored = 0
    for provenance in ('spec/vendor/treasury-v0/provenance.json', 'contracts/fe/treasury/provenance.json'):
        base = (ROOT / provenance).parent
        for path, digest in json.loads((ROOT / provenance).read_text())['files'].items():
            if common.sha(base / path) != digest:
                raise RuntimeError(f'Vendored file changed: {base / path}')
            vendored += 1
    tracked = git('ls-files').split()
    sol = [p for p in tracked if p.endswith('.sol')]
    if any(not (ROOT / p).read_text().startswith('// SPDX-License-Identifier: MIT\n') for p in sol):
        raise RuntimeError('Every Solidity source must declare SPDX MIT')
    leaked = []
    for p in tracked:
        try:
            if re.search(r'/(Users|home)/[A-Za-z0-9._-]+/', (ROOT / p).read_text()):
                leaked.append(p)
        except UnicodeDecodeError:
            continue
    if leaked:
        raise RuntimeError(f'Absolute home paths in tracked files: {leaked}')
    print(f'PASS licenses, NOTICE disclosures, {vendored} vendored file hashes, SPDX MIT on {len(sol)} Solidity '
          f'sources, no absolute paths in {len(tracked)} tracked files', flush=True)
    return {'vendored_files': vendored, 'solidity_sources': len(sol), 'tracked_files': len(tracked)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--reuse-tools', action='store_true', help="use this checkout's pinned compilers")
    args = parser.parse_args()
    os.chdir(ROOT)
    if git('status', '--porcelain', '--untracked-files=all').strip():
        raise SystemExit('Working tree is not clean; commit first (only committed content is cloned).')
    commit = git('rev-parse', 'HEAD').strip()
    summary = static_checks()
    commands = []
    with tempfile.TemporaryDirectory(prefix='fe-compat-phase5-') as directory:
        clone = Path(directory) / 'fe-compatibility'
        subprocess.run(['git', 'clone', '--quiet', '--no-local', str(ROOT), str(clone)], check=True)
        if git('rev-parse', 'HEAD', cwd=clone).strip() != commit or (clone / '.tools').exists():
            raise RuntimeError('Clone is not a clean checkout of HEAD')
        print(f'PASS fresh clone of {commit[:12]} without .tools/ or build outputs', flush=True)
        env = {k: v for k, v in os.environ.items() if k not in ('FE_BIN', 'SOLC_BIN')}
        env['PATH'] = f'{clone / ".tools/bin"}{os.pathsep}{env["PATH"]}'
        if args.reuse_tools:
            env.update(FE_BIN=str(ROOT / '.tools/bin/fe'), SOLC_BIN=str(ROOT / '.tools/bin/solc'))

        def checked(*command, expect=0, timeout=3600):
            started = time.monotonic()
            result = subprocess.run([sys.executable if c == 'python3' else c for c in command], cwd=clone, env=env,
                                    capture_output=True, text=True, timeout=timeout)
            scrub = lambda s: s.replace(str(clone), '<clone>').replace(str(ROOT), '<root>')
            commands.append({'command': list(command), 'exit': result.returncode,
                             'seconds': round(time.monotonic() - started, 1),
                             'stdout': scrub(result.stdout)[-6000:], 'stderr': scrub(result.stderr)[-2000:]})
            if result.returncode != expect:
                raise RuntimeError(f'{" ".join(command)}: exit {result.returncode}\n{result.stdout[-3000:]}\n'
                                   f'{result.stderr[-2000:]}')
            print(f'PASS (clone) {" ".join(command)}  [{commands[-1]["seconds"]} s]', flush=True)
            return result

        if not args.reuse_tools:
            checked('python3', 'scripts/bootstrap-fe.py')
            checked('python3', 'scripts/bootstrap-solc.py')
        checked('python3', 'scripts/build.py')
        checked('python3', 'scripts/verify-phase4.py')
        demo = checked('python3', 'scripts/demo.py')
        # Scripted dry run of the porting exercise (the implementing agent's own; not the outside-user test).
        checked('python3', 'scripts/port-exercise.py', 'start')
        policy = clone / 'exercise/policy/src/policy.fe'
        text = policy.read_text()
        if text.count(PLANT[0]) != 1:
            raise RuntimeError('Exercise plant no longer applies')
        policy.write_text(text.replace(*PLANT))
        found = checked('python3', 'scripts/port-exercise.py', 'check', expect=1)
        if 'insufficient-funds: action insufficient-funds-3' not in found.stdout or 'status:' not in found.stdout:
            raise RuntimeError(f'Exercise did not locate the planted mistake:\n{found.stdout}')
        policy.write_text(text)
        checked('python3', 'scripts/port-exercise.py', 'check')
        timing = json.loads(checked('python3', 'scripts/port-exercise.py', 'status').stdout)
        if git('status', '--porcelain', cwd=clone).strip():
            raise RuntimeError('The clone has tracked changes: the exercise or gates edited the checker')
        print('PASS exercise dry run: planted `amount >= available` located at insufficient-funds-3 (status), '
              'fixed, passing report; no tracked file changed', flush=True)
    feedback = (ROOT / 'docs/reviewer-feedback.md').read_text()
    received = 'Status: **received**' in feedback
    summary.update(commit=commit, tools='reused pinned compilers' if args.reuse_tools else 'bootstrapped in clone',
                   exercise_dry_run={'planted': PLANT, 'located': 'insufficient-funds-3 status', 'timing': timing},
                   demo=demo.stdout, outside_user='received' if received else 'pending')
    if args.record:
        gate = {'format': 'fe-compatibility-phase5-gate-v1',
                'result': 'Phase 5 exit gate passed' if received else
                          'Phase 5 release checks passed from a clean clone; outside-user exercise pending',
                'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'host': platform.platform(),
                'python': platform.python_version(), 'fe': common.fe_compiler()[1], 'solc': common.solc_compiler()[1],
                'summary': summary, 'commands': commands}
        EVIDENCE.write_text(json.dumps(gate, indent=2).replace(str(ROOT), '<root>') + '\n')
        print(f'Recorded {EVIDENCE.relative_to(ROOT)}', flush=True)
    print('PASS Phase 5 release checks (clean clone, every gate, demo, exercise dry run, licenses and provenance)',
          flush=True)
    print('PASS outside-user exercise recorded' if received else
          'PENDING outside-user exercise: another person must run docs/tester-guide.md and fill in '
          'docs/reviewer-feedback.md', flush=True)


if __name__ == '__main__':
    main()
