# Treasury v0 contract

Status: **frozen implementation target, revision 1, 14 November 2026**.
The full EVM interface is implemented and tested; see
[Phase 3 results](../docs/phase3.md). `spike/PaymentProbe` remains separate
feasibility evidence. Any semantic change must revise this spec, its target ABI,
and vectors.

[treasury-v0.abi.json](treasury-v0.abi.json) is the machine-readable target ABI.
All quantities are unsigned 256-bit values. Amounts are integer wei, times are
Unix seconds, addresses are canonical ABI addresses. Fe uses `Wei`, `Timestamp`,
and `GrantId` internally. No tokens, signatures, proxies, or owner rotation.

## State and lifetime

Constructor: `constructor(address owner)`, nonpayable; zero owner reverts with
`InvalidOwner()`. Owner is immutable, may be a contract, and is supplied explicitly.

`nextGrantId` starts at 1. A successful creation allocates the current ID then
increments it. IDs never repeat. `MAX = 2^256 - 1` is reserved as an exhaustion
sentinel: allocatable IDs are 1 through MAX-1. A zero/exhausted next ID yields
`GrantIdExhausted()`, never arithmetic wrap. No state changes on rejection.

Each grant has an explicit `exists` bit, delegate, fixed recipient, cap, spent,
exclusive expiry, and active flag. Creation sets exists/active true and spent 0.
Revocation only sets active false. There is no deletion or reactivation. Zero and MAX IDs
are always unknown. Absent storage must not authorize a spend, even if its zero
values resemble an account or timestamp in a pure test.

A grant allocates permission, not treasury funds. Caps may exceed the current
balance in aggregate. ETH can arrive without a deposit event (e.g. forced ETH);
`treasuryBalance()` returns actual EVM balance. No invariant equates that balance
with deposits minus payments.

## ABI

| Signature | Returns | Mutability |
| --- | --- | --- |
| `deposit()` | none | payable |
| `createGrant(address,address,uint256,uint256)` | `uint256 grantId` | nonpayable |
| `revoke(uint256)` | none | nonpayable |
| `spend(uint256,uint256)` | none | nonpayable |
| `owner()` | `address` | view |
| `nextGrantId()` | `uint256` | view |
| `treasuryBalance()` | `uint256` | view |
| `getGrant(uint256)` | `(bool,address,address,uint256,uint256,uint256,bool)` | view |

`createGrant` arguments: delegate, recipient, cap, expiresAt, in that order.
`spend` arguments: grantId and amount. The recipient cannot be overridden.
`getGrant` returns exists, delegate, recipient, cap, spent, expiresAt, active as
seven flat ABI output words. Unknown IDs, including zero and MAX, return
`(false,0x0,0x0,0,0,0,false)`, without reverting. All getters are public and
read-only; there is no transaction-origin authorization.

Only `deposit()` accepts transaction value. It accepts any sender; zero value
is a successful no-op without an event, while still respecting the lock.
Empty calldata and unknown/short selectors with zero value revert with
`UnsupportedCall()` via an explicit nonpayable fallback. Value sent to a
nonpayable function, fallback, or constructor is rejected before domain checks.
Malformed calldata for a known selector must fail ABI decoding before domain
checks. Dispatch, malformed ABI, and automatic nonpayable failures follow the
pinned compiler's rejection encoding; no application custom error is promised
for these compiler-generated failures. Their rejection and unchanged state are
checked by the administration and spending runners.

## Validation precedence

All mutating entry points first pass compiler dispatch/payability/ABI checks,
then acquire the same standard-library transient mutex. A busy lock produces
`Reentrant()`. Authority and policy checks occur under that lock. Successful
calls explicitly unlock; revert restores the previous accounting and lock.
Getters remain available during callbacks and do not take the lock.

### Create

For valid deployed state: owner authority, nonzero delegate and recipient,
positive cap, expiry strictly greater than current time, available ID, then
creation. Return the allocated ID and emit `GrantCreated` exactly once.

The pure evaluator also rejects a zero owner as `InvalidOwner()` before authority;
this represents a violated constructor invariant, unreachable in a valid deployment.
Address validation precedes cap validation, which precedes expiry and ID checks.
A cap of MAX and expiry of MAX are valid when time is strictly earlier.

### Revoke

Owner authority, known allocated ID (excluding zero and MAX), then inspect active. Known active becomes
inactive and emits one `GrantRevoked`. Known inactive is a successful no-op
without an event. Expiry, spent, and balance do not prevent revocation. Wrong
owner wins over unknown ID. A corrupt budget can still be revoked.

### Spend

After dispatch and lock, checks are strictly ordered:

1. Known allocated ID, excluding zero and MAX (`UnknownGrant`). Existence is checked before authority
   because the actual delegate must be loaded from a known record.
2. Actual caller equals stored delegate (`Unauthorized`).
3. Grant is active (`InactiveGrant`).
4. Amount is positive (`InvalidAmount`).
5. Current time is strictly less than expiry (`Expired`); equality rejects.
6. Record integrity: nonzero delegate/recipient, positive cap, spent <= cap
   (`InvalidGrantState`). This prevents corrupt records from underflowing.
7. Amount <= cap - spent (`CapExceeded`).
8. Amount <= actual available ETH (`InsufficientBalance`).
9. Reserve accounting: set spent to old spent + amount; release any live
   mutable projection; attempt payment only to the stored recipient.
10. Payment must succeed (`PaymentFailed`); emit `Spent` and unlock.

The trusted EVM boundary builds the policy context from `Ctx::caller`,
`Ctx::timestamp`, and `Ctx::selfbalance` within this invocation, immediately
before policy evaluation. No caller/time/balance argument is accepted publicly.
The pure decision is a snapshot of a proposed transition, not a bearer authority
or a reusable authorization token; it must never be cached for later execution.

Payment uses empty calldata, exact amount, and `Call::send_value` with requested
gas 100,000. EVM gas caps/stipend still apply. Recipients requiring more gas may
fail; there is no configurable recipient or gas argument. Failure data from the
recipient is not bubbled or copied; map unsuccessful outcome to `PaymentFailed()`.
Transaction-level out-of-gas is distinct from a guaranteed application error.

All protected mutations (deposit, create, revoke, spend) share the lock. Callback
mutations fail with `Reentrant()` after dispatch checks. Read-only callbacks may
see reserved spent accounting and the actual balance after value transfer. This
is the specified intermediate view; the mutex does not conceal it. A failed
payment restores accounting, value transfers, lock, and any logs. A second
legitimate operation in the same transaction must work after explicit unlock.

## Custom errors

| Canonical signature | Payload source |
| --- | --- |
| `InvalidOwner()` | constructor or invalid pure owner input |
| `Unauthorized()` | caller mismatch |
| `InvalidAddress()` | zero creation delegate/recipient |
| `InvalidAmount()` | zero cap at creation or zero spend |
| `InvalidExpiry()` | new expiry <= current time |
| `GrantIdExhausted()` | next ID is zero or MAX |
| `UnknownGrant(uint256)` | requested grantId |
| `InactiveGrant(uint256)` | requested grantId |
| `Expired(uint256,uint256)` | stored expiresAt, currentTime |
| `InvalidGrantState()` | invalid stored addresses/cap/spent |
| `CapExceeded(uint256,uint256)` | cap - spent, requested amount |
| `InsufficientBalance(uint256,uint256)` | actual available balance, requested amount |
| `PaymentFailed()` | failed recipient call |
| `Reentrant()` | shared mutex already held |
| `UnsupportedCall()` | zero-value unmatched calldata |

Static errors encode the four-byte Keccak selector followed by the specified
32-byte ABI words, in order; no assertion string substitutes for a public policy
error. The pure `PolicyError` enum carries categories, and the later adapter
must encode payloads from the same loaded snapshot. These errors describe
application rejections; unexpected compiler traps are not successful policy
validation.

## Events

All events are non-anonymous, with topic0 the Keccak of the canonical signature.
Indexed fields are listed explicitly; other fields are ABI data in listed order.

| Signature | Indexed fields | Data fields |
| --- | --- | --- |
| `Deposited(address,uint256)` | sender | amount |
| `GrantCreated(uint256,address,address,uint256,uint256)` | grantId, delegate, recipient | cap, expiresAt |
| `GrantRevoked(uint256)` | grantId | none |
| `Spent(uint256,address,address,uint256,uint256)` | grantId, delegate, recipient | amount, newSpent |

Emit one Deposited for a positive explicit deposit, one GrantCreated per new
record, one GrantRevoked for the first revocation, and one Spent after a
successful payment. Zero deposits and repeated revocations emit none. Events
from recipient code can precede the treasury's Spent event; only the treasury's
own success event is specified here. A failed outer call leaves no committed
success event or recipient log from that failed call.

## Phase boundaries and evidence

The pure policy implements construction validation, owner authority, creation,
revocation, and spend decisions. [Explicit vectors](../tests/vectors/policy-v1.json)
freeze both expected success values and error precedence, including maximal
quantities. The test generator only renders literals and assertions into Fe;
it contains no second implementation of policy decisions.

Storage layout is not frozen by this ABI. Phase 2 implements persistent
administration and compares its emitted ABI/events with the corresponding
subset of this target. Phase 3 integrates spending, payment failure, and
hostile callback tests, and verifies the complete target ABI. The
Phase 0 spike remains separate feasibility evidence throughout.
