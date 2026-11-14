# fe-compatibility

Status: prepared for Phase 0; no acceptance gate completed.

Read [the plan](docs/reference/FE_COMPATIBILITY_PLAN.md) and [the reference](docs/reference/FE_AGENT_REFERENCE.md).

Use `spike/` for the initial compiler-generated ingot.
Record exact experiments and results in `docs/feasibility.md`.

First exit gate: Exact success/revert bytes and events compared by a Fe checker.

## Local setup

This directory is an independent Git repository. Commit and push from here to
preserve this project's history. Shared references are vendored in
`docs/reference/`; setup does not depend on the parent workspace.

```sh
python3 scripts/bootstrap-fe.py
source scripts/env.sh
fe check spike
fe test spike
```

Each repository uses its own `main` branch. Add its remote when available:

```sh
git remote add origin <this-project-repository-url>
git push -u origin main
```

Future commits should be made in this repository; pushing the existing branch
retains the complete history.
