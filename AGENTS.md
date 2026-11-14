# Working in fe-compatibility

This directory is an independent Git repository. Make commits here; preserve its
existing history when adding a remote and pushing.

Read `docs/reference/FE_AGENT_REFERENCE.md` and
`docs/reference/FE_COMPATIBILITY_PLAN.md` before implementation. Work on the first incomplete
phase and its exit gate; Phase 0 is pending.

Use Fe 26.5.0 at commit `3dab95f8eebdccf9a2382bb59a33f7bbd03540ca`.
From this repository root, run `python3 scripts/bootstrap-fe.py` when needed,
then `source scripts/env.sh`. Keep central algorithms in Fe. Record exact
commands, tool versions, outcomes, and limitations in `docs/feasibility.md`.
Do not treat setup or generated smoke tests as completion of a phase gate.
