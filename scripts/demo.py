#!/usr/bin/env python3
"""Three-minute demo of fe-compatibility (requires `python3 scripts/build.py` and pinned anvil/cast).

1. The Solidity and Fe treasuries agree on the frozen v0 corpus (85 actions).
2. A seeded Fe port with inclusive expiry is located at the exact action.
3. A seeded Fe storage layout with a shifted packed offset: a getter-only
   comparison sees nothing, and Fe layout mode locates the overwritten byte.
Each claim is checked; the demo exits non-zero if any expectation fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'host'))
import common  # noqa: E402
import fecheck  # noqa: E402
import layout  # noqa: E402
import treasury  # noqa: E402


def fail(message):
    sys.exit(f'FAIL: {message}')


def main():
    print('1) Solidity treasury vs Fe treasury, frozen v0 corpus')
    out = treasury.run('solidity-treasury', 'fe-treasury')
    s = out['summary']
    if not (s['spec_oracle_left'] and s['spec_oracle_right'] and s['differential_match']):
        fail(f'correct pair: {s}')
    print(f'   no mismatch observed on {s["actions"]} actions in {len(out["scenarios"])} scenarios: status, exact '
          'returndata, exact events, and 12 state fields after every action, decided by the Fe checker')

    print('\n2) Fe port with a seeded inclusive-expiry check (now > expiresAt instead of >=)')
    out = treasury.run('solidity-treasury', 'fe-inclusive-expiry', only=['expiry-equality'])
    report = out['scenarios']['expiry-equality']['report']
    m = report['mismatches'][0]
    if (m['step'], m['category']) != (4, 'status'):
        fail(f'inclusive expiry located at {m["step"]} {m["category"]}')
    print(f'   first divergence: action {m["action"]["id"]}, spend at exactly the expiry second')
    print(f'   {m["category"]}: Solidity {m["explanation"]["left"]} / Fe port {m["explanation"]["right"]}')

    print('\n3) Fe storage layout with paused written one byte too high')
    stamp = common.load_stamp()
    fixture = layout.load()
    sol = layout.run('solidity-layout', fixture, stamp)
    bad = layout.run('fe-layout-shifted', fixture, stamp)
    behavior = fecheck.sequence(sol['deployment'], bad['deployment'],
                                [({}, True, {**a, 'state': []}, {**b, 'state': []})
                                 for a, b in zip(sol['steps'], bad['steps'])])
    found = layout.layout_check(fixture, bad)
    if behavior['verdict'] != 'match' or (found['category'], found['step']) != ('neighbor', 1):
        fail(f'layout demo: behavior {behavior["verdict"]}, layout {found}')
    print(f'   getter-only comparison of the same {len(sol["steps"])} actions: {behavior["verdict"]} (the bug is invisible)')
    print(f'   layout mode: {found["category"]}: {found["explanation"]}')
    print('\nPASS demo')


if __name__ == '__main__':
    main()
