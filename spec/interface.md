# Frozen interfaces

| Interface | Revision | Source | Used by |
| --- | --- | --- | --- |
| Meter v0 | Phase 0 | [meter-v0.md](meter-v0.md) | Observation-path proof |
| Codec v1 | 1 (21 November 2026) | [codec-v1.md](codec-v1.md), [codec-v1.abi.json](codec-v1.abi.json) | ABI conformance (Phase 1) |
| Treasury v0 | 1 (14 November 2026) | [vendor/treasury-v0/](vendor/treasury-v0/), vendored from Fe Capabilities at `ba6893c` | Behavioral corpus (Phase 3), [scenarios](scenarios.md) |

The treasury specification is vendored unchanged, and its SHA-256 hashes are
pinned in `vendor/treasury-v0/provenance.json`. It already freezes:

- external signatures and payable flags (only `deposit()` is payable);
- validation precedence for create, revoke, and spend;
- every custom error's payload;
- event fields and indexing;
- repeated revocation as a successful no-op with no second event, and
  revocation of an unknown ID as a revert.

The plan requires these choices to be identical in both versions. When this
project compares treasury implementations, it adds:

- **Strict error comparison** wherever the spec defines a precedence. If a
  request breaks several rules, both implementations must report the same
  first error, with exact selector and payload.
- **Rejection scope** (status and logs only) for dispatch, payability, and ABI
  rejections. The spec leaves those to "the pinned compiler's rejection
  encoding".
- **Treasury-emitted events only**, under the event contract. Logs from
  recipient code are recorded, and are compared only within a step's declared
  scope.
- **ETH movement and public state** observed through the getters after each
  action. That is Phase 3.

Changing any frozen interface means a new revision, an updated ABI file,
regenerated vectors, and a recorded reason.
