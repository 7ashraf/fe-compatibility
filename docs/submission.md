# Submission summary

- **Project:** fe-compatibility, a Fe conformance kit for Solidity→Fe ports.
- **Exact Fe version:** `fe 26.5.0 (3dab95f)`, source commit
  `3dab95f8eebdccf9a2382bb59a33f7bbd03540ca`. See the [Fe manifest](../fe.toml)
  and [toolchain pins](../toolchain.json).
- **Verified on:** macOS arm64. Linux is untested.
- **License:** MIT. Provenance and AI assistance are in [NOTICE.md](../NOTICE.md).
- **Frozen implementation:** recorded in [the Phase 5 evidence](evidence/phase5.json)
  (`summary.commit`). Use `git rev-parse HEAD` in the project checkout for the
  full commit SHA after publishing the candidate.

## One-sentence pitch

Fe Compatibility helps teams validate Solidity-to-Fe ports by pinpointing the
first observable mismatch in a reproducible EVM scenario.

## Fe-specific technical highlight

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

## Reproducible demo

Use Python 3.10+, Git, curl, and Anvil/Cast 1.5.1-stable (commit
`b0a9dd9ceda36f63e2326ce530c10e6916f4b8a2`). Run these commands in Bash
or Zsh from the project root.

```sh
python3 scripts/bootstrap-fe.py
python3 scripts/bootstrap-solc.py
source scripts/env.sh
python3 scripts/build.py
python3 scripts/demo.py
python3 scripts/verify-phase5.py
```

The demo checks agreement on 85 treasury actions, pinpoints an inclusive-expiry
mistake, and locates a shifted storage field that getter comparisons miss.

## Pre-existing work, reuse, and AI assistance

The treasury port, policy, and v0 specification are vendored from Fe Capabilities
at `ba6893c5e847b9f1e2c7479ef00f2489972a2691` (MIT). The project also uses
adapted local Anvil tooling, supplied plans and examples, and compiler-bundled
Fe libraries. Claude Opus 5.5 implemented and verified Phases 0–5. OpenAI
Codex assisted with contest documentation and release verification. The demo
uses deliberately seeded porting mistakes. See [NOTICE.md](../NOTICE.md).

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
