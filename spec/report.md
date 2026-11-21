# Conformance report `fe-compatibility-report`, version 1

Status: **frozen, revision 1, 21 November 2026.** Produced by `host/report.py`
(for example, `python3 host/observe.py --left solidity --right fe`). The report
is written with sorted keys and contains no timestamps. Two runs of the same
pinned configuration produce byte-identical reports, and the Phase 2 gate
checks this.

The Fe checker decides everything in `decision` and, for each listed mismatch,
its `category`, `location`, and `fe` values. The `strict` and `explanation`
views only present those decisions. They never change a verdict.

| Key | Content |
| --- | --- |
| `format`, `version` | `fe-compatibility-report`, `1` |
| `mode` | For example `behavioral conformance (strict)` |
| `corpus` | Corpus identifier |
| `configuration.left` / `.right` | Implementation name, target identity (compiler, settings, creation and runtime SHA-256), world roles, deployed runtime SHA-256 |
| `tools`, `environment` | Pinned Anvil/Cast versions; chain, fork, timestamps, and gas settings |
| `raw_records_sha256` | SHA-256 of each canonical raw execution record (`fe-compatibility-raw-execution` v2), so the report can be tied to its raw evidence |
| `decision` | `checker`, `verdict` (`match`, `mismatch`, `malformed`, or `not-comparable`), `steps_compared`, `mismatching_steps`, `listed` (≤ 8), `truncated` |
| `claim` | One sentence that limits the claim to this corpus and configuration |
| `state_declared` | The public state read after every call: name, getter, kind |
| `mismatches[]` | Up to 8 entries, in step order. The first one is the first divergence. |
| `malformed` | When the verdict is `malformed`: the `reason` (see below), plus `deployment` and `step` |
| `deployment_succeeded` | When the verdict is `not-comparable` |
| `abi_declarations` | Declaration conformance of both compiled ABIs against the spec: `match`, plus `missing` and `unexpected` per side |
| `gas_used` | Per step and per side. It is never compared. |

## A mismatch entry

| Key | Content |
| --- | --- |
| `step`, `deployment`, `action` | Where the divergence happened: the action label, or the deployment |
| `category` | One of the 17 Fe categories below |
| `location` | `log` index, `index` (a byte offset, topic index, log position, or state field), and `slot` (a return word, error argument, data word, or state field) |
| `fe` | Fe's `left` and `right` values: the full 32-byte words, selectors, lengths, counts, or flags |
| `strict` | The exact raw bytes involved: both returndatas, both log lists, or both state entries |
| `explanation` | `what` (a sentence), plus typed `left` and `right` values decoded from the ABI |

## Categories, in the order checked within a step

| Group | Categories |
| --- | --- |
| Status | `status` |
| Revert data | `error-selector`, `error-argument`, `returndata-length`, `returndata-byte` (only for payloads under 4 bytes) |
| Success data | `returndata-length`, `returndata-byte` |
| Logs (sequence) | `log-missing` (one deletion), `log-extra` (one insertion), `log-reordered` (same multiset), `log-count` (anything else) |
| Logs (fields) | `log-emitter`, `topic-count`, `topic`, `log-data-length`, `log-data-byte` |
| Typed state | `state-count`, `state-kind`, `state-value` |

**Malformed reasons:** `oversized`, `padding`, `logs-on-revert`,
`too-many-logs`, `too-many-topics`, `emitter`, `stray-data`,
`too-many-state`, `state-value`. A malformed observation is a harness or
transport problem and never a behavior verdict.

**Limits:**

- 256 bytes per payload
- 4 logs, each with 4 topics
- 8 state fields
- 64 steps
- 8 listed mismatches

Over-limit observations are reported as malformed, never truncated. The
mismatch list is bounded at 8 entries, but `mismatching_steps` always counts
every mismatching step.
