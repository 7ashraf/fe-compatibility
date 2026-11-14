# Fe Capabilities — phased implementation plan

**Status:** proposed project, not an implemented product.  
**Baseline:** Fe 26.5.0; research prepared 7 November; plan finalized 8 November 2026.  
**Read with:** [Fe agent reference](FE_AGENT_REFERENCE.md).

## 1. The project in simple terms

Build reusable Fe components for giving an account a tightly limited spending permission: **this delegate may pay this recipient, up to this total amount, before this time, until the owner revokes it**.

Demonstrate the components in an ETH treasury. A company could give an automation bot or employee a spending allowance without handing over unrestricted treasury control. The hackathon prototype uses local test funds.

The distinctive contribution is a reusable Fe library whose code dependencies are explicit, paired with actual runtime authorization and adversarial tests. A treasury UI alone would not demonstrate why Fe matters.

## 2. Two different kinds of permission

Keep these separate in the API, documentation, and demo:

| Permission | Enforced by | Example | Limitation |
|---|---|---|---|
| Code access | Fe effects/access rules and API boundaries | A budget calculation receives no payment capability | The trusted caller/provider and unsafe code remain part of the system |
| User authorization | Runtime checks using actual EVM context and stored grant state | Only the stored delegate can spend an active grant | The programmer must implement and test every rule |

An effect declaration does not prove that `msg.sender` is authorized. A capability-shaped data object is not automatically unforgeable, non-replayable, or tied to current state. Do not market this as an unhackable treasury or a sandbox for arbitrary hostile plugins.

The useful claim is narrower: important dependencies are visible, components are reusable, and the demonstrated runtime policy is covered by focused tests.

## 3. Scope

| MVP | Stretch only | Excluded from the contest baseline |
|---|---|---|
| ETH-only treasury | Simple UI after core acceptance | ERC-20 allowance edge cases |
| Immutable owner | Additional policy composition example | Upgradeability/proxies |
| Fixed recipient per grant | One more independently implemented consumer | Signatures/session keys/ERC-4337 |
| Lifetime budget, exclusive expiry, revocation | Comparative gas report | Daily resets, rolling windows, price feeds |
| Actual payment and atomic rollback | Carefully reviewed token adapter | Cross-chain permissions |
| Narrow Fe policy/effect interfaces | Developer-facing API documentation site | General dynamic plugin execution |
| Compile-fail and runtime negative tests | Formal methods exploration | Claims of an audit or universal safety |

Start with no frontend. The essential demonstration is a real payment, rejected policy violations, and a reusable component with a visibly narrow interface.

## 4. Concrete behavioral specification

This section defines our proposed v0 behavior; it is not an existing Fe API. Use the same specification in the other two projects.

### State and roles

- `owner`: immutable nonzero address chosen at deployment.
- `next_grant_id`: monotonically increasing positive ID; never reuse revoked IDs.
- Each grant: `delegate`, fixed `recipient`, `cap_wei`, `spent_wei`, `expires_at`, and `active`.
- An explicit existence distinction is required. An all-zero mapping entry is not a valid grant.
- Grants allocate permission, not reserved ETH. Several grants can exceed the treasury's current balance in aggregate.

### Proposed operations

| Operation | Contract behavior |
|---|---|
| Deposit | Explicit payable entry point; any sender; zero value allowed as a no-op; no success event for zero value. |
| Grant | Owner only; nonzero delegate/recipient; positive cap; expiry strictly after current time; create fresh ID. |
| Revoke | Owner only; unknown ID reverts; known active grant becomes inactive and emits once; known inactive grant is a successful no-op. |
| Spend | Known grant; caller is its delegate; active; positive amount; current time strictly before expiry; within remaining cap and available ETH. |
| Observe | Read grant/existence and treasury balance without changing state. |

Only deposit accepts transaction value. Reject accidental ETH sent to other entry points according to the reviewed ABI. Explicitly decide and test empty-calldata behavior; the default v0 interface should not rely on an undocumented fallback.

Recipients are fixed at grant creation. `Spend` accepts the grant ID and amount, not a freely chosen replacement recipient. Owner/delegate may be contracts. Do not assume they cannot participate in callbacks.

### Error and event contract

Before implementation, freeze canonical ABI signatures and error payloads in `spec/treasury-v0.md`. Suggested error categories: unauthorized, unknown grant, inactive grant, invalid amount, expired, cap exceeded, insufficient balance, payment failed, and reentrancy. Use typed custom errors rather than incidental assertion text for public policy failures.

Freeze a consistent validation order: payable/dispatch restrictions; reentrancy guard for protected mutations; operation-level authority; existence and active state; amount; expiry; remaining budget; available ETH; payment. For spend, delegate authority requires loading a known grant first. Document that operation-specific exception explicitly.

Events record grant creation, the first successful revocation, a successful positive deposit, and successful spend. Specify all fields and indexing once. Emit spend success only within an operation that commits successfully. Revert tests must confirm no committed success event remains.

### Invariants

1. A successful spend was initiated by the grant's delegate under a currently valid grant.
2. `0 <= spent <= cap`; validate `amount <= cap - spent` before adding.
3. Each payment goes to the stored recipient and consumes the same amount of budget.
4. Expiry is exclusive: `now == expires_at` rejects spending.
5. Revocation blocks subsequent spends; a new grant never revives an old ID.
6. Failed payment rolls back spent accounting and related logs.
7. Reentry cannot bypass accounting or mutate another sensitive policy entry point.
8. A later legitimate call in the same transaction works after the guard unlocks.
9. One grant's writes do not alter another grant's permissions or accounting.
10. ETH balance assumptions account for unsolicited/forced transfers; do not assert that explicit deposits are the only possible source of ETH.

## 5. Architecture and effect boundaries

| Proposed area | Responsibility | Intended dependencies |
|---|---|---|
| `src/types.fe` | Grant IDs, policy/state, decisions, typed errors | Ordinary domain types |
| `src/policy.fe` | Validate caller, expiry, amount, remaining cap | Read-only grant and application context |
| `src/budget.fe` | Checked budget transition | Narrow mutable budget/state access |
| `src/grants.fe` | Grant creation, lookup, revocation | Grant store plus authorized owner boundary |
| `src/treasury.fe` | Bind actual context, lock, validate, update, pay, emit | EVM capabilities only at the boundary |
| `tests/compile_fail/` | Forbidden safe access examples | Separate consumer fixtures |
| `tests/runtime/` | Payments, callbacks, policy attacks | Actual EVM execution |
| `examples/sponsorship/` | Second small consumer of policy components | Same public library, no copy of its logic |

Separate pure policy from storage and payment. An application-owned context value can hold caller and timestamp for unit tests; production construction must derive them from actual `Ctx`. Built-in `Ctx`, `Call`, and `Log` traits are sealed, so do not write fake implementations of those traits.

Prefer a decision value describing a valid transition to mutating state and returning `Err`. Remember that `Err` does not roll back writes. The trusted treasury boundary must load current state, validate, apply, and pay within the same protected invocation. Do not expose a reusable “authorized spend token” that callers can forge or replay against changed state.

If generic effects become difficult, use a small concrete application-owned effect first. Generalize only after a second consumer needs it. A narrow, well-tested library is stronger than a generic framework with unverified assumptions.

## 6. Reentrancy and payment design

Inspect the existing [`Mutex<T>`](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/mutex.fe) and its fixtures. It already provides transient locking and protected-value access. The new contribution should be correct composition with the grant policy, not an unnecessary new mutex.

Choose the lock domain explicitly. Grant, revoke, and spend mutate sensitive state and must share a coherent callback policy. For a straightforward v0, guard every state-changing treasury entry point, including deposit, while allowing observation of consistent documented state.

Read the needed values, validate, update budget, end any live mutable projections that cannot cross an external call, then attempt payment. Use the supported non-bubbling call/send path to distinguish payment failure and raise the agreed error. On success, complete the event/unlock sequence. On revert, EVM rollback must restore the lock/accounting state.

Do not assume `Mutex::peek` hides intermediate state. Decide what getters expose during callbacks and verify the observable behavior. If the read-only view includes the already-reserved spend, document it as part of checks/effects/interactions.

Explicitly unlock after success. A transient lock lasts for the transaction, so a forgotten unlock can break a second legitimate spend in a batch even if separate transactions appear fine.

## 7. Phases and acceptance gates

### Phase 0 — prove access boundaries and actual payment

**Timebox:** two focused sessions during 8–9 November.

Tasks: pin toolchain; compile the reference examples; build one minimal policy function with an application-owned effect; prove an allowed caller compiles and a forbidden access does not; deploy a tiny contract and make a real local ETH payment; test recipient rejection.

Deliverables: `docs/feasibility.md`, exact commands, one positive/negative compilation pair, one EVM payment test.

**Exit:** there is a real compile-time boundary and a real EVM payment path. **Fallback:** concrete effects rather than complex generic composition. **Stop:** the intended claim cannot be expressed honestly without broad raw access everywhere.

### Phase 1 — freeze semantics and implement pure policy

Tasks: finalize the v0 spec, validation precedence, events, and ABI; implement budget/expiry/delegate checks; define existence and inactive state; use strong types at unit boundaries; add explicit context construction for tests.

Deliverables: spec, policy module, independently written expected vectors, API notes.

**Exit tests:** zero and maximal amounts; exact cap; one above cap; expiry before/equal/after now; wrong caller; inactive and missing grant; no mutation after rejected policy result. Every branch has a meaningful expected result, not just “did not crash.”

### Phase 2 — storage and administration

Tasks: add persistent grant store; immutable owner initialization; monotonic IDs; create/revoke/observe handlers; isolate storage access from pure policy; verify emitted ABI and events.

Deliverables: deployable administration contract, storage tests, schema/interface fixtures.

**Exit tests:** unauthorized grant/revoke fail for the right reason; invalid owner/delegate/recipient rejected; IDs never reused; one grant does not corrupt another; absent map values cannot authorize a spend; repeated revoke follows the no-op rule. Compiler-checked effect narrowing remains visible in the library API.

### Phase 3 — protected spending and real ETH

Tasks: integrate payment and existing mutex; define callback behavior for every mutation; handle insufficient funds and recipient failure; preserve exact error/event contract; complete deposit behavior and payable tests.

Deliverables: functional treasury, hostile recipient fixtures, atomicity tests.

**Exit tests:** successful spend transfers the expected ETH and increments spent once; rejecting recipient leaves accounting unchanged; same-function and cross-function callbacks fail safely; a contract owner cannot use a callback to bypass protected administration; two sequential valid spends in one transaction both work; later transaction works after a failed attempt.

### Phase 4 — prove reusable boundaries

Tasks: package policy/budget components as an ingot; write a second small sponsorship consumer without copying the core; add compile-fail fixtures as an external consumer; document the trusted boundary and public API.

Deliverables: reusable package, second consumer, compile-fail runner, capability/dependency table.

**Exit tests:** policy-only code cannot access payment or mutate an omitted store through the safe API; read-only grant code cannot write through its provided access; authorized positive controls compile; each negative failure is due to the intended missing capability/access. Both consumers pass their runtime tests using the same library revision.

### Phase 5 — adversarial review and evidence

Tasks: review the invariants against every entry point; introduce seeded defects to validate tests; integrate optional Compatibility/Replay artifacts after the core stands alone; have an outside developer run the package and explain the boundaries back.

Deliverables: test matrix, threat/assumption notes, defect-detection results, reproducible demo, honest limitations.

**Exit:** cap-check removal, expiry-boundary change, missing caller check, and forgotten unlock are each detected by an appropriate test. Record any untested combinations. No claim of a professional audit.

### Phase 6 — freeze and handoff

Tasks: clean-checkout build/test; pin all dependencies; document unsafe use if any; make the README and demo understandable in minutes; record license, reuse, and AI assistance; prepare final commit.

**Exit:** a reviewer can install, test, create a grant, make an allowed payment, and reproduce at least three rejected attacks using documented commands.

## 8. Compile-fail testing without false confidence

A test that fails to compile for a syntax error proves nothing about capability boundaries. Each negative fixture needs a corresponding positive fixture differing only in the relevant access/provider. Require a diagnostic category or stable substring indicating the intended failure; avoid full diagnostic snapshots that break on harmless formatting changes.

Run negative fixtures separately from the ordinary passing test suite. Have the runner treat an unexpected successful compile as failure. Keep fixtures as external consumers when testing privacy/public API boundaries; code inside the implementation module may have additional rights.

Never claim that removing an effect prevents a malicious trusted host from supplying a broader implementation elsewhere. The demonstrated property is about the submitted safe code and explicit dependencies.

## 9. Runtime test matrix

| Family | Required cases |
|---|---|
| Identity | Owner/delegate/recipient distinct; wrong caller; contract caller; never use transaction origin for authority |
| Grant lifecycle | Unknown ID, active, revoked, repeat revoke, fresh grant after revoke |
| Budget | Zero, exact remaining, one over, multiple spends, arithmetic boundary |
| Time | Before, exactly at, after expiry; grant with nonfuture expiry |
| Funding | Empty treasury, later deposit, failed payment, unsolicited balance increase |
| Isolation | Two grants and multiple delegates cannot overwrite each other |
| Callbacks | Same-function spend, cross-function revoke/grant/deposit, getter observation |
| Transaction lifetime | Two legitimate same-transaction calls; revert then later success |
| ABI/errors/events | Correct custom-error payload; correct indexing; no committed log on failure |
| Reuse | Second consumer imports unchanged library; no sibling checkout required |

Use the actual context at runtime. Unit mocks of caller/time make policy testing convenient but do not prove that the contract boundary binds trustworthy values.

## 10. Risks and fallbacks

| Risk | Response |
|---|---|
| Generics/effects consume schedule | Concrete effect providers first; generalize after second consumer |
| API overstates authority guarantees | Document trusted code and runtime checks; avoid bearer authorization objects |
| Existing stdlib already supplies the primitive | Reuse it and make policy composition/testing the original contribution |
| Mutex access conflicts around calls | Shorten projections; copy permitted values; use pinned source fixtures |
| Too many payment/token variants | Keep ETH and fixed recipients only |
| UI crowds out security tests | CLI demo first; UI last or omit |
| Companion projects lag | All core tests remain in this repository |

## 11. Measurements, demo, and judge-facing evidence

Measure concrete outcomes: supported policy rules; positive/negative compile cases; seeded defects caught; real payment/rollback cases; integration steps for the second consumer; runtime/bytecode/gas only with a pinned, disclosed environment. Test count alone is not proof of safety.

Demo sequence: owner grants a small allowance; delegate pays the fixed recipient; overspend fails; an unapproved account fails; owner revokes; the old grant fails; a malicious recipient's callback fails; a legitimate second call still succeeds. Then show one short policy function whose signature exposes its limited dependencies, plus a compile-fail example.

Explain the engineering gain in plain terms: a reviewer can see what a component can access, while tests prove the actual permission rules. Do not claim judges will prefer it based on personal profiling. Align evidence with the published technical and Fe-specific criteria.

README order: problem, quick start, supported policy, Fe-specific design, trust boundaries, API, tests, demo, limitations, provenance. Include a simple table separating code access from user authority; this distinction is central to the project.

## 12. Portfolio schedule and shared work

Use 8–9 November for shared spec/toolchain and this project's feasibility spike. Target a working Capabilities MVP on 10–12 November. Support the other projects through a frozen treasury specification and pinned fixture, then return to adversarial hardening on 20–21 November. Freeze features on 22 November and use the remaining time for reproducibility, documentation, and submission preparation.

This project owns the reusable policy/composition library. Compatibility owns its conformance engine; Replay owns its reducer. Cite the common treasury implementation wherever reused and avoid presenting the same code as a new core contribution in each entry. All three repositories should run independently.

If the schedule slips, remove UI and stretch policies first. Do not cut rollback, authorization, or reentrancy validation to preserve a three-project count.

## 13. First implementation brief

```text
Implement phase 0 and the pure policy slice from phase 1.
Use Fe 26.5.0, the agent reference, and the proposed treasury v0 spec.
Start with a grant containing delegate, recipient, cap, spent, expiry, active.
Use an application-owned context for unit tests and real Ctx at the EVM edge.
Prove one allowed/forbidden effect-access pair and one actual ETH payment.
Inspect std::evm::mutex before implementing any custom guard.
Do not add tokens, signatures, upgradeability, or a frontend.
Finish with exact test results, API assumptions, and the next gate.
```

Primary references: [effect declaration](https://fe-lang.org/effects/declaring-effects/), [propagation](https://fe-lang.org/effects/propagation/), [mocking limits](https://fe-lang.org/testing/mocking/), [access rules](https://github.com/argotorg/fe/blob/v26.5.0/docs/language/accesses.md), [EVM capabilities and calls](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/effects.fe), [mutex](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/mutex.fe), [units](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/units.fe), [revert semantics](https://fe-lang.org/errors/revert/), and [contest rules](https://fe-lang.org/contest/).
