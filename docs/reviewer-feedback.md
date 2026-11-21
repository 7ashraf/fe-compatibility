# Independent tester feedback

Status: **pending**. No one outside the implementation has done the
[tester guide](tester-guide.md) exercise yet. The implementing agent's own dry
runs, including the scripted exercise in `scripts/verify-phase5.py`, don't
count. The Phase 5 runner reports this item as pending until the status above
reads "received", with a filled-in record below.

The tester may use an alias. Record their relationship to the project, so the
scope of independence is clear. Keep their actual observations, including
failures and misunderstandings. Don't prefill answers.

## Record (copy one per tester)

- Tester (name or alias, with permission) and their relationship to the project:
- Date (UTC) and commit (`git rev-parse HEAD`):
- OS / architecture / Python / Foundry version:
- Setup: did steps 1–3 work as written? What went wrong?
- Who planted the mistake (the tester or a helper), and what was it
  (`port-exercise.py diff`)?
- Did `check` report a mismatch? Which scenario, action, and category?
- Could you locate the faulty line from the report alone? How long did it
  take (`port-exercise.py status`)?
- After the fix, did `check` print `PASS` without you editing anything outside
  `exercise/`?
- What was unclear in the report or this guide?
- Any errors or deviations from the documented behavior:
