# Feasibility and phase gates

| Phase | Status |
| --- | --- |
| 0: Observation path | Passed, 21 November 2026 ([below](#phase-0-feasibility--full-observation-path-21-november-2026)) |
| 1: Specification, schemas, and golden vectors | Passed, 21 November 2026 ([below](#phase-1--specification-schemas-and-golden-vectors-21-november-2026)) |
| 2: Reusable Fe conformance engine | Passed, 21 November 2026 ([below](#phase-2--reusable-fe-conformance-engine-21-november-2026)) |
| 3: Differential treasury execution | Passed, 21 November 2026 ([below](#phase-3--differential-treasury-execution-21-november-2026)) |
| 4: Bounded layout adapter and validator | Passed, 21 November 2026 ([below](#phase-4--bounded-layout-adapter-and-validator-21-november-2026)) |
| 5: Second integration, user test, release | Release checks passed, 21 November 2026; **outside-user exercise pending** ([below](#phase-5--second-integration-user-test-and-release-21-november-2026)) |

# Phase 0 feasibility — full observation path (21 November 2026)

**Result: Phase 0 exit gate passed. Decision: go.** Fe makes the comparison
decision and detects a one-byte difference in real EVM output.

> In Phase 1, the checker moved to native protocol 2 and the raw record to
> version 2. `scripts/verify-phase0.py` still passes, unchanged in its
> expectations. The Phase 0 evidence files are historical (protocol 1, record v1).

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


# Phase 1 — specification, schemas, and golden vectors (21 November 2026)

**Result: Phase 1 exit gate passed** (`scripts/verify-phase1.py`, about 10 s,
including the Phase 0 regression). It uses the same pinned toolchain as Phase 0.

## Deliverables

| Deliverable | Path |
| --- | --- |
| Interface index | `spec/interface.md` |
| Treasury v0, revision 1, vendored unchanged from Fe Capabilities `ba6893c` (SHA-256 pinned) | `spec/vendor/treasury-v0/` |
| Codec v1, a standalone ABI fixture, and its frozen target ABI | `spec/codec-v1.md`, `spec/codec-v1.abi.json` |
| Observation schema, vector format, normalization allowlist, limits | `spec/schema.md` |
| Golden vectors: 15 valid, 13 malformed, 1 deployment, from an independent encoder | `fixtures/abi/codec-v1.json`, generated by `scripts/make-vectors.py` |
| Codec implementations, written from the spec | `contracts/solidity/Codec.sol`, `contracts/fe/codec/` |
| Fe ABI validator | `src/abi.fe` (188 lines) |
| Fe allowlisted normalization | `src/normalize.fe` (125 lines) |
| Deployment-first comparison, `not-comparable` verdict, rejection scope | `src/conformance.fe` |
| Native checker protocol 2 (sequence and ABI requests) | `host/checker-native/` |
| Strict fixture loader and runner | `host/vectors.py`, `host/world.py`, `host/fecheck.py` |

**Fixture provenance.** The golden bytes are produced by `cast` 1.5.1 (the alloy
encoder). It is independent of both solc and Fe, so neither implementation is
its own oracle. Expected values are written from the spec, never obtained by
running a contract. Malformed calldata comes from documented byte edits.
`make-vectors.py --check` regenerates the fixture byte for byte (SHA-256
`51208c64…3e2c99`). Both compiled ABIs equal the frozen ABI canonically,
including state mutability, tuple components, and event indexing.

## Exit tests

1. **Matching vectors pass.** Fe compares both implementations against all 15
   valid vectors (exact returndata and logs) and the 10 `reject` vectors
   (status and logs), and finds a match. Solidity and Fe also match each other
   on all 28. Every successful returndata is canonical under the Fe validator.
2. **Wrong selector, type, or length fails with a specific category.** The Fe
   ABI validator classifies all 13 malformed calldatas exactly as declared:
   - `selector`;
   - `truncated` for empty input, a missing word, and a missing byte;
   - `type` for `uint8` = 256, an unextended `int16`, an address with bit 160
     set, `bool` = 2, and `uint64` = 2^64;
   - `length`, `offset`, `padding`, and `extra`.

   Nine returndata perturbations of real records are also classified:
   - dirty `uint8`, address, and `bool` values → `type`;
   - a missing word → `truncated`;
   - an extra word → `extra`;
   - a bytes length overrun → `length`;
   - a non-canonical offset → `offset`;
   - a wrong error selector → `returndata-byte` at offset 3;
   - a short error payload → `returndata-length`.
3. **Normalization changes only approved fields.**
   - World A: deployer is account 0, caller account 1, target
     `0x5fbd…0aa3`.
   - World B: deployer is account 2, caller account 3, target `0x663f…6602`.
   - Raw comparison of the two worlds is a mismatch at `statics-max`
     (returned address).
   - With the allowlist, all 27 non-control vectors match.
   - The control `echo-address-bytes` returns the target address inside
     `bytes`. That isn't an allowlisted position, so it stays raw and is
     reported as `returndata-byte`.
   - The loader rejects a fixture whose allowlist was extended to a `uint256`
     word.
   - Fe unit tests cover the remaining cases: an address-valued `uint` stays
     raw, a wrong role still mismatches, an unknown address is compared raw,
     and duplicate roles or out-of-range positions are malformed.
4. **A deployment error can't look like an expected application revert.**
   With a zero owner, both constructors revert with `0x49e27cff`
   (`InvalidOwner()`, equal to the golden bytes).
   - The Solidity-vs-Fe result is `not-comparable`.
   - The same failed deployment, paired with a step that expects exactly those
     revert bytes, is still `not-comparable`.
   - The runtime code is never compared, because it differs by compiler.
5. **Values above JavaScript's safe-integer range round-trip exactly.** These
   five vectors match golden bytes in Fe on both implementations:
   - 2^256−1 and 2^255−1;
   - −2^255;
   - ±(2^53+1);
   - 2^64−1.

   All 10 decoded values equal the decimal-string inputs. A JSON number, even
   one above 2^53, a float, or a leading-zero decimal is rejected at load time.

**Strict loader (exit 2, never a verdict).** The gate checks that each of 20
invalid fixtures is rejected:

- schema version 2, or `true`;
- an unknown or a missing field;
- JSON numbers or floats;
- a non-canonical decimal;
- uppercase hex;
- calldata over 256 bytes;
- more than 64 vectors;
- a duplicate ID;
- five topics;
- a tampered allowlist;
- a signature outside the frozen ABI;
- a wrong interface hash;
- a duplicate JSON key;
- NaN;
- non-list or non-object structures;
- a missing file.

The gate caught one real bug here: a missing fixture used to exit 1, which
looks like a conformance failure. Every load failure now exits 2.

## Observed behavior on malformed calldata (recorded, not a claim)

| Vectors | Solidity 0.8.31 | Fe 26.5.0 (Sonatina) |
| --- | --- | --- |
| 10 `reject`: unknown selector, empty, truncated, dirty widths, length overrun | revert, empty data | revert, empty data |
| 3 `unspecified`: offset 64, nonzero padding, trailing word | accepted | accepted |

The two compilers agree on every malformed vector in this corpus. Both decode
leniently in the same three non-canonical cases. The Fe validator labels those
calldatas non-canonical, and the spec leaves them unspecified. Nothing here is
called a vulnerability.

Bytecode SHA-256 (creation / runtime):

- Solidity Codec: `7746a619…` / `51b993de…`
- Fe Codec: `96789bc1…` / `f42b5698…`

The full values are in `docs/evidence/phase1/gate.json`. Gas, which is never
compared, totals 348,439 for Solidity and 347,740 for Fe over the 15 valid
calls.

Evidence is in [evidence/phase1/](evidence/phase1/):

- `report.json`
- `gate.json`, with the commands, malformed behavior, perturbations,
  round-trips, and loader rejections
- six raw execution records: Solidity and Fe in world A, Fe in world B, and
  both zero-owner deployments

## Limitations

- The ABI validator supports static `uint`/`int` of 8–256 bits, `address`,
  `bool`, flattened static tuples, and at most one dynamic `bytes`. Arrays,
  strings, nested dynamic types, and multiple dynamic arguments are out of
  scope.
- Return-value normalization covers word-aligned static heads only. Addresses
  inside revert payloads aren't normalized; no frozen error has one.
- The event list each function may emit (`EMITS`) is transcribed from the spec
  by hand in the loader. It isn't derived from source.
- Treasury v0 is frozen and vendored, but no treasury implementation is
  exercised yet. That's Phase 3.
- Verified on macOS arm64 only, and all runs are the implementing agent's own.

## Next gate

Phase 2: the reusable Fe conformance engine. That means typed state comparisons,
a decoded explanatory view next to the strict one, deterministic output limits,
a machine-readable report format, and negative tests for reordered or extra
logs and mismatched state behind a superficially matching return.


# Phase 2 — reusable Fe conformance engine (21 November 2026)

**Result: Phase 2 exit gate passed** (`scripts/verify-phase2.py`, about 26 s,
including the Phase 1 and Phase 0 gates). It uses the same pinned toolchain.

## What the engine now does (all in Fe)

- **Typed public state.** Observations carry up to 8 declared state fields
  (`uint`, `int`, `address`, `bool`, `word`), read through getters after every
  call. They are compared after status, returndata, and logs (`state-count`,
  `state-kind`, `state-value`). Address-typed state is normalized by its
  declared type.
- **Semantic categories (17).** For reverts, a different error
  (`error-selector`) is reported before a different argument
  (`error-argument`, with the argument index and both full words). Log
  sequences are classified as `log-missing` (one deletion), `log-extra` (one
  insertion), or `log-reordered` (same multiset), before falling back to
  `log-count` or the first differing field. Byte categories report the
  containing word as well as the offset.
- **Deterministic order and output limits.** Within a step the order is fixed:
  status, returndata, logs, state. Across steps, the first divergence sets the
  verdict. Every mismatching step's first divergence is listed in step order,
  up to 8 entries, and `mismatching_steps` counts them all.
- **Malformed reasons.** Malformed observations now carry a reason. These are
  `oversized`, `padding`, `logs-on-revert`, `too-many-logs`,
  `too-many-topics`, `emitter`, `stray-data`, `too-many-state`, and
  `state-value`.
  Native protocol 3 reads over-limit payloads and counts up to the frame bound,
  so Fe reports them as `oversized` or `too-many-*`. It doesn't reject them at
  the transport. A malformed observation is never a behavior verdict.
- **Report (`spec/report.md`, `host/report.py`).** It is a machine-readable
  `fe-compatibility-report` v1, with no timestamps and byte-identical across
  runs. Each listed mismatch carries Fe's category, location, and values. It
  also has a **strict** view (the exact raw bytes involved) and an
  **explanatory** view (ABI names and typed values). For example:
  `TooLarge(uint256,uint256): argument 1 `limit` (uint256) differs: 100 vs 101`,
  or `state `total` (total()) differs after the action: 105 vs 106`. ABI
  declaration differences are reported in `abi_declarations`.

## Exit tests

**Pure Fe tests.** Ten Phase 2 tests in `src/phase2_tests.fe` (24 Fe tests in
total) pass on the EVM and native backends. Each negative case starts from a
matching positive control and changes exactly one thing.

**Real EVM corpus.** The Solidity Meter was compared with the correct Fe port
and with six seeded Fe ports, each with one porting mistake applied at build
time (`host/common.py` `VARIANTS`). Every listed mismatch had to be the
intended one, and nothing else could appear:

| Seeded mistake | Fe reports |
| --- | --- |
| None (correct port) | `match` over 5 steps |
| `TooLarge` reports limit 101 | step 2 `error-argument`, argument 1 at byte 67, 100 vs 101 |
| Stores one extra unit at the limit; return and event correct | step 3 `state-value` `total` 105 vs 106, then step 4 `returndata-byte` (`total()`) |
| `caller` not indexed | steps 0 and 3 `topic-count` 2 vs 1 |
| Event emitted twice | steps 0 and 3 `log-extra` at position 1 |
| Wrong error for zero quantity | step 1 `error-selector` `EmptyQuantity()` vs `TooLarge(uint256,uint256)` |
| Zero quantity not rejected | step 1 `status` (revert vs success) |

**A finding.** Fe 26.5.0 emits only the custom errors that are actually raised
into its ABI. The last two ports therefore drop `EmptyQuantity()` from their
ABI, and the report's `abi_declarations` shows it as missing on the right.
Before Phase 2 this aborted the run as an infrastructure error. It is now
reported as a declaration-conformance difference, and the behavioral
comparison still runs.

**Perturbations of real records.** Eleven perturbations went through the
native Fe checker, covering what the Meter can't produce:

- two logs swapped → `log-reordered`;
- first of two logs dropped → `log-missing`;
- an extra log → `log-extra`;
- the indexed caller changed → `topic` at index 1;
- an error argument byte changed → `error-argument` at 67;
- success instead of a revert → `status`;
- a state value after an identical return → `state-value`;
- 300-byte returndata and 257-byte log data → malformed `oversized`;
- five logs → malformed `too-many-logs`;
- 15 mismatching steps → 8 listed in step order, all 15 counted, `truncated`.

**Report checks.** The report validates structurally against `spec/report.md`,
and a rerun produced a byte-identical report.

## Regressions and changed expectations

The Phase 0 and Phase 1 gates still pass. Their expectations were updated only
where Phase 2 deliberately refines a category:

- the Phase 0 seeded fault is now `error-argument` (argument 1, byte 67,
  100 vs 101) instead of `returndata-byte` at 67;
- the "error selector byte" and "wrong error selector" perturbations are now
  `error-selector`;
- the missing and extra events are now `log-missing` and `log-extra` instead
  of `log-count`.

The Phase 0 and Phase 1 evidence files stay as recorded at the time.

Evidence is in [evidence/phase2/](evidence/phase2/): seven reports
(`report-solidity-vs-*.json`) and `gate.json`, which has the commands, every
perturbation decision, and the target identities.

## Limitations

- The explanatory view handles static return heads, error arguments, event
  parameters, and state fields. A difference inside dynamic `bytes` returns is
  explained only as a byte offset.
- State is read through declared getters after each call. Raw storage is
  layout mode (Phase 4).
- The log-sequence classes cover a single deletion, a single insertion, or a
  permutation. Anything else is `log-count` with the first divergent position.
- The seeded corpus is one small contract. The treasury corpus is Phase 3.
- Verified on macOS arm64 only, and all runs are the implementing agent's own.

## Next gate

Phase 3: differential treasury execution. Both treasury versions are built from
the frozen v0 spec and run as matching sequences in isolated worlds, with
negative and boundary cases and seeded faults such as inclusive expiry and a
missing event index.


# Phase 3 — differential treasury execution (21 November 2026)

**Result: Phase 3 exit gate passed** (`scripts/verify-phase3.py`, about 46 s,
including the Phase 0–2 gates). It uses the same pinned toolchain.

## The pair and the corpus

| Piece | Origin |
| --- | --- |
| `contracts/solidity/Treasury.sol` (150 lines) | Written for this project from `spec/vendor/treasury-v0/treasury-v0.md`. It uses a transient `bool` lock, the specified check order, `call{value, gas: 100000}` payment, and an explicit nonpayable `fallback` reverting `UnsupportedCall()`. |
| `contracts/fe/treasury/` | Fe Capabilities treasury and policy at `ba6893c`, vendored unchanged (SHA-256 checked at every build). The Sonatina creation hash `200d381e…` matches the one fe-replay built independently from the same sources. |
| `contracts/solidity/Harness.sol` | Shared fixtures, with identical bytecode in both worlds: `RejectingRecipient`, `ReentrantRecipient` (calls `spend` during payment and logs the outcome), and `Batcher` (a delegate making two spends in one transaction) |
| `fixtures/behavior/treasury-v0.json` | 11 scenarios and 85 actions (`spec/scenarios.md`). Every action has its outcome written from the spec: the exact error and arguments, return values, and exact treasury events. |

Both compiled ABIs equal the frozen ABI canonically, covering all functions,
15 errors, 4 events, the fallback, and mutability. Each scenario gets one fresh
Anvil world per implementation, with the same actors, deployment order and
addresses, block schedule, and funding. After every action the runner records
status, exact returndata, ordered logs, and 12 typed state fields:
`nextGrantId`, the treasury balance, all seven words of grant 1, grant 2's
`spent` and `active`, and the payee's balance.

## Harness changes needed for the treasury

- **Time-exact cross-check.** The `eth_call` replay of each transaction now
  runs on the parent state with the mined block's timestamp and number (an
  Anvil `blockOverrides` check confirmed this works). Without that, results
  such as `Expired(expiresAt, now)` or `InvalidExpiry()` legitimately
  differed from the trace, and the run stopped as an infrastructure error.
- **Balances net of own gas.** When the recipient EOA sends a transaction
  itself, its raw balance includes the gas fee, and the fee differs by
  compiler. Observed balances add back the fees that account paid for its own
  transactions. This follows the plan ("sender gas accounted separately").
- **Fe state limit 8 → 16.** All 24 Fe tests still pass on both backends.

## Exit tests

**The correct pair passes.** Solidity and Fe each meet the spec oracle on all
85 actions: status, exact returndata, and exact events, with the 6
compiler-generated rejections compared by status only. They also match each
other step by step, including all 12 state fields. The run output is
byte-identical across reruns. The scenarios agree on the specified result for:

- the cap boundary: exactly the remaining amount succeeds, one over gives
  `CapExceeded(10, 11)`;
- expiry equality: `Expired(T+4, T+4)` at exactly the expiry second, and
  after it;
- unauthorized access by outsider, owner, and recipient, including that the
  wrong owner wins over an unknown ID for revoke, and that an unknown ID wins
  over authority for spend;
- revocation, repeated revocation (success, no event), and no ID reuse;
- insufficient funds (`InsufficientBalance(5, 10)`);
- a recipient revert (`PaymentFailed()` with state unchanged);
- reentry (the recipient's `spend` callback gets `Reentrant()` and the outer
  spend completes);
- two spends in one transaction;
- the fallback and payability (`UnsupportedCall()` for unknown, short, or
  empty calldata).

**Seeded faults are caught at the earliest relevant observation.** Each fault
is a single mutation of the vendored Fe source, applied at build time and
compared against Solidity. Every other scenario must match exactly.

| Seeded fault | First divergence (scenario, step, category) |
| --- | --- |
| Inclusive expiry (`now > expiresAt`) | `expiry-equality` 4, `status`: the only spend at exactly the expiry second |
| Exact remaining rejected (`amount >= remaining`) | `deposit-spend` 4, `cap-boundary` 3, `revocation` 11, all `status`: every spend of exactly the remaining amount |
| `Spent.delegate` not indexed | `topic-count` at the first successful spend, in all 7 scenarios that have one |
| Active checked before authority | `revocation` 6, `error-selector` (`Unauthorized()` vs `InactiveGrant(uint256)`) |
| Repeated revocation emits again | `revocation` 4, `log-extra` |
| `spent` not persisted | `state-value` `grant1.spent` at the first spend, in 6 scenarios; in `same-transaction`, `log-data-byte` (the second `Spent.newSpent`) |

For the unpersisted-accounting fault, the return value and the event are still
correct at the spend itself. Only the typed-state comparison catches it there.
The spec oracle, which doesn't cover state, notices one to seven actions later
(spend/oracle steps: cap-boundary 3/4, deposit-spend 3/4, expiry-equality 2/3,
insufficient-funds 3/6, reentry 2/3, revocation 2/9).

**Negative controls.**

- Changing one expected error argument (`CapExceeded(9, 11)`) makes the spec
  oracle fail on both correct implementations, with `error-argument` at the
  right step. The differential still matches. So the oracle isn't vacuous.
- A corpus whose schedule is inconsistent is rejected.

Bytecode SHA-256 (creation / runtime):

- Solidity treasury: `2b185fce…` / `7b80dc7b…`
- Fe treasury: `200d381e…` / `6f1466de…`

Evidence is in [evidence/phase3/](evidence/phase3/):

- `correct-pair.json`: every scenario's spec-oracle decisions and its report;
- `seeded-*.json`: first divergences, spec-oracle detections, counts, and
  full reports;
- `gate.json`;
- `raw/`: 22 raw execution records of the correct pair.

## Limitations

- **The oracle isn't fully independent.** The Solidity reference was written
  from the spec, but by the same agent that had read the vendored Fe
  implementation. The spec-derived expectations, which are encoded by `cast`,
  and the seeded faults reduce that risk but don't remove it.
- **No new treasury logic.** The Fe treasury is vendored, so this project
  contributes the conformance workflow, the Solidity reference, the corpus,
  and the seeded faults.
- **Coverage.** The corpus has 85 hand-written actions. It isn't generated or
  exhaustive, and passing means "no mismatch observed for this corpus under
  this configuration".
- **Unreached rules.** `GrantIdExhausted` and `InvalidGrantState` aren't
  reachable through the public interface, so they aren't exercised.
- **Harness logs.** The reentrant recipient's own log is compared exactly. For
  other harness contracts, only the treasury's events are specified.
- Verified on macOS arm64 only, and all runs are the implementing agent's own.

## Next gate

Phase 4: a bounded layout adapter and validator. It uses the isolated packed
storage fixture: an address, a bool, and a `uint88` packed in slot 0, and a
mapping rooted at slot 1. It needs neighbor-preservation tests, a shifted
offset that is detected, and overlapping or out-of-range field descriptions
that are rejected.


# Phase 4 — bounded layout adapter and validator (21 November 2026)

**Result: Phase 4 exit gate passed** (`scripts/verify-phase4.py`, about 59 s,
including the Phase 0–3 gates). It uses the same pinned toolchain.

## What was built

| Piece | Path |
| --- | --- |
| Frozen layout spec and scope statement | `spec/layout-v1.md` |
| Schema plus 19-action corpus with the expected field and entry model | `fixtures/layout/packed-v1.json` |
| Solidity reference, whose own layout rules give the reviewed positions | `contracts/solidity/PackedLayout.sol` |
| Fe adapter (`SolSlot`/`SolWord`/`SolMapping`, `RawStorage` effect, no contract fields) | `contracts/fe/layout/` |
| Fe layout validator (284 lines) and 6 pure tests | `src/layout.fe`, `src/phase4_tests.fe` |
| Native request kind 4 and runner | `host/checker-native/`, `host/layout.py` |

**The pinned raw-layout APIs.** I read them from the std source embedded in
the pinned compiler.

- `SolSlot::at(slot)` and `SolMapping::at(root)` are `unsafe`. Their contract
  is that nothing the compiler allocates may use the slot or the slots derived
  from it.
- `SolSlot::read`/`write` address a `SolPacked` field by its byte offset from
  the low end of the word, preserving the neighbors.
- `SolMapping::slot_of(key)` is `keccak256(abi.encode(key, root))`.
- Raw storage authority is the sealed `RawStorage` effect. `unsafe` only
  asserts the invariant; it grants no authority.
- **Gap found:** the pinned std has no 88-bit `SolPacked` type. The adapter
  implements the public trait for a local `U88` (88-bit mask), and its
  boundary values round-trip in the tests below.

**The unsafe invariant at each raw access.** The adapter declares no contract
fields, so nothing the compiler allocates can alias slot 0, slot 1, or an
entry slot. Each `unsafe` block carries a comment saying so. The runner checks
this at run time: every `SSTORE` that either implementation executes, taken
from the opcode trace, must be slot 0 or a declared entry slot.

## Exit tests

- **The schema is independent of both implementations.** The reviewed schema
  equals `solc --storage-layout` for the Solidity reference: `_owner` slot 0
  offset 0, `_paused` 0/20, `_limit` 0/21 (`t_uint88`), `_balances` slot 1.
- **The correct pair conforms.** Over 19 actions, both the Solidity reference
  and the Fe adapter conform to the schema, as decided by Fe. For each action:
  - only the written field's bits change;
  - all three fields decode to their expected values;
  - all three keys' entries hold their expected values at the slots `cast index`
    derives;
  - the write set is declared.

  The two implementations also match each other step by step on raw slots 0
  and 1, the three entry words, and getter returndata.
- **Individual writes preserve unrelated bits.** Neighbor preservation passes
  on every action of both. Fe unit tests cover a clobbering write (`neighbor`
  at byte 21) and a change with no written field. The seeded clobber below is
  the end-to-end negative.
- **Boundary-width values round-trip.** Slot 0 after action 3 is exactly
  `0xffffffffffffffffffffff01ffffffffffffffffffffffffffffffffffffffff`: the
  maximal address, `true`, and 2^88−1. All 19 known slot-0 vectors hold on
  both implementations, and slot 1 stays zero.
- **Distinct keys stay independent.** The entries for the three keys (the
  caller, the zero address, and the maximal address, with values up to
  2^256−1) are checked after every action. Writing one key never changes
  another.
- **An intentionally shifted offset is detected.** Three seeded Fe adapters
  were tested:

  | Seeded fault | Fe layout result | Getter-only comparison of the same 19 actions |
  | --- | --- | --- |
  | `paused` stored at byte 21, not 20 | `neighbor`, action 1 (`setPaused`), byte 21 | **match**: invisible |
  | Mapping rooted at slot 2, not 1 | `mapping-entry`, action 9: key's entry holds 0, expected 5 | **match**: invisible |
  | `setOwner` clears the slot first | `neighbor`, action 3, byte 20 | mismatch only at action 15 (`limit()`) |

  The first two keep the contract's own getters self-consistent. A behavioral
  comparison can't see them, and only layout mode catches them.
- **Overlapping or out-of-range descriptions are rejected.** Fe rejects 9
  invalid schemas with specific categories, before any action is checked:
  - overlap (limit at offset 20);
  - out of range (limit at 22; paused at 32);
  - width (19-byte address, 33-byte uint, 2-byte bool);
  - a root on the packed slot;
  - a repeated root;
  - nine fields.
- **The scope statement.** Every passing result names its scope: slots
  [0, 1]; the fields and their positions; the three keys with their entry
  slots; and 19 actions.

**A declaration finding.** The ABIs are identical except for state mutability.
Fe 26.5.0 emits the four read-only getters, which read through the
`RawStorage` effect, as `nonpayable`, where Solidity emits them as `view`.
This is recorded, not hidden. It doesn't affect layout or behavior in this
corpus.

Bytecode SHA-256 (creation / runtime):

- Solidity: `e69fea0e…` / `f7929b9f…`
- Fe: `a968543a…` / `eb1c4587…`

Evidence is in [evidence/phase4/](evidence/phase4/): `correct-pair.json`,
`seeded.json` (layout results and getter-only comparisons), `gate.json`
(scope, known vectors, solc storage layout, schema rejections, declaration
finding), and both raw records.

## Limitations

- **One packed slot and one flat mapping.** Nested mappings, arrays,
  `bytes`/`string`, inheritance, and proxies are out of scope.
- **Exact scope.** The result covers exactly the declared slots and three
  keys. It says nothing about other storage, and it makes no upgrade-safety
  claim.
- **The expected model is hand-written.** It's trivial (each setter writes its
  own field), but it's still written in the host.
- **The write-set check traces the target's own frame only.** No nested calls
  happen in this fixture.
- Verified on macOS arm64 only, and all runs are the implementing agent's own.

## Next gate

Phase 5: a second integration, a user test, and the release. That means
another developer introduces a porting mistake and locates it from the
report, plus a clean-checkout verification and submission materials. An
outside user is required. If none is available, that limitation must be
stated, not worked around.


# Phase 5 — second integration, user test, and release (21 November 2026)

**Result: the release checks passed. The exit gate is not met.** The exit
requires *another person* to run the pair, see a deliberate mismatch, apply
the correction, and get a passing report without editing the checker. No
outside tester has done this yet. As the plan requires, that limitation is
stated here rather than worked around. `scripts/verify-phase5.py` reports it
as **pending** until `docs/reviewer-feedback.md` records real feedback.

## Second fixture family on the same engine

The same Fe engine, transport, and report format now serve four independent
fixture families, each with its own frozen spec and seeded negatives:

- Meter v0 (Phase 0, Phase 2 seeded ports);
- Codec v1 (Phase 1 ABI vectors);
- treasury v0 (Phase 3);
- the packed layout (Phase 4).

None of them required changing the checker for another.

## Outside-user exercise (prepared, pending)

- **`docs/tester-guide.md`.** About 20 minutes: setup, the demo, then the
  porting exercise.
- **`scripts/port-exercise.py`.**
  - `start` copies the reviewed Fe treasury port into a git-ignored
    `exercise/`. A helper (or the tester) plants one mistake.
  - `check` builds the edited port and runs the full treasury corpus against
    Solidity. It prints the first divergence per scenario (action, category,
    plain explanation, reference value vs port value) and writes the full
    report.
  - `status` gives the time from start to the first mismatch and from there to
    passing again.

  A port that doesn't compile is reported as a build problem (exit 3), never as
  a conformance verdict.
- **`docs/reviewer-feedback.md`.** The record to fill in, with status
  **pending**.

**The implementing agent's own dry run (not the outside-user test).** I
planted `amount >= context.available` in place of `>`. This isn't one of the
seeded faults. `check` reported 1 of 11 scenarios differing, at
`insufficient-funds-3`:

- category `status` (the reference succeeds; the port reverts with
  `InsufficientBalance(uint256,uint256)`);
- 4 of 7 actions differ in that scenario.

Reverting the line gave `PASS` on all 85 actions. The first mismatch came
3.1 s after `start`, and the passing report 2.6 s later. The person in the
loop was the agent, so those times measure the tool's turnaround, not a human
locating the bug.

## Release checks (`scripts/verify-phase5.py`)

- **Licenses and disclosures.** The MIT `LICENSE`, the retained Fe
  Apache-2.0 license, and the NOTICE disclosures: the vendored inputs and
  their commit, the seeded faults, the Solidity reference not being a fully
  independent oracle, and AI assistance.
- **Provenance and hygiene.** Every vendored file matches its
  `provenance.json` (treasury spec and Fe treasury). Every Solidity file is
  SPDX MIT. No tracked file contains an absolute home path.
- **Fresh clone.** A `git clone` of HEAD, with no `.tools/` or build outputs.
  Inside it, the gate bootstraps the pinned Fe and solc, builds, and runs:
  - `verify-phase4.py`, which runs every gate from Phase 0 to 4;
  - `scripts/demo.py`;
  - the scripted exercise dry run.

  It then confirms that no tracked file changed.
- **`scripts/demo.py`** (about 3 s) checks each claim it prints:
  - the correct treasury pair agrees on 85 actions;
  - inclusive expiry is located at `expiry-equality-4`;
  - the shifted layout offset is invisible to a getter-only comparison, while
    layout mode finds byte 21.

The recorded run is in [evidence/phase5.json](evidence/phase5.json).

## What remains

1. **The outside-user exercise.** A person who didn't build this follows
   `docs/tester-guide.md`, and their real observations go into
   `docs/reviewer-feedback.md`.
2. **Linux.** It is untested.
3. **Publishing.** A remote, a push, and a contest submission all need the
   owner. Whether this project can be submitted also depends on its contest
   registration.
