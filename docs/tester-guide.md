# Tester guide: find a porting mistake with fe-compatibility

This takes about 20 minutes, and you don't need to read the checker's source.
It's meant for someone who didn't build this project. Please record what
actually happens, including setup trouble and anything confusing, in
[reviewer-feedback.md](reviewer-feedback.md), or send the answers to the
project owner.

## 1. Prerequisites

- macOS on Apple silicon (the only verified platform), or Linux x86-64 / arm64
  (assets are pinned but untested; please report what happens).
- Python 3.10 or newer, curl, and git.
- Foundry **1.5.1-stable** at commit `b0a9dd9ceda36f63e2326ce530c10e6916f4b8a2`,
  with `anvil` and `cast` on PATH. Other builds are refused.

## 2. Set up (from the repository root)

```sh
python3 scripts/bootstrap-fe.py      # Fe 26.5.0, checksum-verified
python3 scripts/bootstrap-solc.py    # Solidity 0.8.31, checksum-verified
source scripts/env.sh
python3 scripts/build.py
```

## 3. See it work

```sh
python3 scripts/demo.py
```

The demo prints three results:

1. The Solidity and Fe treasuries agree on 85 actions.
2. A deliberately planted Fe bug, an off-by-one expiry, is located at the
   exact action.
3. A storage-layout bug is located even though the contract's getters hide it.

## 4. The porting exercise

Ideally, someone else plants a mistake and you find it. If you're alone, plant
one yourself and see whether the report leads you back to it.

```sh
python3 scripts/port-exercise.py start   # copies the Fe treasury port into exercise/
```

**The helper** (or you) changes one thing in `exercise/policy/src/policy.fe`
or `exercise/treasury/src/lib.fe`. For example: a comparison, the order of two
checks, an event field, or an error argument. It must still compile. Don't
edit anything outside `exercise/`.

**The tester** runs:

```sh
python3 scripts/port-exercise.py check
```

`check` builds the edited port and runs the treasury corpus against the
Solidity reference. For each affected scenario it prints:

- the first diverging action (who called what, with which arguments);
- the category, for example `status`, `error-argument`, `topic-count`, or
  `state-value`;
- a plain-language explanation;
- the reference's value next to yours.

The full report, with raw bytes, is written to `exercise/report-N.json`. Using
only that output, find the line, fix it, and run `check` again until it
prints `PASS`.

```sh
python3 scripts/port-exercise.py status  # time to the first mismatch and time to fix
python3 scripts/port-exercise.py diff    # afterwards: what was changed
```

Exit codes:

- 0: passing report.
- 1: mismatch.
- 3: the edited port doesn't compile. That's a build problem, never a
  conformance verdict.

## 5. Optional: the full gates

```sh
python3 scripts/verify-phase4.py   # about 1 minute; includes Phases 0-3
python3 scripts/verify-phase5.py   # fresh clone, licenses and provenance, demo, exercise dry run (needs a clean tree)
```
