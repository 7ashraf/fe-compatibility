# Fe Replay — phased implementation plan

**Status:** proposed project, not an implemented product.  
**Baseline:** Fe 26.5.0; research prepared 7 November; plan finalized 8 November 2026.  
**Read with:** [Fe agent reference](FE_AGENT_REFERENCE.md).

## 1. The project in simple terms

A contract fails after a long sequence of actions. Fe Replay saves exactly what happened, removes unnecessary steps, simplifies the remaining inputs, and gives the developer a small regression case that still exposes the same bug.

The strongest version is a **Fe library for typed, stateful scenario reduction**, with a thin adapter for executing those scenarios. The reducer, action model, and failure-matching logic belong in Fe. A dashboard and a new generic fuzzing engine are not the MVP.

The intended first user is a Fe developer who already has a failing integration sequence but cannot easily understand it. The key deliverable is a reproducible explanation of a failure, not a large count of generated transactions.

## 2. Value hypothesis and competitive edge

Foundry already offers invariant testing, saved corpora, replay, and minimization. Read its [invariant guide](https://www.getfoundry.sh/guides/invariant-testing) and [corpus workflow](https://www.getfoundry.sh/guides/fuzz-corpus) before making a novelty claim.

Our hypothesis is narrower: Fe developers benefit from a typed scenario model whose reducer understands domain actions, preserves the identity of a failure, and can run against a pure model or an EVM adapter without rewriting the reduction algorithm. Explicit effects make dependencies such as the evaluator and generation source visible.

Evidence needed: one developer can take a saved case, reduce it, understand it, and keep it as a regression without modifying reducer internals. Demonstrate that on two different state machines. Do not claim to outperform Foundry unless a controlled comparison supports the exact metric.

**Early stop rule:** if the result is merely a host script wrapping Foundry's existing shrinking, or Fe only contains the example target, it is not a strong standalone submission. Narrow the problem to a useful Fe reduction library or make it a supporting feature of another entry.

## 3. Scope and boundaries

| Required MVP | Stretch only after acceptance | Excluded |
|---|---|---|
| Typed action sequence and versioned saved case | Rich semantic action-repair plugins | Universal Solidity/Fe fuzzer |
| Deterministic replay from clean state | Coverage-guided generation | Whole-EVM debugger |
| Chunk deletion, single-step deletion, bounded input simplification | Multiple reduction strategies | LLM-generated arbitrary contracts |
| Same-failure preservation | Interactive viewer | Formal proof of minimality |
| Native Fe reducer or proven Fe execution fallback | Multiple EVM clients | Distributed fuzzing infrastructure |
| Pure toy ledger plus treasury EVM demonstration | Automatic source-test generation | Mainnet execution or real funds |
| Machine-readable artifact and readable summary | Corpus management UI | Another PRNG implementation |

Initial engineering bounds: at most 64 actions per case and explicit candidate/evaluation limits. These are adjustable configuration choices, not language limits. Reject oversized input clearly rather than silently truncating it.

## 4. Architecture and ownership

Proposed repository areas:

| Area | Responsibility | Language |
|---|---|---|
| `src/actions.fe` | Action enum, stable IDs, validity and simplification rules | Fe |
| `src/reducer.fe` | Candidate generation, ordering, budget, accepted-case state | Fe |
| `src/failure.fe` | Failure fingerprints and verdict comparison | Fe |
| `src/sequence.fe` | Bounded sequence operations and progress ordering | Fe |
| `examples/ledger/` | Small independent model and seeded fault | Fe |
| `examples/treasury/` | Adapter to the shared treasury specification | Fe plus EVM harness |
| `host/` | File parsing, process/RPC transport, artifact formatting | Small TypeScript or Python layer |
| `fixtures/` | Passing cases, seeded failures, expected reductions | Versioned data |

Prefer a reducer state machine that emits a candidate, accepts an evaluator result, and decides the next step. The host may execute a candidate; it must not secretly own candidate selection or failure identity.

Use application-owned traits/effects for reset, execute, and observe. Standard EVM capability traits are sealed; do not invent arbitrary `Ctx`/`Call` mocks. The pure adapter owns ordinary in-memory data. The EVM adapter drives real compiled contract code.

The first architecture spike must prove the transport between the Fe reducer and evaluator. If runtime native I/O is expensive, the documented fallback is a generated Fe harness consuming fixture constants. Batch candidate evaluation can remain practical for a bounded demonstration. State the performance limitation openly.

## 5. Saved-case and oracle contract

The format is our proposed interface, not a built-in Fe API. Include:

- Schema version, case ID, target/source commit, compiler/backend/optimization, fork, bytecode hash, and generator version.
- Initial balances, actors as stable roles, deployment settings, time, and relevant environment values.
- Actual typed actions with stable logical IDs; seed is supplementary information.
- Expected failure fingerprint, evaluation budget, original case hash, and provenance.
- For reduced output: retained actions, attempted/accepted candidates, stop reason, execution count, and before/after size.

Use decimal strings for all potentially large numeric quantities and hex for bytes. Validate the entire case before execution. Reject unknown action kinds, schema versions, invalid lengths, and unresolved actor references.

An evaluator returns one of four categories:

| Verdict | Meaning | Reducer action |
|---|---|---|
| Pass | Scenario executed and property held | Reject candidate |
| Same failure | Execution violated the target property with the expected identity | Accept if strictly simpler |
| Invalid scenario | Removed prerequisite or impossible model setup | Reject; record why |
| Infrastructure error | Crash, timeout, tool mismatch, deployment failure | Stop or bounded retry under explicit policy |

Different failures are reported but never accepted as the target bug. A fingerprint includes property ID, failure class, observation category, and stable trigger ID where necessary. Avoid absolute addresses, numeric action indices, and incidental error text. Do not include the amount being simplified unless it is essential to identifying the bug.

Each candidate starts from an identical clean environment. Reset account balances, code/storage, time, deployment nonces/salts, and any host model. A previous candidate's state must never leak into the next.

For actions that create grants, use logical handles mapped to actual IDs during evaluation. Deleting a creator makes dependent actions invalid unless an explicit domain simplifier repairs them. Never silently reinterpret an old ID as another grant.

## 6. Reduction algorithm

This is design pseudocode, not executable Fe:

```text
verify original case reproduces target failure
best := original
while budget remains:
    propose deletion or argument simplification from best
    require candidate is strictly smaller under a declared ordering
    evaluate candidate from fresh initial state
    if same target failure:
        best := candidate
        restart relevant simplification passes
    otherwise retain best and record verdict
stop when passes reach a fixed point or a budget is exhausted
replay best independently before exporting
```

Use a lexicographic simplicity measure: action count first, then an explicit finite argument complexity measure. Start with chunk deletion, then single-action deletion, then bounded domain reductions such as amount toward zero/one/a relevant cap boundary and time toward an expiry boundary. Preserve monotonic environment constraints.

A reduction is not guaranteed globally shortest. Claim only “reduced” by default. Claim deletion-1-minimal only after exhaustively testing every remaining single-action deletion against the final case without a budget stop. Include the precise guarantee in output.

## 7. Phases and acceptance gates

### Phase 0 — prove usefulness and the dangerous integration path

**Timebox:** first two focused work sessions, during the portfolio's initial spike window.

Tasks: pin Fe; reproduce the reference tests; inspect native interfaces; compile a five-action reducer prototype; send one candidate through a real evaluator; obtain two successful identical replays. Check existing Foundry behavior on the same simple fault. Draft the one-sentence distinction from existing tools.

Deliverables: `docs/feasibility.md`, working spike, exact commands, a sample observation record, and a short baseline comparison.

**Exit:** the candidate-selection code is Fe, evaluator results can return to it, and one saved failure reproduces from clean state. **Fallback:** generated fixture harness. **Stop:** no reliable Fe evaluation loop after the timebox, or no distinct user benefit.

### Phase 1 — schema and a reliable replay engine

Tasks: implement bounded actions and parsing validation; define reset and observation contracts; build the pure ledger; add deliberate overspend fault behind an explicit demo target; save a complete case. Implement stable grant/action handles before reduction.

Deliverables: schema document, ledger adapter, golden cases, replay command contract. Any suggested command name in the README must correspond to a real implemented script.

**Exit tests:** same case run 20 times gives identical observations; changing an amount or initial state changes the expected result; malformed input and incompatible schema fail clearly; injected process failure becomes infrastructure error; a non-buggy ledger passes.

### Phase 2 — Fe reducer with failure preservation

Tasks: implement chunk and single deletion; define deterministic candidate order; add evaluation budget; preserve fingerprints; keep best accepted state; add argument simplification. Avoid PRNG dependence in the reducer itself unless essential.

Deliverables: reusable reducer API, deterministic candidate transcript, reduced fixture, unit tests for sequence boundaries and verdict handling.

**Exit tests:** irrelevant steps disappear; the triggering property remains identical; a candidate causing another assertion is rejected; deleting a prerequisite is invalid; exhausted budget returns the best valid case; termination holds for empty, singleton, and maximum-size cases. Re-evaluate the exported output independently.

### Phase 3 — real treasury EVM adapter

Tasks: integrate the shared ETH treasury v0 spec from the agent reference; record real outcomes and relevant state; use exact error observations; add owner/delegate/recipient actions and time advancement. Add a separately identified seeded fault, such as bypassed cap validation or incorrect expiry equality.

Deliverables: EVM replay adapter, adversarial recipient fixture, original and reduced cases, actual generated bytecode hashes.

**Exit tests:** correct treasury passes; seeded faulty treasury fails; reduced case preserves the same property; reset isolates candidates; reverting recipient leaves budget unchanged; a failing deployment cannot count as a discovered policy bug. Establish whether each scenario represents separate transactions or multiple calls inside one transaction—transient state makes the distinction material.

### Phase 4 — generality and honest measurements

Tasks: integrate the second independent example without changing core reduction logic; measure original/reduced lengths, candidate count, wall time, and repeatability. Compare a pinned Foundry workflow where the same workload can be expressed fairly.

Deliverables: benchmark script, raw runs, environment manifest, adapter effort notes, limitations.

**Exit:** the core works on both examples; at least one person unfamiliar with the implementation reproduces the saved failure; all comparative claims link to raw measurements. This is a target to achieve, not an existing endorsement.

### Phase 5 — freeze and submission package

Tasks: clean-checkout test; license/provenance review; document exact supported bounds; remove dead UI work; prepare a short recorded or scripted demo; pin the final commit. Use the common submission checklist in the reference.

**Exit:** a reviewer can reproduce the original failure, reduce it, replay the reduction, and verify that the corrected target passes from documented commands.

## 8. Mandatory regression matrix

| Test family | Required evidence |
|---|---|
| Determinism | Repeated action stream and observation equality |
| Reset isolation | A deliberately dirty evaluator does not contaminate later runs |
| Failure identity | Wrong-property failure never accepted |
| Model independence | Oracle not copied from the faulty implementation |
| Stateful prerequisites | Removed grant/deposit handled explicitly |
| Reduction correctness | Exported case independently reproduces |
| Boundedness | Candidate, length, timeout, and numeric limits enforced |
| Environment | Fixed fork/time/actors/compiler; incompatible config rejected |
| Seeded defects | Each advertised defect detected, corrected version passes |
| Host failures | Crash and timeout never become contract violations |

Do not evaluate tool quality only by “number of tests.” Use known faults, false-positive controls, and independent replay.

## 9. Risks and decisions

| Risk | Early signal | Response |
|---|---|---|
| Native transport dominates effort | Candidate loop not working in phase 0 | Generated Fe harness; retain Fe reducer |
| Scope duplicates Foundry | Pitch only mentions fuzz/shrink/replay | Emphasize typed domain reduction with actual integration evidence, or stop standalone entry |
| Shrinking changes bug | Smaller case hits a different revert | Strong fingerprint and separate infrastructure category |
| Backend mismatch | Pure model works but EVM semantics differ | EVM-confirm every exported contract failure |
| Recompilation is slow | Harness generation dominates timings | Batch evaluations, lower bounds, publish cost |
| Shared treasury delayed | No contract fixture ready | Finish ledger plus small independent counter/queue target first |

## 10. Demo and evidence story

A three-minute demo should: show a long saved action sequence; reproduce the failure; identify its property ID; run reduction; display the much smaller sequence and explanation; replay it; switch to the corrected target and show it passes. State clearly that demonstration bugs were intentionally inserted unless a real independent bug was actually discovered.

README order: problem, one command to reproduce, Fe contribution, architecture, case format, algorithm/guarantees, tests/measurements, limitations, provenance. Include one annotated reducer function and explain why its effect boundary lets it reuse the evaluator interface.

Evidence maps to the rubric through reproducibility and correct reduction, meaningful Fe algorithms, demonstrated workflow improvement, a second adapter, and a short understandable demo. Do not infer judges' votes from their public interests.

## 11. Portfolio schedule and reuse

Treat the three plans as one workload, not three independent full-time schedules. Suggested shared calendar:

| Dates, November 2026 | Focus |
|---|---|
| 8–9 | Shared toolchain/spec and a feasibility spike for every project; prioritize Replay's transport risk |
| 10–12 | Capabilities MVP; keep Replay spike reproducible |
| 13–15 | Compatibility MVP |
| 16–19 | Replay MVP; register all intended distinct entries before the official deadline |
| 20–21 | Adversarial tests, second-user feedback, evidence |
| 22–24 | Feature freeze, clean reproduction, documentation, demos, submission buffer |

If a core phase slips, remove stretch work before compressing verification. One strong finished entry has more value than three claims with missing evidence. Shared treasury/spec artifacts must be pinned and credited; the reducer must run without sibling repository checkouts.

## 12. First implementation brief

```text
Build only phase 0 and the smallest vertical replay slice.
Use Fe 26.5.0 and the reference's verified syntax.
Start with five typed ledger actions, one intentionally faulty target,
one stable property ID, and a clean-state evaluator.
Prove the Fe reducer can propose one deletion and consume its verdict.
Record the exact host boundary and fallback cost.
Do not build a frontend or general fuzzer.
Finish with a reproducible command and the phase-0 go/no-go assessment.
```

Sources to inspect before implementation: [Fe testing runner](https://fe-lang.org/testing/runner/), [native library](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/native.fe), [random primitives](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/random.fe), [effects](https://fe-lang.org/effects/declaring-effects/), and the Foundry references in section 2. Recheck [contest rules](https://fe-lang.org/contest/) at submission time.
