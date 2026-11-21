# Phase 0 feasibility — full observation path (21 November 2026)

**Result: Phase 0 exit gate passed. Decision: go.** Fe makes the comparison
decision and detects a one-byte difference in real EVM output. Phases 1–5 are
not started.

## Toolchain (all pinned and checked at run time)

| Tool | Pin | How it is checked |
| --- | --- | --- |
| Fe | 26.5.0, commit `3dab95f8eebdccf9a2382bb59a33f7bbd03540ca`, `fe_mac_arm64` sha256 `4968711c…a523fed` | `scripts/bootstrap-fe.py` checks the download. The host refuses any other digest or version. |
| Solidity | 0.8.31+commit.fd3a2265, macOS sha256 `f5a243d6…346ade9` (the Linux assets are also pinned) | `scripts/bootstrap-solc.py` checks the download. The host refuses any other digest. |
| Foundry | Anvil/Cast 1.5.1-stable, commit `b0a9dd9ceda36f63e2326ce530c10e6916f4b8a2` | Each chain start refuses another commit. |
| Python | 3.14.6 used; the standard library only | — |

Host: macOS 26.4.1 arm64. Linux is untested.

Settings:

- Solidity: `--evm-version osaka --optimize --optimize-runs 200`.
- Fe contracts: `--backend sonatina --profile release -O 1`.
- Checker: `--backend native -O 1`.
- EVM: Anvil `--hardfork osaka`, chain 31337, genesis timestamp 1700000000,
  base fee 0, gas 2,000,000 per transaction, gas price 1.

## What was built

| Piece | Path | Language |
| --- | --- | --- |
| Frozen fixture spec (written first) | `spec/meter-v0.md` | — |
| Solidity reference, written from the spec | `contracts/solidity/Meter.sol` | Solidity |
| Fe port, plus a `try_call` exact-bytes test | `contracts/fe/meter/` | Fe |
| Seeded variant (`TooLarge` reports limit 101), generated at build time | `.tools/build/sources/meter-faulty` (ignored) | Fe |
| Typed raw observations and well-formedness checks | `src/observation.fe` | Fe |
| Strict comparison, mismatch classes, first divergence, streaming steps | `src/conformance.fe` | Fe |
| Checker unit tests (EVM and native backends) | `src/tests.fe` | Fe |
| Native checker transport (protocol 1) | `host/checker-native/` | Fe |
| Build with digests and a stale-build stamp | `scripts/build.py`, `host/common.py` | Python |
| Chain driver and observation capture | `host/observe.py`, `host/evm_chain.py` | Python |
| Gate | `scripts/verify-phase0.py` | Python |

**Division of work.** Python runs the chains and moves bytes. It never decides
equality. Fe makes every decision: whether each observation is well formed,
whether two observations match, which mismatch class applies, the byte offset
or topic index, and which step diverged first. The Fe side is about 510 lines
(observation, conformance, transport); the observation driver is 185 lines of
Python.

## How the raw observations are obtained

- **Equal worlds.** Each implementation gets its own fresh Anvil node. The
  same account 0 deploys at nonce 0, so both contracts sit at the same address
  (`0x5fbd…0aa3`). There's no address normalization in Phase 0. Every call is
  one mined transaction from the same sender, with scheduled timestamps
  (1700000002 onward). The host checks each mined timestamp.
- **Returndata.** Transaction receipts don't contain returndata. The host reads
  it from `debug_traceTransaction` (`returnValue`, with `failed` checked
  against receipt status), for successes and reverts alike. It then gets the
  same bytes a second, independent way: `eth_call` of the same calldata at
  the parent block, or the error `data` on revert. If the two paths disagree,
  that's an infrastructure error.
- **Logs.** From the receipt, in order: emitter, topics, raw data.
- **Gas.** Recorded per step but never compared.
- **In-EVM path.** The pinned `try_call` returns a `CallOutcome` with
  `success()` and `returndata()` and doesn't bubble the revert.
  `contracts/fe/meter/src/tests.fe` checks the exact
  `encode_error(TooLarge{200,100})` and `EmptyQuantity` bytes, and that state
  rolled back. The same test fails on the seeded port with an assertion panic
  (`Panic(0x01)`).

**Transport to Fe.** The frame is whitespace-separated decimals (≤ 65,536
characters, ≤ 78 digits per number). Each payload is sent as its byte length
plus big-endian 32-byte words with zero padding, so leading zeros and empty
payloads survive. Payloads are capped at 256 bytes, logs at 4 per call, topics
at 4, and sequences at 64 steps. Anything larger, non-zero padding, logs on a
reverted call, or an invalid frame is an error, never a truncated equality.

## Exact verification

```sh
python3 scripts/bootstrap-fe.py && python3 scripts/bootstrap-solc.py
source scripts/env.sh
python3 scripts/verify-phase0.py --record     # 3.8 s
```

The gate ran, and passed, the following:

- `fe check .`
- `fe test .` (6 passed) and `fe test . --backend native` (6 passed)
- `fe test contracts/fe/meter` (1 passed)
- `scripts/build.py`
- `fe test` on the seeded port: fails, as required, with `Panic(0x01)`
- `host/observe.py` three times:
  - **Solidity vs Fe:** match on all 5 steps.
  - **Fe vs Solidity:** match.
  - **Solidity vs seeded Fe:** mismatch. Fe reports step 2 (`add(200)`),
    category `returndata-byte`, offset 67, `0x64` vs `0x65`.

| Perturbation of the real Solidity record (each sent through the native Fe checker) | Fe classification |
| --- | --- |
| last returndata byte / error selector byte / error argument byte / `total()` value | `returndata-byte` at offsets 31 / 0 / 35 / 31 |
| lost leading zero; empty returndata; extra trailing zero in revert data | `returndata-length` |
| success instead of revert | `status` |
| missing event; extra event | `log-count` |
| different emitter | `log-emitter` |
| indexed caller moved to data | `topic-count` |
| event-signature topic byte; indexed-caller byte | `topic` at index 0 / 1 |
| event data byte | `log-data-byte` at offset 63 |

Each record also matches itself. The following are infrastructure errors,
never verdicts:

- 300-byte returndata
- a log on a reverted call
- five logs
- differing step counts
- a modified checker binary (stale-build refusal)

Bytecode sha256 (creation / runtime), byte-identical when rebuilt:

| Target | Creation | Runtime |
| --- | --- | --- |
| Solidity | `c8ad5b8a…843aaf` | `db17cda9…21199c` |
| Fe | `c71e325b…c909ee` | `3d51abc7…cf4f61` |
| Fe seeded | `737a0401…18dee0` | `66516c59…751c63` |

Gas per step, reported only and not compared: Solidity 45625 / 21480 / 21531 /
28525 / 23342, Fe 45190 / 21480 / 21510 / 28090 / 23274. This is one tiny
fixture and supports no gas claim.

Raw records and the full transcript are in [evidence/phase0/](evidence/phase0/):
`raw-solidity.json`, `raw-fe.json`, `raw-fe-faulty.json`, `gate.json`.

## Limitations and what Phase 0 does not establish

- The meter is a five-call observation-path fixture, not a compatibility claim
  about any realistic contract. ABI vectors, the treasury corpus, public-state
  comparison, ETH deltas, and layout mode are Phases 1–4.
- Only strict raw-byte mode exists. There is no decoded explanatory view yet;
  the report shows both raw returndata.
- Both worlds deploy at the same address, so the actor/address-mapping and
  normalization allowlist (Phase 1) aren't exercised.
- Observations are capped at 8 words, 4 logs, and 64 steps. These are fixed Fe
  array sizes.
- Returndata comes from Anvil's trace API, cross-checked by `eth_call`. Another
  node implementation would need its own proof.
- Verified on macOS arm64 only.
- All runs are the implementing agent's own. There has been no outside user
  yet; that's Phase 5.

## Go / no-go

**Go.** The dangerous part, reliable raw returndata and events from both
compilers with the decision made in Fe, works. It's fast (3.8 s for the whole
gate) and has explicit infrastructure separation. The fallback (a generated Fe
test harness) isn't needed: the native stdin transport works. Next is Phase 1:
freeze the treasury interface specification, the observation schema and
normalization allowlist, and independent ABI golden vectors.

## Contest note

The agent reference records that registration closed on 17 November 2026 and
that each project must be registered separately. If this project wasn't
registered by then, it may not be eligible for submission, whatever its
technical state.
