# Fe coding-agent reference

**Baseline:** Fe 26.5.0 · **Research and verification date:** 7 November 2026 · **Finalized:** 8 November 2026  
**Audience:** an AI coding agent working with an experienced Solidity developer who is learning Fe.  
**Companion plans:** [Fe Replay](FE_REPLAY_PLAN.md), [Fe Compatibility](FE_COMPATIBILITY_PLAN.md), [Fe Capabilities](FE_CAPABILITIES_PLAN.md).

## 1. Read this before writing code

Use this document as the working context for these three projects. It is a curated implementation reference, not a complete copy of every Fe API. Follow the linked, version-pinned source whenever a signature or behavior is not specified here.

The two complete examples in section 20 were compiled and tested using the official Linux binary reporting `fe 26.5.0 (3dab95f)`. Other snippets are explicitly identified as configuration, commands, or proposed design. The three project plans describe work to implement; their projects have not already been built or validated.

### Agent operating rules

1. Read this reference and the relevant project plan before editing. Implement one phase at a time, including its exit criteria.
2. Begin with `fe --version`. Pin the compiler, dependency commits, execution fork, and supporting tool versions. Never silently upgrade to resolve an error.
3. Prefer the pinned compiler's help, source, and passing fixtures when rolling website documentation disagrees with the installed version. Investigate contradictions rather than making up an API.
4. Do not translate Solidity or Rust syntax mechanically. In particular: `var`, `uses`, labeled arguments, `msg`/`recv`, and **`Result<Error, Value>`** are deliberate Fe differences.
5. Before using an unfamiliar API, locate its declaration and a passing test at the pinned tag. Compile a small experiment before incorporating it into the project.
6. Keep the core contribution in Fe. Host scripts may handle files, process execution, RPC, presentation, and orchestration. Do not move the project's central algorithm into TypeScript merely because that is easier.
7. Mark every example or feature as **tested**, **documented but not locally tested**, or **proposed**. Report exact commands and outcomes; never convert an assumption into a completed check.
8. Make unsafe code small and reviewable. Record the invariant that makes every unsafe operation valid. A passing compiler is not a security audit.
9. On compiler failure, first reduce it to a standalone reproduction. Preserve the original error, compiler version, backend, and command. Avoid broad refactors that hide the cause.
10. End each implementation session with working behavior, verification results, remaining limitations, and the next phase gate. Do not claim production readiness, formal equivalence, or guaranteed contest placement.

## 2. Source authority and version pin

The baseline release is [v26.5.0](https://github.com/argotorg/fe/releases/tag/v26.5.0), commit `3dab95f8eebdccf9a2382bb59a33f7bbd03540ca`. Use the [source tree at that commit](https://github.com/argotorg/fe/tree/3dab95f8eebdccf9a2382bb59a33f7bbd03540ca) for a durable reference. Links below using `v26.5.0` identify the same baseline.

Record a small toolchain manifest in every project: Fe version and binary checksum; OS/architecture; backend; optimization and build profile; EVM fork; Solidity and Foundry versions where used; dependency SHAs; fixture-schema version. A release tag alone is not the project's submission SHA.

Website documentation is useful for explanations but can advance ahead of this baseline. Do not assume that an example from an old Python-like Fe release applies to current Fe. The current language uses braces, Rust-like declarations, explicit access modes, effects, and typed messages.

Primary starting points: [documentation](https://fe-lang.org/), [first contract](https://fe-lang.org/getting-started/first-contract/), [compiler fixtures](https://github.com/argotorg/fe/tree/v26.5.0/crates/fe/tests/fixtures), [core library](https://github.com/argotorg/fe/tree/v26.5.0/ingots/core/src), [standard library](https://github.com/argotorg/fe/tree/v26.5.0/ingots/std/src).

## 3. Mental model for a Solidity engineer

Fe can compile contracts for the EVM and suitable programs for a native backend. Ethereum calls, transactions, storage, gas, ABI encoding, and reentrancy still matter. The language provides different ways to express and constrain code; it does not replace the EVM security model.

| Familiar concept | Fe approach | Consequence for these projects |
|---|---|---|
| External Solidity functions | Typed `msg` variants implemented by `recv` handlers | Define external selectors explicitly and verify emitted ABI. |
| State variable access | Contract fields provided through `uses` | A function's state and environment dependencies can be visible in its signature. |
| `msg.sender`, block context | `Ctx` effect | The real EVM boundary must supply caller/time, not untrusted request data. |
| Modifiers/inheritance for shared behavior | Functions, traits, composition, effects | Extract reusable policy and execution components. |
| `uint256` | `u256` | Keep ABI types and internal domain types distinct. |
| `mapping` | `StorageMap` and explicit Solidity-layout helpers | Do not assume tuple keys reproduce nested Solidity mappings. |
| `require`/custom errors | Assertions and typed revert helpers | Error bytes are part of compatibility tests. |
| `memory`/`storage` references | Access modes and effect-provided resources | Learn access lifetime and alias rules instead of importing Rust lifetimes. |
| Forge tests | Fe tests, plus optional Foundry integration | Native model tests do not substitute for real EVM execution. |

**Strengths for our work:** typed action enums, explicit effects, reusable generic algorithms, testable policy logic, and the possibility of running appropriate logic across backends. **Costs:** a younger toolchain and ecosystem, rapidly changing APIs, less accumulated production experience, and integration work that Solidity users normally get from established tooling. Treat performance and security advantages as hypotheses requiring evidence.

Further orientation: [Solidity migration appendix](https://fe-lang.org/appendix/from-solidity/).

## 4. Bootstrap and commands

Obtain the correct binary from the pinned release. The locally tested artifact was `fe_linux_amd64`; choose your actual platform and verify downloaded bytes against any published checksum or a separately recorded trusted digest.

Commands below were checked against the 26.5.0 CLI. Replace project paths with your repository paths; these are not new commands provided by the project plans.

```sh
fe --version
fe new my_project --name my_project
fe check my_project
fe fmt my_project --check
fe test my_project
fe build my_project --emit bytecode,runtime-bytecode,abi,metadata
```

For focused investigation:

```sh
fe test tests/pure_model.fe --backend native
fe test my_project --filter budget --show-logs
fe test my_project --call-trace
fe test my_project --trace-evm --debug-dir debug-output
fe test my_project --report --report-out failure-report.tar.gz
fe build my_project --contract Treasury --out-dir out
fe build pure_tool --backend native
```

Native executable support depends on the platform and program. The release supports native executables on x86-64 Linux and AArch64 macOS. A contract using EVM operations is not automatically a native program. First verify the pure core and the host interface separately.

Useful commands include `check`, `fmt`, `test`, `build`, `bench`, `doc`, and `lsp`. Use each command's `--help` before constructing CI flags. Do not invent `fe run`, `fe install`, or Cargo commands as Fe build steps. `cargo` is relevant only when deliberately building the compiler from Rust source.

## 5. Ingots, modules, and dependencies

An ingot is a Fe package. Start from `fe new`; keep `fe.toml`, `src/lib.fe`, and the generated layout as the known-good foundation. Modules and visibility are explicit; a name being `pub` inside the language does not make it an externally callable Ethereum function.

Minimal manifest:

```toml
[ingot]
name = "my_project"
version = "0.1.0"
```

For git dependencies, use `source`, a **full 40-character commit** in `rev`, and `path` if the ingot is inside a larger repository. A local relative path is useful during development but must work from the submitted clean checkout. This version's dependency model does not provide a lockfile to replace exact revision pins.

Unsafe dependency permissions have their own policy. Do not add `allow_unsafe = true` indiscriminately; inspect the reachable unsafe functionality and explain why it is needed. This setting is not a general sandbox.

References: [project structure](https://fe-lang.org/ingots/project-structure/), [dependencies](https://fe-lang.org/ingots/dependencies/), [workspaces](https://fe-lang.org/ingots/workspaces/).

## 6. Syntax and control flow

Use `let` for an immutable local binding and `var` for a mutable one. Functions use `fn`, braces, and `->` for a return type. Blocks can return their final expression. `if` and `match` can produce values. Match enums exhaustively; do not hide new variants behind a wildcard without a reason.

Arguments normally carry labels: a declaration with `amount: u256` is called with `amount: value`. An underscore in the parameter declaration can make an argument positional. Prefer explicit labels until the compiler confirms the shorthand. Generic function instantiation such as `preserve<bool>(value: true)` is verified in section 20; do not blindly copy Rust's turbofish.

Use fixed arrays for a small, bounded MVP when that avoids unnecessary collection complexity. Write explicit iteration bounds, especially in generators, reducers, decoders, and contract handlers. A host timeout is not a substitute for an algorithmic termination condition.

References: [functions](https://fe-lang.org/foundations/functions/), [operators and expressions](https://fe-lang.org/foundations/operators/), [iteration design](https://github.com/argotorg/fe/blob/v26.5.0/docs/language/iteration.md).

## 7. Types, collections, and numeric boundaries

Use ordinary integer types, `bool`, structs, enums, tuples, and arrays to make invalid combinations harder to construct. `usize` is for indexing; external ABI quantities need deliberately selected Solidity-compatible widths. Do not serialize 256-bit values through JavaScript `number`.

| Need | Starting type/API | Required check |
|---|---|---|
| Small fixed action sequence | `[T; N]` plus length | Capacity and index bounds. |
| Growable working sequence | `MemVec<T>` | Ownership and allocation limits. |
| Solidity dynamic array | ABI `DynArray<T>` | Actual element codec and canonical encoding. |
| ABI byte payload | `Bytes` | Length and padding behavior. |
| Working byte buffer | `MemBuffer` | Capacity and conversion boundaries. |
| Text | `String<N>` or `DynString` as appropriate | Byte-length limits and ABI representation. |
| Persistent map | `StorageMap<K,V>` | Zero state, key encoding, root slot. |

These are not interchangeable containers. Consult [type reference](https://fe-lang.org/appendix/types/) and the [pinned library](https://github.com/argotorg/fe/tree/v26.5.0/ingots/std/src) for constructors, imports, and supported operations. Prefer a tiny compiled usage example over guessing an API from its name.

Arithmetic is checked by default; never assume a narrowing conversion, shift, division, or signed boundary is harmless. Test zero denominators, maxima, negative values where relevant, and conversion boundaries. If intentionally using `#[arithmetic(unchecked)]`, document the mathematical bounds; do not use Solidity's `unchecked { ... }` syntax by habit. Inspect [intrinsics](https://fe-lang.org/appendix/intrinsics/) before relying on low-level behavior.

## 8. Ownership and access modes

A plain parameter provides ordinary read access. `mut` permits mutation through the access; `own` passes ownership. Whether a value can be copied matters for moves. A mutable binding and permission to mutate an accessed object are separate concepts.

Fe access modes are not ordinary storable Rust references. Do not invent lifetime parameters or embed `&mut T` in structs. Mutable accesses can conflict when they overlap; disjoint field accesses can be accepted. Access lifetime follows use, so unnecessarily retaining an access can prevent later operations.

Methods can use `self`, `mut self`, or `own self`. Advanced projected access returns and `mut?` exist; keep them out of the first MVP unless a verified example makes them necessary.

When an access error occurs: shorten the live access, split read/validate/write phases, copy a small value if permitted, or pass a narrower resource. Do not reach for raw memory to silence the checker.

References: [ownership guide](https://fe-lang.org/foundations/ownership/), [access design at the pinned tag](https://github.com/argotorg/fe/blob/v26.5.0/docs/language/accesses.md).

## 9. Structs, enums, traits, and closures

Use enums to represent action variants and failure categories. This is especially valuable for Replay: `Grant`, `Spend`, `Revoke`, and `AdvanceTime` should not become loosely typed JSON inside the Fe core.

Traits describe reusable behavior; implementations and generics allow algorithms to work with multiple concrete providers. Prefer static generic composition for the MVP. Do not assume Rust trait objects, reflection, macros, or every associated-type pattern are supported identically.

Closures can participate in generic collection operations, as the verified fold example shows. Captures and their mutation are restricted; use explicit state parameters/effects instead of designing around a closure that mutates arbitrary captured state. Effect propagation through closure abstractions must also be represented, not hidden.

References: [enums](https://fe-lang.org/compound-types/enums/), [trait definitions](https://fe-lang.org/traits/definition/), [generics](https://fe-lang.org/traits/generics/), [closures](https://fe-lang.org/traits/closures/), [closure design](https://github.com/argotorg/fe/blob/v26.5.0/docs/language/closures.md).

## 10. Effects and capability boundaries

`uses` declares dependencies on state or an environment. `with` supplies a provider. A function can depend on a custom budget/state effect or a trait abstraction instead of reaching into a global object. Callers must satisfy the effect requirements of the code they invoke.

Common EVM capabilities include context, logging, calls, creation, and raw storage/memory/operations. `Evm` is broad; do not inject it into a policy function that only needs caller/time. Keep library functions narrow and let the boundary assemble their dependencies.

Built-in EVM capability traits such as `Ctx`, `Call`, and `Log` are sealed. Application code cannot freely implement mock versions. For unit tests, define an application-owned context/effect or trait; use the real `Evm` provider for integration tests.

**Compile-time access restriction is not runtime authorization.** A spend function can require a budget effect and still pay an unauthorized caller if it never validates the actual sender. The top-level provider, unsafe code, and broad capabilities remain trusted. This is not a sandbox for hostile dynamically loaded code.

Design two separate proofs of behavior: compile-fail examples for forbidden dependency access, and EVM tests for caller permissions, expiry, revocation, callbacks, and rollback.

References: [declaring effects](https://fe-lang.org/effects/declaring-effects/), [propagation](https://fe-lang.org/effects/propagation/), [built-in effects](https://fe-lang.org/effects/built-in/), [pinned effect APIs](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/effects.fe).

## 11. Contract entry points and ABI

Define a `msg` with named variants, parameter types, and return types. Implement it through `recv`. Specify canonical external signatures with `#[selector = sol("functionName(uint256)")]`; the signature uses ABI type names, not Fe names. Calls are synchronous EVM calls, not an actor mailbox.

Keep one reviewed external interface specification. Check generated ABI against it, including outputs, mutability, event fields, and errors. A convenience function marked `pub` is not a substitute for a `recv` entry point. Explicitly decide payable behavior; constructors are non-payable unless marked accordingly.

`#[abi]` supports ABI-compatible structs in the pinned release. Still verify the exact struct/array shapes the application needs. Canonical ABI type equivalence does not imply identical internal memory or storage layout.

References: [defining messages](https://fe-lang.org/messages/defining-messages/), [selectors](https://fe-lang.org/messages/selectors/), [constructor behavior](https://fe-lang.org/contracts/init/), [Solidity ABI specification](https://docs.soliditylang.org/en/latest/abi-spec.html).

## 12. Persistent and transient state

Contract fields are immutable by default; initialize them on every successful constructor path. `mut` fields are persistent mutable state. A handler separately requests write access through `uses (mut field)`.

Each mutable contract field has its own root. Struct packing and mapping rules require attention; do not infer a Solidity contract's entire layout from the appearance of Fe declarations. `TSlot<T>` uses transient storage with a separate namespace and transaction lifetime.

`StorageMap` reads and writes use `get(key: ...)` and `set(key: ..., value: ...)`. An absent entry has the zero representation, which the application must interpret explicitly. Do not instantiate storage resources as a pure in-memory reference model.

Raw layout APIs such as `SolSlot::at` require the caller to prevent aliasing and collisions. Nested Solidity mappings need their actual nested derivation; tuple-key maps are not an automatic substitute. Test packed writes preserve neighboring bytes. Never claim a safe proxy upgrade from ABI tests alone.

References: [storage guide](https://fe-lang.org/contracts/storage/), [maps](https://fe-lang.org/compound-types/maps/), [storage design](https://github.com/argotorg/fe/blob/v26.5.0/docs/language/contract-storage.md), [SolSlot](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/sol_slot.fe), [mapping helpers](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/mapping.fe).

## 13. Errors and transaction failure

**`Result<E,T>` is error-first.** `Err` and `Ok` are values. Returning `Err` does not undo writes that already occurred. A fallible pure policy function should validate before mutating, or return a proposed update that the caller commits on success.

EVM revert is different: it rolls back the failed call's state and logs according to EVM call semantics. Use `#[error]` with `revert_error` for a Solidity custom error. Do not substitute `revert(value)` and assume it automatically prefixes the custom-error selector. Assertions with messages and bare assertions have different revert encodings.

For tests, `#[test(should_revert)]` accepts a revert but alone does not prove its reason. Security tests should verify the expected selector/payload and unchanged state. A deployment failure or out-of-gas failure must not accidentally satisfy an authorization test.

References: [Option and Result](https://fe-lang.org/errors/option-result/), [revert guide](https://fe-lang.org/errors/revert/), [Result source](https://github.com/argotorg/fe/blob/v26.5.0/ingots/core/src/result.fe), [returndata helpers](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/returndata.fe).

## 14. Calls, context, logs, and reentrancy

Use typed calls for ordinary successful contract interaction. To compare failure behavior, use a verified lower-level call path that exposes success status and returndata; a helper that automatically bubbles a revert cannot be your sole observer.

The pinned `Call` source provides `try_call`, `try_call_raw`, and `try_static`, returning a `CallOutcome` with success and returndata accessors. `send_value` exposes a raw outcome for an empty-calldata payment. These APIs were source-checked here, but not exercised by the introductory examples; compile a focused failure-capture test before integrating them.

Read actual caller, call value, and timestamp at the EVM boundary. `Ctx` uses domain types such as `Wei` and `Timestamp`; check the source when an overview table loosely describes them as integers.

Represent events with the supported event declaration mechanism and inspect emitted topics/data. Event ordering and indexed fields are observable behavior. Failed calls must not leave committed success events behind.

Apply checks/effects/interactions and explicitly handle recipient failure. Any external call can invoke hostile code. Inspect the existing mutex before implementing another guard. Transient guards must unlock for a later legitimate call in the same transaction, while blocking callbacks into protected mutations.

References: [EVM APIs](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm.fe), [effects source](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/effects.fe), [call utilities](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/calls.fe), [event ABI](https://fe-lang.org/events/abi/), [mutex](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/mutex.fe).

## 15. Units, fixed point, and existing libraries

Keep payment amounts as `Wei`, times as `Timestamp`, and intervals as `Duration` inside policy code when practical. Convert to ABI integers at explicit boundaries. The library provides unit constructors and accessors such as `as_wei` and `as_seconds`; verify imports and receiver types before use.

Fixed-point types encode scale in their type (`UFixed<D>`, `Fixed<D>`, with common aliases). Choose rounding deliberately; financial arithmetic requires tests around tiny values, saturation boundaries, and scale conversion. The treasury MVP needs integer wei, not a new fixed-point math library.

Before writing crypto or token infrastructure, inspect the existing EIP-712, signature, ERC, Merkle, RLP, SSZ, and collection modules. Reuse does not eliminate the need to understand their assumptions or test the behavior used by your contract.

References: [units](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/units.fe), [fixed point](https://github.com/argotorg/fe/blob/v26.5.0/ingots/core/src/fixed.fe), [standard-library inventory](https://github.com/argotorg/fe/tree/v26.5.0/ingots/std/src/evm).

## 16. Deterministic randomness

The pinned library already provides `Rng`, `KeccakRng`, and `ReplayRng`. Use these as building blocks; do not pitch the mere existence of a seeded generator as the Replay project's novelty.

Record final typed actions as well as seed and generator version. A seed alone stops reproducing behavior if generation rules change. `ReplayRng` cycles supplied values. Rejection sampling can fail to terminate when a repeating stream never produces an acceptable value; bound generation work and test this explicitly. Calling a uniform sampler with an invalid bound must also be handled.

These are deterministic testing utilities, not proof of secure on-chain randomness. Do not use predictable PRNG output for valuable lotteries or secret generation.

Reference: [random implementation](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/random.fe).

## 17. Testing, debugging, and execution environment

Use `#[test]` for unit tests and an `Evm` effect for contract deployment/calls. Pure model tests can additionally run with `--backend native` when supported. Keep backend-specific adapters separate.

The documented EVM target for this baseline is **Osaka**. A local Anvil process must support the required fork; the docs use `anvil --hardfork osaka`. Pin and verify Foundry instead of assuming an older installation can execute generated bytecode. Fe's test environment can lift transaction gas limits, so passing tests do not establish real-chain deployability.

Debug through a minimized failing test, logs, call traces, EVM traces, and the CLI report bundle. Use `--help` for trace size and native timeout/output settings. Never classify infrastructure failure, timeout, or unsupported opcode as a discovered contract property violation.

References: [unit testing](https://fe-lang.org/testing/unit-testing/), [runner](https://fe-lang.org/testing/runner/), [integration](https://fe-lang.org/testing/integration/), [mocking](https://fe-lang.org/testing/mocking/).

## 18. External tools and native integration

Foundry already provides sophisticated invariant testing, replay/corpus workflows, and minimization. Our tools must justify a Fe-specific benefit beyond duplicating these basics. Establish an actual pinned baseline before making comparative claims.

A practical architecture is a Fe core with a thin host adapter. The host may parse JSON, launch tests, drive local RPC, store artifacts, and render diffs. The Fe core owns domain decisions and the central algorithm. Do not assume Fe has Rust's complete file/network/serialization ecosystem. Inspect `std::native` and prove the exact input/output path required.

A compiled Fe program that consumes generated fixture constants is a valid narrow fallback if runtime file parsing would consume the schedule. Disclose this limitation; do not describe it as a universal interactive CLI.

References: [native source](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/native.fe), [Foundry invariant testing](https://www.getfoundry.sh/guides/invariant-testing), [Foundry corpus workflow](https://www.getfoundry.sh/guides/fuzz-corpus), [Fe/Foundry example](https://github.com/fe-lang/bountiful).

## 19. Shared fixture contract: proposed treasury v0

This is **our proposed behavioral specification**, not an existing Fe API. It gives the three projects a consistent demonstration without making them variants of one submission. Freeze it before implementation.

The treasury holds ETH. An immutable owner creates grants. Each grant has a monotonically increasing ID, delegate, fixed recipient, lifetime cap, spent amount, expiry, and active flag. Grants do not reserve funds. No tokens, rolling daily budgets, signatures, owner rotation, production proxies, or cross-chain calls are in v0.

| Proposed operation | Behavior |
|---|---|
| Deposit | Any sender may fund the treasury through an explicit payable entry point; zero value is a no-op without an event. |
| Grant | Owner chooses nonzero delegate/recipient, positive cap, and future expiry; creates a new ID. |
| Revoke | Owner deactivates a known grant; repeated revocation is a no-op without another event; unknown ID reverts. |
| Spend | Only that grant's delegate; positive amount; active grant; `now < expiry`; sufficient remaining cap and ETH. Pay only its fixed recipient. |
| Observe | Return complete public grant state and relevant treasury observations without mutation. |

Validate `spent <= cap` and `amount <= cap - spent` before addition. Update accounting before payment; if payment fails, revert the whole operation. Guard all sensitive mutating entry points against cross-function reentrancy. A later normal operation in the same transaction must still work.

Only deposit accepts transaction value. The Capabilities plan provides the detailed error precedence, event contract, and callback policy; freeze these into one shared specification before implementing the adapters.

Use a new ID for a new grant; revocation must not revive through slot reuse. Consider forced ETH when defining balance invariants: raw balance is not universally equal to explicit deposits minus spends. Test recipient rejection, reentry, insufficient balance, expiry equality, unknown IDs, and untrusted callers.

Fixtures use stable actor roles, integer quantities as decimal strings, and bytes as `0x` strings. Store schema version, compiler/backend/fork, initial state, actual actions, environment changes, target hashes, and expected property ID. Plans may extend the schema explicitly; reject unsupported versions.

## 20. Complete examples verified for this reference

### A. Pure language, effects, Result, generic, and collection example

Save as `language_smoke.fe`. This is original example code tested on both the default EVM test backend and the native test backend.

```fe
struct Budget { left: u256 }

enum SpendError {
    Empty,
    TooLarge,
}

fn reserve(amount: u256) -> Result<SpendError, u256> uses (budget: mut Budget) {
    if amount == 0 {
        return Err(SpendError::Empty)
    }
    if amount > budget.left {
        return Err(SpendError::TooLarge)
    }
    budget.left -= amount
    Ok(budget.left)
}

fn preserve<T>(value: own T) -> T {
    value
}

#[test]
fn reserve_success_and_failure() {
    var budget = Budget { left: 25 }
    with (mut budget) {
        match reserve(amount: 9) {
            Ok(left) => assert!(left == 16),
            Err(_) => assert!(false),
        }
        assert!(reserve(amount: 17).is_err())
    }
    assert!(budget.left == 16)
    let flag = preserve<bool>(value: true)
    assert!(flag)
}

#[test]
fn collection_and_closure() {
    var values: MemVec<u256> = MemVec::new()
    values.push(3)
    values.push(8)
    let total = values.fold(0, |acc: own u256, x: u256| acc + x)
    assert!(total == 11)
}
```

### B. Deploy, call, observe, and reject a typed message

Save as `contract_smoke.fe`. This is original example code tested with the default EVM test backend. The broad expected-revert test is introductory; project security tests must check the reason and state.

```fe
use std::abi::sol

msg MeterMsg {
    #[selector = sol("add(uint256)")]
    Add { quantity: u256 },
    #[selector = sol("total()")]
    Total -> u256,
}

#[error]
struct EmptyQuantity {}

pub contract Meter {
    mut total: u256,

    init() uses (mut total) { total = 0 }

    recv MeterMsg {
        Add { quantity } uses (mut total) {
            if quantity == 0 {
                revert_error(EmptyQuantity {})
            }
            total += quantity
        }
        Total -> u256 uses (total) {
            total
        }
    }
}

#[test]
fn meter_round_trip() uses (evm: mut Evm) {
    let target = evm.create2<Meter>(value: Wei::zero(), args: (), salt: 7)
    evm.call(
        addr: target,
        gas: 100000,
        value: Wei::zero(),
        message: MeterMsg::Add { quantity: 13 },
    )
    let observed: u256 = evm
        .call(
            addr: target,
            gas: 100000,
            value: Wei::zero(),
            message: MeterMsg::Total {},
        )
    assert!(observed == 13)
}

#[test(should_revert)]
fn meter_rejects_zero() uses (evm: mut Evm) {
    let target = evm.create2<Meter>(value: Wei::zero(), args: (), salt: 9)
    evm.call(
        addr: target,
        gas: 100000,
        value: Wei::zero(),
        message: MeterMsg::Add { quantity: 0 },
    )
}
```

### Recorded verification

| Check performed on 7 November 2026 | Result |
|---|---|
| `fe --version` | `fe 26.5.0 (3dab95f)` |
| Generated `fe new` project, then `fe test` | 1 passed |
| Generated project build emitting bytecode, runtime bytecode, ABI, metadata | Passed; artifacts produced |
| `fe test language_smoke.fe contract_smoke.fe` | 4 passed, 0 failed |
| `fe test language_smoke.fe --backend native` | 2 passed, 0 failed |

No Foundry/Anvil integration, full treasury, project implementation, benchmark, or security audit was completed as part of preparing these documents. Those are explicit plan gates.

## 21. Common failure diagnosis

| Symptom | First investigation |
|---|---|
| Unexpected `Result` type mismatch | Check error/value generic order. |
| Unknown generic or argument syntax | Compare with a pinned passing fixture and labeled call. |
| Missing effect | Trace the callee's `uses` and the provider at the call site. |
| Mutable access conflict | Shorten overlapping accesses; separate validation and writeback. |
| Contract compiles but selector fails | Compare canonical signature, emitted ABI, and raw calldata. |
| Native test fails on EVM operation | Separate pure core from EVM adapter; do not stub away the claim. |
| Revert caught as test success for wrong reason | Check exact payload and isolate deployment/setup from the operation. |
| Local execution reports invalid opcode | Confirm compiler target and local fork/tool support. |
| Matching getters but incompatible upgrade | Inspect explicit storage slots, packing, immutables, and mapping derivation. |
| Seed does not reproduce | Replay saved actions, generator version, environment, and initial state. |
| Reduced case fails differently | Preserve failure identity, not just a nonzero process exit. |

## 22. Contest and portfolio constraints

The [contest page](https://fe-lang.org/contest/) was checked on 7 November 2026. Registration closes **17 November, 23:59 UTC**; submission closes **24 November, 23:59 UTC**. Register each distinct project separately. Variants of the same work are not separate entries.

Each submission needs a public repository, OSI-approved license, exact project commit and Fe version, reproducible tests/build, limitations, and disclosure of reused work and AI assistance. Its central contribution must be Fe; compiler/Rust contributions alone do not qualify. The score weights are technical quality 30%, Fe-specific value 25%, originality 20%, usefulness 15%, documentation/demo 10%.

Our proposed distinction is: Replay owns failure-preserving reduction; Compatibility owns conformance evidence and bounded layout validation; Capabilities owns reusable authorization/execution composition. Shared fixture code must be identified, pinned, and separated from each original contribution. Recheck the official rules before submitting; sharing a fixture does not itself establish eligibility.

## 23. Session handoff template

Copy this brief into a coding agent together with the selected plan:

```text
Read FE_AGENT_REFERENCE.md and the selected project plan.
Work on the first incomplete phase only, carrying it through its exit gate.
Inspect the repository and pinned toolchain before editing.
Keep core algorithms in Fe and preserve the documented MVP boundaries.
For unfamiliar APIs, inspect pinned source and compile a minimal experiment.
Add meaningful correctness tests, including the phase's negative cases.
Do not claim a command or test ran unless you ran it.
Report: changes, exact checks/results, unresolved limitations, next gate.
If blocked, produce a minimal reproduction and the plan's bounded fallback.
Do not publish, contact anyone, deploy with real funds, or submit forms as part
of an implementation task unless the user separately authorizes that action.
```

## 24. Definition of implementation-ready

- [ ] Compiler/version and platform are recorded; baseline examples pass locally.
- [ ] External behavior and error precedence are frozen in a reviewed specification.
- [ ] The core Fe contribution is identifiable without the presentation layer.
- [ ] Every runtime claim has an EVM or native execution check appropriate to it.
- [ ] Every compile-time boundary has a positive control and targeted negative case.
- [ ] Failures distinguish domain violations from harness/infrastructure errors.
- [ ] Unsafe and raw-layout operations have written preconditions and focused tests.
- [ ] A clean checkout runs using documented, pinned dependencies.
- [ ] Reused code, unimplemented features, and AI assistance are disclosed accurately.

This checklist is a project completion aid, not a statement that the proposed projects already satisfy it.
