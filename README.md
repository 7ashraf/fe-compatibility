# fe-compatibility

Run the same actions against a Solidity contract and its Fe port, capture the
raw EVM observations (status, exact returndata or revert bytes, and ordered
logs), and let a **Fe checker** decide whether they match. When they don't, it
reports the first divergence.

**Status: Phase 0 exit gate passed** ([feasibility](docs/feasibility.md)).
Phases 1–5 (schemas and ABI vectors, the full Fe engine, the treasury corpus,
layout mode, and an outside user) are not started. Passing means "no mismatch
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
```

The seeded `fe-faulty` port reports `TooLarge(200, 101)` instead of
`TooLarge(200, 100)`. Fe reports step 2 `add(200)`, `returndata-byte`, offset
67, `100` vs `101`, along with both raw payloads.

## Where the Fe is

- `src/observation.fe`: typed raw observations. Payloads are an explicit byte
  length plus 32-byte words, and the module enforces well-formedness rules
  (zero padding, caps, no logs on reverts).
- `src/conformance.fe`: strict comparison in a fixed order (status, returndata,
  log count, emitter, topics, data). It assigns one of nine mismatch
  categories, the byte or topic index, and the first divergent step.
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
