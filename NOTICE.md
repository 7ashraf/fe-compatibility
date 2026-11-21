# License, reuse, and attribution

Project-authored code, fixtures, and documentation are MIT ([LICENSE](LICENSE)),
copyright 2026 Fe Compatibility contributors.

| Material | Origin |
| --- | --- |
| `src/`, `host/checker-native/`, `host/observe.py`, `host/common.py`, `scripts/build.py`, `scripts/verify-phase0.py`, `contracts/`, `spec/` | Project implementation of the supplied plan. The Solidity meter was written from `spec/meter-v0.md`, not translated from the Fe port. |
| `host/evm_chain.py` | Copied from the sibling project fe-replay (`host/evm_chain.py`), which adapted it from Fe Capabilities `scripts/local_chain.py`. Both are MIT and have the same owner. |
| `scripts/bootstrap-fe.py`, `scripts/env.sh`, `spike/` | Workspace scaffolding. `spike/` was generated with Fe 26.5.0 `fe new`. |
| `scripts/bootstrap-solc.py` | Copied from fe-replay (MIT). |
| `host/checker-native/src/lib.fe` number parsing and printing | Follows the bounded decimal transport pattern of fe-replay's native engine. |
| `docs/reference/` | The reference and plans the workspace owner supplied. |
| Fe compiler and its bundled core/std, Solidity compiler, Foundry | External tools. They are not redistributed, and `.tools/` is git-ignored. |

Fe is Apache-2.0 at the pinned source; a copy of its license is in
[licenses/](licenses/Fe-APACHE-2.0.txt).

The `fe-faulty` variant is a **deliberately seeded** fault for harness
validation.

## AI assistance

Phase 0 was implemented, run, and documented by Claude Opus 5.5 in Claude Code,
directed by the project owner. Commits carry a `Co-Authored-By` trailer. The
verification runs are the agent's own, not independent review.
