---
name: vetted-decision
description: Choose a design by writing its options as a decision record that a fresh judge scores. Load before research when a mechanism must be adopted, replaced, moved or deleted, X or Y, or who owns X. Not for what to do next, a settled design's edits, or picking a package.
---

# Vetted decision

You propose; a separate agent judges (nobody grades their own work).

1. **Search first.** A record on the same question in the project's decision records whose cited `path:line`s are unchanged is the answer; reuse it.
2. **Write the record** as MADR 4.0, `NNNN-<slug>.md` in the decision records folder, front matter `status: proposed`, `date`, `deciders`:
   - *Context*: the code path that does it today and the clause that governs it, each as `path:line`.
   - *Decision Drivers*: the measurable targets (ids) and the rule ids (standards and house rules in `catalog/rules.toml`) the choice must meet.
   - *Considered Options*, labelled O1..On: always keep the current design, the mechanism native to the current owner, and delete it; a package only after its `bh vet` facts. Per option, each value and record hop by hop (producer, carrier, reader) and what happens on retry, crash and delete.
   - No *Decision Outcome* yet.
3. **Judge:** run `bh decide <record>`. A fresh `claude -p` job scores each option per driver and rule (`pass`, `fail`, `unknown`), recommends one, and lists objections and falsifying calls. It never sees your preference.
4. **Record the outcome:** add *Decision Outcome* with the judge's `recommended` option, its objections and falsifying calls (each becomes an acceptance target), and the result's job id. Disagreeing is an objection of yours under it, never an edit of the verdicts. A point only the owner decides (new owner, wider privilege, retention, scope) stays `status: proposed` and is named as such.
