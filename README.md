# fe-compatibility

Run the same actions against a Solidity contract and its Fe port, capture the
raw EVM observations (status, exact returndata or revert bytes, and ordered
logs), and let a **Fe checker** decide whether they match. When they don't, it
reports the first divergence.

**Status: Phase 0–4 exit gates passed** ([feasibility](docs/feasibility.md)).
Phase 5 (a second integration with an outside user, and the release) is not
started. Passing means "no mismatch
observed for this corpus under this configuration". It never means the
contracts are equivalent.

## Quick start

Requires Python 3.10+, curl, and Foundry 1.5.1-stable (Anvil/Cast, commit
`b0a9dd9c`) on PATH. Verified on macOS arm64 only.

```sh
python3 scripts/bootstrap-fe.py && python3 scripts/bootstrap-solc.py
source scripts/env.sh
python3 scripts/build.py
python3 host/observe.py --left solidity --right fe          # exit 0: no mismatch on 5 calls
python3 host/observe.py --left solidity --right fe-faulty   # exit 1: Fe locates the one-byte difference
python3 scripts/verify-phase0.py                            # whole Phase 0 gate, about 4 s
python3 host/vectors.py                                     # Phase 1 ABI conformance on 28 golden vectors
python3 scripts/verify-phase1.py                            # Phase 1 gate (includes Phase 0), about 10 s
python3 host/observe.py --right fe-state                    # report: state differs behind a matching return
python3 scripts/verify-phase2.py                            # Phase 2 gate (includes 0-1), about 26 s
python3 host/treasury.py                                    # treasury v0: Solidity vs Fe over 85 actions
python3 host/treasury.py --right fe-inclusive-expiry        # a seeded porting mistake, located
python3 scripts/verify-phase3.py                            # Phase 3 gate (includes 0-2), about 46 s
python3 host/layout.py --right fe-layout-shifted            # layout mode: a shifted packed offset, located
python3 scripts/verify-phase4.py                            # Phase 4 gate (includes 0-3), about 59 s
```

**Layout mode** ([spec/layout-v1.md](spec/layout-v1.md)) checks an explicit
packed layout: an address, a bool, and a `uint88` in slot 0, and a mapping at
slot 1. The Fe adapter uses only `SolSlot`, `SolWord`, and `SolMapping`. The
Fe validator (`src/layout.fe`) rejects overlapping or out-of-range schemas.
For every action it checks that bits outside the written field are untouched,
that each field decodes correctly, that entries at independently derived
slots hold their values, and that every slot written was declared. A shifted
offset and a wrong mapping root are caught by layout mode, while a getter-only
comparison of the same actions sees nothing.

The treasury corpus (`fixtures/behavior/treasury-v0.json`,
[spec/scenarios.md](spec/scenarios.md)) has 11 scenarios. They cover the cap
boundary, expiry equality, unauthorized access, revocation, insufficient
funds, a rejecting recipient, reentry, two spends in one transaction, and
dispatch. Each action's outcome is written from the frozen spec. The Fe
checker compares each implementation with that outcome and the two
implementations with each other, including 12 typed state fields after every
action. Six seeded Fe treasury ports (`fe-inclusive-expiry`,
`fe-cap-off-by-one`, `fe-unindexed-delegate`, `fe-auth-after-active`,
`fe-revoke-event-twice`, `fe-no-reserve`) are each caught at their earliest
relevant step.

Reports follow [spec/report.md](spec/report.md). Each listed mismatch has
Fe's category and location, the exact raw bytes, and a typed explanation. Six
seeded Fe ports (`--right fe-faulty`, `fe-state`, `fe-unindexed`,
`fe-extra-log`, `fe-wrong-error`, `fe-no-empty-check`) each show one porting
mistake caught at the intended step.

The frozen interfaces are indexed in [spec/interface.md](spec/interface.md):
Codec v1 for ABI conformance, and treasury v0 vendored from Fe Capabilities.
Formats, limits, and the address-normalization allowlist are in
[spec/schema.md](spec/schema.md). The golden vectors in
`fixtures/abi/codec-v1.json` are encoded by `cast`, independently of both
compilers under test.

The seeded `fe-faulty` port reports `TooLarge(200, 101)` instead of
`TooLarge(200, 100)`. Fe reports step 2 `add(200)`, `returndata-byte`, offset
67, `100` vs `101`, along with both raw payloads.

## Where the Fe is

- `src/observation.fe`: typed raw observations. Payloads are an explicit byte
  length plus 32-byte words, and the module enforces well-formedness rules
  (zero padding, caps, no logs on reverts).
- `src/conformance.fe`: strict comparison in a fixed order (status, then
  error selector and arguments or exact returndata, then the log sequence and
  fields, then typed state). It uses 17 categories, including
  missing, extra, and reordered logs and state behind a matching return. It
  reports the first divergence and a bounded, ordered list of up to 8
  mismatches, with a total count. A failed
  deployment makes the result `not-comparable`, and compiler-generated
  rejections can be compared in a status-only scope.
- `src/abi.fe`: an ABI conformance validator. It reports `selector`,
  `truncated`, `extra`, `type` (dirty high bits or missing sign extension),
  `offset`, `length`, or `padding`, with the slot index.
- `src/normalize.fe`: address normalization through per-world role tables.
  Only allowlisted positions are rewritten (emitters, plus address-typed
  returns, topics, and data words).
- `host/checker-native/`: a bounded stdin/stdout transport that runs the
  checker as a native Fe executable.
- `contracts/fe/meter/`: the Fe port, plus a `try_call` test of exact error bytes.

Python (`host/observe.py`) starts an isolated Anvil world per implementation
and moves bytes. It doesn't compare them. Returndata comes from
`debug_traceTransaction`, cross-checked against `eth_call` at the parent block.

License: MIT. Reuse and AI assistance are described in [NOTICE.md](NOTICE.md).
References: [plan](docs/reference/FE_COMPATIBILITY_PLAN.md) and
[agent reference](docs/reference/FE_AGENT_REFERENCE.md).

## Independent Git history

This directory is its own repository on `main`, and no remote has been added.

```sh
git remote add origin <this-project-repository-url>
git push -u origin main
```
