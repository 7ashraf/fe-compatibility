# Fe Compatibility — phased implementation plan

**Status:** proposed project, not an implemented product.  
**Baseline:** Fe 26.5.0; research prepared 7 November; plan finalized 8 November 2026.  
**Read with:** [Fe agent reference](FE_AGENT_REFERENCE.md).

## 1. The project in simple terms

You have a Solidity contract and a Fe version. This project runs the same actions against both and shows exactly where their public behavior differs: return data, errors, events, state, or a deliberately specified storage layout.

The goal is to make a bounded Fe port easier to review. It is **not** an automatic Solidity-to-Fe translator, a mathematical equivalence proof, or a certificate that an arbitrary proxy upgrade is safe.

The intended first user is an experienced Solidity developer evaluating Fe. Your own Solidity experience is valuable here: choose a familiar behavior, write a precise specification, and demonstrate subtle mismatches that a successful deployment or matching happy-path getter would miss.

## 2. The contribution that must be in Fe

Build a reusable **Fe conformance kit**: typed observations, expected outcomes, comparison/classification logic, and a bounded explicit-layout validator with golden fixtures. Use a host runner to deploy implementations, execute actions, collect outputs, and present reports.

Existing ABI codecs and `SolSlot`/`SolMapping` are building blocks. Do not relabel those standard-library features as new inventions. The original contribution is the repeatable conformance workflow, Fe checking logic, well-chosen failure corpus, and clear separation of what each check establishes.

**Value hypothesis:** a developer can introduce or detect a porting mistake and get a precise, reproducible explanation without learning the entire Fe compiler. Test that with one outside user and a second small contract family.

**Stop rule:** if nearly all useful logic lives in a JavaScript comparison script and the only Fe is the target contract, strengthen the reusable Fe conformance layer or merge the work into another entry. A token Fe wrapper is not enough.

## 3. Claims, modes, and scope

Every report must identify its mode:

| Mode | What is compared | What passing does not establish |
|---|---|---|
| ABI conformance | Selectors, declared types, encoding/decoding vectors | Correct business logic |
| Behavioral conformance | Outcomes under the tested action sequences | Equivalence for every possible execution |
| Explicit layout conformance | Approved slots/offsets/keys in a named layout schema | Compatibility of arbitrary compiler layouts or upgrades |

MVP: one shared ETH treasury scenario family, one small independent ABI fixture, and one isolated packed-storage fixture. Support finite sequences and explicit observation types. Initially bound cases to 64 actions and clearly cap payload/log sizes; oversized observations become errors, never silently truncated equality.

Exclude universal source parsing, arbitrary storage discovery, source translation, cross-chain behavior, compiler optimization, and production proxy migration. A local proxy demonstration is stretch work only after the basic claims are fully supported.

## 4. Architecture

| Proposed area | Responsibility |
|---|---|
| `src/observation.fe` | Typed call status, bytes, logs, state fields, comparison mode |
| `src/conformance.fe` | Fe comparison and mismatch classification |
| `src/layout_schema.fe` | Supported widths/offsets, root reservations, overlap/range validation |
| `src/layout_access.fe` | Small reviewed adapter around existing Solidity-layout APIs |
| `fixtures/abi/` | Golden vectors plus malformed/truncated inputs |
| `fixtures/behavior/` | Treasury sequences and expected observations |
| `fixtures/layout/` | Slot words, approved keys, mutation sequences |
| `contracts/solidity/` | Independently written reference implementations |
| `contracts/fe/` | Fe implementations and deliberately faulty variants |
| `host/` | Build/deploy/RPC, observation transport, report rendering |

Make the checker useful without the UI. The host supplies raw observations and the declared schema; Fe decides equality and classifies mismatches. If Fe-native file I/O is too costly, generate bounded Fe fixture inputs and run its checker through a compiled harness. Record that limitation and the real execution cost.

Do not call an EVM capability from a native checker. Keep bytes/comparison/schema logic pure where possible and storage access in the EVM adapter.

## 5. Freeze the comparison contract

Record both compiler versions, optimization settings, EVM target, source and bytecode hashes, dependency versions, ABI, and schema hash. Run each implementation in an isolated but equivalent environment with the same actor roles, chain ID, time, initial balances, gas allowance, and action order.

Prefer equal deployment addresses in separate worlds when practical. Otherwise use an explicit actor/address mapping. Only normalize fields the schema identifies as addresses. Never globally replace matching byte patterns in returndata, topics, or storage; that can hide a real mismatch. Preserve raw and normalized observations together.

### Observation rules

| Observation | Comparison rule |
|---|---|
| Success/failure | Must match; distinguish execution failure from harness failure |
| Successful returndata | Exact bytes in strict mode; decoded view is explanatory |
| Revert data | Exact selector and payload under the agreed error contract |
| Events | Ordered list, emitter identity, topics, and data within declared scope |
| Public state | Named getters/model fields after each action |
| ETH movement | Recipient/treasury deltas under specified semantics; sender gas accounted separately |
| Raw storage | Only named layout schema and declared sampled slots/keys |
| Gas | Report separately; unequal gas does not by itself mean behavioral incompatibility |

Use the non-bubbling call APIs to capture failure; the pinned source provides `try_call` and `try_call_raw`. Verify their signatures with a small test. Host-side transaction receipts alone may not contain returndata; prove how the selected harness obtains it before building the report UI.

Define error precedence. If a request is both unauthorized and expired, both implementations must use the same specified validation order for strict error comparison. Otherwise label the divergence as intentionally outside that claim, not silently compatible.

## 6. Exact MVP fixtures

### A. Treasury behavior

Use the shared v0 specification from the reference: immutable owner, lifetime grants, fixed recipient, positive spend, exclusive expiry, revocation, and atomic payment/accounting. Freeze repeated revocation as **successful no-op for a known inactive grant**, with no second revocation event; unknown grant revocation reverts. Make that choice identical in both versions.

Write the Solidity reference from the behavior specification, not by line-by-line translation of the Fe implementation. Reusing the same incorrect algorithm in two languages is a weak oracle. Keep a small independent transition model and explicit expected examples.

### B. ABI fixture

Use a small contract with static integer/address inputs, one ABI struct/tuple, one bounded dynamic payload, a custom error, and one event with an indexed field. Add integer boundaries, empty values, malformed offsets/lengths, and truncated calldata. Inspect actual emitted ABI before selecting unsupported shapes.

Canonical valid ABI is the primary compatibility claim. If two compilers differ on malformed input acceptance, record the exact difference and decide whether the specification requires rejection; do not automatically call every decoder difference a compiler vulnerability.

### C. Explicit layout fixture

Use a separate storage-only example with a reviewed layout: slot 0 packs an address at byte offset 0, a bool at offset 20, and an 11-byte unsigned value at offset 21; slot 1 is the root of a single address-to-uint256 mapping. Offsets are from the low end of the word.

The Fe adapter must use a storage domain with no overlapping compiler-allocated fields. Verify this invariant explicitly; do not mix raw slot writes with aliases to automatic contract state. Test every field update preserves its neighbors and several independent keys remain distinct.

Nested mapping support is optional. If added, use the actual nested Solidity derivation; a tuple-key map is not automatically equivalent. Dynamic arrays/strings and arbitrary namespace discovery remain outside the first layout claim.

## 7. Phases and gates

### Phase 0 — prove the full observation path

**Timebox:** two focused work sessions in the initial portfolio spike window.

Tasks: pin Fe, Solidity, and Foundry; verify local Osaka support; compile/deploy a small pair; call one success and one custom-error path; capture exact bytes and one event; feed the observations into a Fe checker.

Deliverables: `docs/feasibility.md`, toolchain manifest, two raw execution records, first Fe mismatch result.

**Exit:** the comparison decision genuinely runs in Fe, and a one-byte difference is detected. **Fallback:** generated Fe test harness for observations. **Stop:** no reliable raw observation path, or the central checker remains outside Fe after the timebox.

### Phase 1 — specification, schemas, and golden vectors

Tasks: freeze external signatures, payable flags, validation order, event fields, and return types; define observation schema and normalization allowlist; create independent ABI vectors; validate observation limits and schema versions.

Deliverables: interface specification, schema, golden vectors, fixture provenance.

**Exit tests:** matching vectors pass; wrong selector/type/length fails with a specific category; address normalization changes only approved fields; a deployment error cannot look like an expected application revert; values above JavaScript's safe-integer range round-trip exactly.

### Phase 2 — reusable Fe conformance engine

Tasks: implement byte comparison, log sequence comparison, typed state comparisons, mismatch categories, first-divergence reporting, and strict versus explanatory views. Keep raw data available. Add deterministic ordering and output limits.

Deliverables: Fe library API, pure unit tests, a machine-readable report format.

**Exit tests:** detect missing/reordered/extra logs, changed indexed values, wrong custom-error payload, success versus revert, mismatched state after a superficially matching return, and oversized payloads. A negative test must fail because of its intended difference.

### Phase 3 — differential treasury execution

Tasks: implement both contract versions from the frozen spec; execute matching sequences in isolated worlds; collect observations after every action; add negative and boundary cases; introduce explicit faulty variants for harness validation.

Deliverables: passing corpus, mismatch corpus, per-step reports, exact reproduction commands.

**Exit tests:** cap boundary, expiry equality, unauthorized access, revocation, insufficient funds, recipient revert, and reentry cases agree on the specified result. Seeded mistakes—such as inclusive expiry or missing event indexing—are detected at the earliest relevant observation. A correct pair passes the same corpus.

### Phase 4 — bounded layout adapter and validator

Tasks: implement the isolated packed fixture using existing raw-layout APIs; validate allowed widths/offsets and overlaps; compare selected slot words and mapping entries; document the unsafe invariant at each raw access.

Deliverables: layout schema, adapter, known slot vectors, neighbor-preservation tests, scope statement.

**Exit tests:** individual writes preserve unrelated bits; boundary-width values round-trip; distinct keys remain independent; an intentionally shifted offset is detected; overlapping or out-of-range field descriptions are rejected. A passing result says exactly which slots and keys were tested.

### Phase 5 — second integration, user test, and release

Tasks: run a second small fixture family using the same engine; have another developer introduce a porting mistake; measure time to reproduce and locate it; complete clean-checkout verification; prepare demo and submission materials.

Deliverables: real feedback notes, reproducibility record, limitations, final commit, provenance/AI declaration.

**Exit:** another person can run the pair, see a deliberate mismatch, apply the correction, and obtain a passing report without editing the checker. If no external tester is available, state that limitation instead of inventing validation.

## 8. Test and mutation matrix

| Area | Mutations the tool must detect | Positive control |
|---|---|---|
| ABI | Wrong selector, parameter width, tuple field order | Golden valid vector |
| Errors | Wrong selector, missing argument, wrong validation precedence | Same exact expected error |
| Events | Missing log, reordered logs, changed indexed flag | Matching topics/data/order |
| State | Incorrect spent amount despite correct return | Same post-action state |
| Environment | Different timestamp or actor mapping | Equivalent isolated worlds |
| Layout | Offset shift, neighbor overwrite, wrong mapping root | Approved layout vectors |
| Transport | Truncated bytes or lost leading zeros | Exact round-trip of raw bytes |
| Harness | Crash, timeout, unsupported fork | Clearly separated infrastructure result |

Avoid using the same encoder/decoder for every oracle. Include independently obtained vectors and raw byte comparisons to catch shared mistakes. A suite with many random happy-path calls is weaker than one proving it catches these targeted failures.

## 9. Measurements and honest claims

Report: supported ABI shapes; action and observation coverage; known mutations detected/missed; false positives on correct fixtures; first divergence found; clean-checkout reproduction success; end-to-end runtime and environment. Publish raw outputs.

Gas measurements must include compiler versions, optimizer settings, fork, and identical workload. Do not claim “Fe is cheaper than Solidity” from one fixture. Describe the measured function and configuration only.

A passing report should read: “No mismatch observed for corpus X under configuration Y; layout mode covers schema Z and keys K.” It must never say “these contracts are equivalent” or “safe to upgrade” without a separate, much stronger basis.

## 10. Risks and fallbacks

| Risk | Response |
|---|---|
| Native file transport costs too much | Generated bounded fixtures and compiled Fe checker |
| Dynamic ABI support expands scope | Freeze one supported dynamic shape; enumerate exclusions |
| Raw storage is unsafe or difficult | Keep it isolated; ship behavior mode first; clearly mark layout mode incomplete if necessary |
| Shared oracle reproduces same mistake | Independent expected vectors and seeded mutations |
| Address normalization hides bugs | Schema allowlist, raw record retention, dedicated normalization tests |
| Framework differences obscure reverts | Prove non-bubbling raw-call observation in phase 0 |
| Compatibility engine duplicates a generic diff | Center Fe types, semantic observations, layout guards, and actual porting fixtures |

## 11. Demo and submission story

Show a Solidity and Fe pair that both deploy. Run a basic happy path, then a boundary sequence that exposes a specific mismatch. Display the exact step, property, raw bytes, and decoded explanation. Fix the Fe port, rerun, and show the passing corpus. Finish with a packed-field write that preserves neighbors and a deliberately incorrect offset that fails.

Keep the interface spare: CLI output and a clear report are enough. A dashboard is optional. The central story is confidence with explicit limits, backed by executable evidence.

README order: supported claim, quick start, example mismatch, Fe core, architecture, comparison/normalization rules, fixture coverage, layout scope, limitations, measurements, provenance. Explain existing stdlib functionality separately from your original work.

## 12. Portfolio execution and reuse

Use 8–9 November for this project's observation-path spike alongside the other projects. Target the Compatibility MVP for 13–15 November after the shared treasury specification stabilizes. Reserve 20–21 November for adversarial testing and 22–24 November for frozen reproduction and submission preparation. The common calendar and deadlines are in the reference and Replay plan.

The shared treasury is a demonstration dependency, not this submission's entire novelty. Pin or vendor it with attribution, include a second standalone fixture, and ensure this repository runs without sibling checkouts. Disclose any copied Fe/Solidity code and do not count the same contract implementation as three different original contributions.

## 13. First implementation brief

```text
Implement phase 0 only, then assess feasibility.
Pin Fe 26.5.0 and exact supporting compiler/tool versions.
Deploy a tiny Solidity/Fe pair on a compatible local EVM.
Capture one success, one custom error, and one event as raw observations.
Build a Fe checker that detects an intentional one-byte difference.
Document how returndata is obtained and how environments are made equal.
Do not implement a source translator, universal layout scanner, or UI.
Finish with reproducible commands and an honest go/no-go assessment.
```

Primary references: [Fe storage](https://fe-lang.org/contracts/storage/), [Fe selectors](https://fe-lang.org/messages/selectors/), [Fe event ABI](https://fe-lang.org/events/abi/), [pinned call APIs](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/effects.fe), [Solidity ABI](https://docs.soliditylang.org/en/latest/abi-spec.html), [Solidity storage layout](https://docs.soliditylang.org/en/latest/internals/layout_in_storage.html), [Fe integration testing](https://fe-lang.org/testing/integration/), and [contest rules](https://fe-lang.org/contest/).
