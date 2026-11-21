---
name: vetted-decision
description: Decide a design question by judging every option against the compliance catalog and recommending one with no BROKEN rule. Load before any research when a design must be chosen or recommended - adopt, replace, move or delete a mechanism; X or Y; who owns X; a path that failed twice; any option list for the project owner. Do NOT use for which work to do next, a mechanical edit of a settled design, explaining code, running checks, or whether to adopt or pick a third-party tool (vet-oss).
---

# Vetted decision

The answer is its own proof: every verdict names a catalog rule id and its evidence. The rules come from the catalog, never from sources this skill picks.

## Inputs

- **Catalog and overlay:** as `../compliance-review/SKILL.md` "Inputs" loads them (index, in-scope domains, packs, the project overlay).
- **Project bindings:** found as `../compliance-review/SKILL.md` "Inputs" says. They give the tracker, where a decision is recorded, the escalation categories and the evidence environment. No bindings: put the full decision in the reply, say it is unrecorded and give the setup prompt.

**Once per question.** A decision is recorded where the bindings say, headed `Decision: <question>` with the date and commit. Search for that heading first: when one exists, reuse it and re-judge only the rows whose cited inputs (a `path:line`, a catalog rule, an owner's answer) changed since. Unchanged inputs give the same decision.

**Short mode** (another skill asks about one item): reply with the Recommendation section alone, its BROKEN rows and the falsifying call.

**Cost:** read line ranges, never whole documents; about 15 tool calls.

## Steps

1. **Current.** The code path that does it today and the approved clause that governs it, each as `path:line` plus a few words; then the effects any replacement must keep.
2. **Options.** Always: keep the current design; each mechanism native to the owner (inside an adopted owner, lowest rung first, catalog NO-06); delete it. A third-party tool is an option only after `vet-oss` passed it.
3. **Trace, per option.** Each value, secret and record hop by hop: producer, carrier, reader. Per hop: who can see a secret, whose privilege, who owns the fact, what happens on retry, crash and delete. Per termination the option adds, changes or relies on (delete, revoke, disable, prune, offboarding, credit or reversal, cleanup, reset, session, token, grant or membership end): its termination tier, the bound as a number, the native mechanism that meets it, what it keeps (the person's account, links and history; the data under the stated policy) and its place in the child-first release order.
4. **Judge, per option,** by the compliance-review method: scope the domains from `catalog/index.md`, then one row per in-scope rule, `| Rule | Option | HELD/BROKEN/NA | Evidence |`. Evidence is a `path:line` of the project's code or the owner's source, or a real call with the owner's answer. A runtime rule that only documentation supports is UNVERIFIED, never HELD. List only BROKEN, UNVERIFIED and the HELD rows that separate the options; give the count of the rest.
5. **Attack the leading option.** What breaks if it is chosen: consumers, other installations, unattended runs, human steps, recovery (which failure goes unseen, what could be deleted, how it is restored). An option with any runtime, data or access effect that ends, removes or destroys something (not an edit of a document or source file) gets the termination rows in step 4 whatever else is in scope: LC-39 (tier, number, mechanism), LC-40 (a T0 effect checked at the action, after every refusal), LC-41 (native mechanism, measured bound), LC-42 (person and data kept), LC-02 (child-first), LC-43 (rule ids in the code comment), DS-01 and DS-04, with the overlay rows that tighten them; an option to disable or delete an account is judged by LC-42 before ID-05. Each finding is a rule row in step 4.
6. **Falsifying call.** The one real call whose answer would prove the recommendation wrong. Run it and show the owner's answer, never a secret value. Not runnable yet: the recommendation is UNVERIFIED and says so.
7. **Recommendation.** One option with no BROKEN and no UNVERIFIED rule, and one line per rejected option naming the rule ids it broke. When more than one option qualifies, recommend the one with the least waste, compared on the qualifying options only: tokens per run, wall time per run, owner steps (commands a person types, decisions a person makes) and lines of code the project must own, each a number with its source (measured: the run or call; estimated: the basis stated). Show the comparison; when the numbers favour different options, decide in this order: owner steps, then tokens per run, then lines of code the project must own, then wall time (recurring owner effort, then recurring spend, then upkeep, then time). No option qualifies: say so, and name the rule and the redesign that would clear it. A point only the project owner decides (catalog PR-10: conflict between approved documents, new owner, wider privilege, retention, scope; the bindings' categories) is named as such with the recommendation; work continues around it.

## Output

```
Decision: <question> (<date>, <commit>)
Catalog: base <version> + packs <names> + overlay <path>@<commit>
Current: ...
Options: O1 keep ...; O2 ...; O3 delete ...
Trace: <per option>
| Rule | Option | Verdict | Evidence |
Attack: ...
Falsifying call: <call> -> <owner's answer>
Waste: O1 <tokens>, <wall time>, <owner steps>, <lines> (<source of each>); O2 ... (qualifying options only, or "one option qualifies")
Recommendation: <option>; rejected: O2 (CI-09, HO-14), ...
Owner decides: <category: question> or none
```
