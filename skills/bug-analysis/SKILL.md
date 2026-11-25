---
name: bug-analysis
description: Record a reported defect in merged work by its root cause before fixing it. Load when someone reports a wrong value, an error, a flaky step or a failed release on the main branch, and before a `fix` commit. Not for a test failing in your own unmerged work, features or redesigns.
---

# Bug analysis

A test failing in your own unmerged change is not a bug: make it pass. A bug is a defect in merged work that someone saw.

## Record (before the first edit of the fix)

One issue per bug, from the project's defect form; search open defects first, since bugs with one cause share one record. The body follows `templates/bug-record.md`:

- `Class:` product, test, data or environment, with the proof; a guess stays product.
- `Cause:` the design element at fault. `Seen` (the screen, artifact or `path:line` that shows it) or `Inferred` (what would settle it; an inferred cause gets observability first, not a fix).
- `Rule:` each standard or house rule id (`catalog/rules.toml`) the defect breaks, with its evidence; `None: <why>` when none does. Never invent one.
- `Siblings:` the exact search for the same defect elsewhere and its result; siblings are fixed in the same change.
- `Test:` the regression test of the reported item, written before the fix and red on the main branch.
- `Falsifying call:` one real call whose answer would prove the analysis wrong.

A cause is never rewritten: a changed cause is a new comment with `Supersedes:` and what the reading showed.

## Fix

- Subject `fix(#N): ...` with no closing keyword. It changes the file that owns the cause, never a per-instance patch, fallback or wider timeout. A second fix to one place is a design question: write a decision record.
- A reviewer who did not write the fix reads the diff and the record.
- The issue closes only when its `Test:` passes on the fixed main branch.
