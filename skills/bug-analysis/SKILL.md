---
name: bug-analysis
description: Record and fix a defect by its root cause and the catalog rules it broke. Load before any investigation of a defect of any size, with or without a failing test (a bug, error, wrong value, flaky step, failing test or failed release), and before any commit whose subject type is `fix`. Not for new features, redesigns, or prose edits that change no meaning.
---

# Bug analysis

A bug is any defect anyone notices, in any file, however small: wrong behaviour or value, a misleading or missing message, a missing check, a flaky step, a failing test or release. No test need fail or exist. A prose typo that changes no meaning is not a bug.

## Inputs

- **Catalog and overlay:** found as `catalog/method.md` "Inputs" says; only the domains the failing path touches.
- **Project bindings:** found as `catalog/method.md` "Inputs" says: the tracker, the ledger, the commands that draft, post and close a record, the review command, the forms a `Test:` takes. No bindings: one tracker issue per bug by hand; with no tracker, the full record goes in the reply, says it is unrecorded.

## The record

Record a bug in the turn it is found, fixed or not, and before the first edit of a fix (catalog PR-01, PR-09). One issue per bug, its body headed `Analysis: <the defect as a person sees it> (<paths>)`. Search the ledger first: bugs with one cause are one design issue and share one record, each with its own evidence. Each line starts with its label, then its comparable value, then `:` and the detail (`templates/bug-record.md`):

- `Class:` product, test, data or environment, with the proof. Anything but product needs the owner's source, a later approved decision or a measurement; a guess stays product.
- `Cause:` the exact design issue. `Seen`: the operator screen and query, the artifact, or the source `path:line` that shows it. `Inferred`: what was read and which reading would settle it. An inferred cause may be recorded but not fixed: the next work is the observability that makes it seen.
- `Rule: <id> BROKEN: <evidence>` one line per catalog rule the defect broke, judged by the method in `catalog/method.md` (a runtime rule needs the failing input or reachable state; a document or process rule needs the location that breaks its text). `Rule: None: <why>` when no catalog rule covers it; then name the possible missing rule for the catalog owner. Never invent a violation to fill the line. A reported state that an approved rule keeps is no defect: before a surviving person account, identity link or authored record is called a leftover, read LC-42 and the overlay rows that tighten it (a person's account outlives a membership), and record `Rule: None:` with the keeping rule when they hold. Access, grants, sessions or tokens that survive the end past their declared bound are BROKEN under LC-39, LC-41 and ID-05. When the failing path or the fix touches a termination (delete, revoke, disable, prune, offboarding, credit or reversal, cleanup, reset, session, token, grant or membership end), the `Rule:` lines cover LC-39 to LC-43, LC-02, DS-01 and DS-04, each BROKEN or held with its evidence.
- `Siblings:` the exact search for the same defect elsewhere and its result. Siblings are worked as one list with the fix; only a design issue may be deferred.
- `Test:` the test of the reported item, in a form the bindings name. It must pass on the fixed product before the bug closes.
- `Falsifying call:` one real call whose stated answer would prove this analysis wrong.
- `Where:` the owner package or tool; the journey criterion or `none`; how it was found (`test`, `alert`, `walk` or `review`), separated by semicolons.

**A cause is never rewritten.** A changed `Cause:`, `Class:` or verdict is a new `Analysis:` comment on the issue with two more lines, `Supersedes:` the earlier record's URL and `Verdict:` `confirmed`, `partly` or `wrong` with what the reading showed. Only a screen or artifact reading gives a verdict; a test passing after a fix does not prove its cause. A correction that changes no cause is a one-line `Note:` comment.

## The ledger

The ledger is every record on the tracker, read by the bindings' ledger command: one row per record with its class, cause kind, broken rule ids, owner, found-by, fix commits and computed open or closed state. Group by rule id: a rule broken by several records is a design issue to fix at its cause (catalog PR-11), and a rule id that keeps returning after its fixes is a finding about those fixes. Records are read as written, never edited to fit the reader.

## The fix

- The subject is `fix(#N): ...` naming the bug's issue. The message carries no closing keyword (`Fixes`, `Closes`, `Resolves` with `#N`), so reaching the main branch closes nothing. Any other change is not a fix and takes no bug number.
- The fix states how it clears each `Rule:` line and names its Test. It is made in the file that owns the cause, never as a per-instance patch, fallback or widened timeout. A second fix to one place steps back to the design first (`vetted-decision`). A fix that adds or changes a termination states, in the record and in the comment at the code site (LC-43), its termination tier, the bound, the native mechanism and what it keeps; a fix that would delete or disable a person's account, or data beyond the stated policy, is a design decision (`vetted-decision`), never a fix.
- One independent review of the diff, by a reviewer who did not write it (catalog PR-04), also checks the record's lines and the sibling verdicts.
- **Close** only when the record's Test passes on the fixed product, by the bindings' close command; a later run that fails the Test reopens the bug. A release or a merged commit does not prove a fix.
- A bug no fix can close gets a `Closure:` comment naming the record, `Exit:` `stale`, `duplicate`, `data-action` or `test-defect`, and `Evidence:` that resolves (the change that removed it, the surviving record, the reading after the action, the owner's proof).
- Readings taken while fixing are collected and posted as one comment at the end, not one by one.

A subagent brief for a bug names this skill and the path of the bindings.
