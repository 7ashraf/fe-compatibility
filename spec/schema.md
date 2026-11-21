# Observation schema, vector format, and normalization allowlist (v1)

Status: **frozen, revision 1, 21 November 2026.** The host loader enforces
everything here (`host/vectors.py`). The Fe checker enforces the observation
limits again on its own side.

## Observation (what one call or deployment exposed)

| Field | Rule |
| --- | --- |
| `success` | Receipt status, which must agree with the trace's `failed` flag |
| `returndata` | Exact bytes as `0x` hex, ≤ 256 bytes. Taken from `debug_traceTransaction` and cross-checked with `eth_call` at the parent block (a mismatch is an infrastructure error). On a successful deployment it is the runtime code, which is recorded but never compared. |
| `logs` | Ordered list, ≤ 4 per call, each `{address, topics (≤ 4), data (≤ 256 bytes)}` |
| `gas_used` | Recorded but never compared |

A reverted call or deployment must have no logs. Oversized or contradictory
observations are errors. They are never truncated.

**Deployments are observed separately from calls.** If a deployment fails in
either world, the result is `not-comparable`. No later step can make it a
match, so a constructor revert can't stand in for an expected application
revert.

## Comparison modes and claims

| Mode | Compared | Passing does not establish |
| --- | --- | --- |
| ABI conformance (Phase 1) | Canonical declarations against the frozen ABI. Golden calldata classified by the Fe ABI validator. Observed bytes, events, and returndata canonicality against independent golden vectors. | Correct business logic |
| Behavioral, strict | Status, exact returndata, and ordered logs per step, with the first divergence | Equivalence beyond the corpus |
| Behavioral, rejection scope | Status and logs only, for compiler-generated rejections | Equal revert encodings |

## Address normalization allowlist

Two worlds may use different concrete addresses. Each world gives the Fe
checker a table mapping its addresses to role IDs. Fe rewrites only these
positions:

1. every log's **emitter**;
2. **returndata words** whose declared output type is `address` (successful
   calls only, word-aligned static heads);
3. **topics** whose indexed event parameter is `address`;
4. **log-data words** whose non-indexed event parameter is `address`.

The positions belong to the function signature, not to the outcome of a
particular call. The vector file records them for every vector, valid or
malformed, because a malformed call may still be accepted and emit events. The
loader re-derives them from the frozen ABI and the spec's event list. Nothing else is ever rewritten. That
includes `uint256` words, `bytes` contents, and revert payloads, even if their
bytes equal an actor's address. There is no global byte-pattern replacement.
Raw observations are always kept; normalization happens only inside Fe.

## ABI vector file `fe-compatibility-abi-vectors`, schema version 1

- **Top-level keys, all required, no others:** `format`, `schema_version` (the
  JSON integer 1), `fixture`, `interface_sha256` (SHA-256 of the frozen ABI
  file), `reference_world`, `constructor`, `vectors`, `deployment_vectors`,
  `provenance`.
- **Quantities** (arguments, expected values) are canonical decimal strings,
  with `-` allowed only for `int` types. A JSON number, boolean, or null in a
  quantity position is rejected, so values beyond 2^53 can't pass through a
  lossy float. Only structural fields are small JSON integers or booleans:
  `schema_version`, `calldata_index`, normalization indices, and `success`.
  Bytes are lowercase `0x` hex.
- **Addresses** are either `0x` + 40 lowercase hex, or `{"role": name}`,
  resolved per world. Role names: `deployer`, `caller`, `target`, `zero`.
- **`reference_world`** holds the concrete role addresses the golden bytes
  were computed for: deployer = Anvil account 0, caller = account 1, target =
  the deployer's first created contract.
- **A vector** has:
  - `id`, unique, matching `[a-z0-9-]{1,64}`;
  - `kind`, `valid` or `malformed`;
  - `signature`, `inputs`, `outputs`, `args`, all type strings from the frozen ABI;
  - `calldata`;
  - `calldata_category`, one of `canonical`, `selector`, `truncated`,
    `extra`, `type`, `offset`, `length`, `padding`, plus `calldata_index`;
  - for valid vectors, `expected`, of the form
    `{success, returndata, logs:[{emitter, topics, data}]}`, plus
    `normalize`, of the form `{return_words, topics:[[log, index]], data_words:[[log, word]]}`;
  - for malformed vectors, `expected_outcome`, `reject` or `unspecified`.
- **Deployment vectors** give constructor arguments and the expected
  deployment status.
- **Limits:** ≤ 64 vectors, ≤ 256 bytes of calldata or returndata, ≤ 4 logs,
  ≤ 4 topics, text ≤ 256 characters.

An unknown version, a missing or extra field, or a value over a limit is an
invalid input (exit 2). It never gets a verdict.

## Raw execution record `fe-compatibility-raw-execution`, version 2

Version 2 adds a `world` (role → address) and a `deployment` observation to
the Phase 0 v1 record. The v1 records in `docs/evidence/phase0/` remain as
historical evidence.

## Native checker protocol

Protocol version 2 is documented at the top of `host/checker-native/src/lib.fe`.
Version 1, used in Phase 0, has been retired.
