# Submission summary

- **Project:** fe-compatibility, a Fe conformance kit for Solidity→Fe ports.
- **Toolchain:** Fe 26.5.0 `3dab95f`, Solidity 0.8.31, Foundry 1.5.1-stable
  `b0a9dd9c`, Python 3.10+ (standard library only).
- **Verified on:** macOS arm64. Linux is untested.
- **License:** MIT. Provenance and AI assistance are in [NOTICE.md](../NOTICE.md).
- **Frozen commit:** recorded in [evidence/phase5.json](evidence/phase5.json)
  (`summary.commit`).

## What it is

The same actions run against a Solidity contract and its Fe port. The checker
captures the raw EVM observations: status, exact returndata and revert bytes,
ordered logs, typed public state, and raw storage slots. A checker written in
Fe decides whether they match and classifies the first divergence. A
machine-readable report shows the raw bytes and a typed explanation.

It has three modes:

- **ABI conformance:** golden vectors from an independent encoder, and an ABI
  validator.
- **Behavioral conformance:** the treasury v0 corpus, 85 actions with outcomes
  written from the spec.
- **Explicit layout conformance:** a packed slot and a mapping, checked with
  neighbor preservation, field values, entry slots, and declared write sets.

## Try it (about 5 minutes after setup)

```sh
python3 scripts/bootstrap-fe.py && python3 scripts/bootstrap-solc.py
source scripts/env.sh && python3 scripts/build.py
python3 scripts/demo.py
python3 scripts/port-exercise.py start   # then edit exercise/ and run: check
```

## Claims and limits

- **Claimed:** no mismatch observed for each corpus under its configuration.
  Every seeded mistake is located at its earliest relevant observation:
  - 6 Meter ports;
  - 6 treasury ports (including inclusive expiry, a missing event index, and
    unpersisted accounting that only typed state reveals);
  - 3 layout adapters (a shifted offset and a wrong mapping root that are
    invisible to getters).
- **Not claimed:**
  - equivalence or upgrade safety;
  - arbitrary contracts or storage layouts;
  - an independent oracle (the Solidity treasury reference was written by the
    same agent that had read the Fe implementation);
  - gas or performance advantages.
- **Findings about Fe 26.5.0:**
  - only raised custom errors appear in the emitted ABI;
  - `RawStorage` getters are emitted as `nonpayable`, not `view`;
  - std has no 88-bit `SolPacked` type.
- **Pending:** an outside user's run of
  [the tester guide](tester-guide.md) ([feedback record](reviewer-feedback.md)).
