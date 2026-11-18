---
name: compliance-review
description: Review a design, spec, ADR, implementation plan or diff for compliance against a fixed rule catalog (the ready-made base catalog plus the project's overlay) and return one HELD/BROKEN/NA verdict per rule, so review rounds converge instead of finding new ad-hoc issues. Use for any design, spec, plan or architecture review, a re-review after fixes, or a check that a plan can be followed without decisions. Do NOT use to build or change a catalog (use compliance-catalog).
---

# Compliance review

A review checks the artifact against a fixed set of rules. It does not hunt for whatever it can find: an ad-hoc review always finds something new, while a compliance review converges because the set of BROKEN rules only shrinks.

## Inputs

- **Base catalog:** the `catalog/` directory of this plugin (two directories above this file). Ready to use; never rebuilt by a review. Load in this order, and nothing more: `catalog/index.md` (version, readings, terms, domain and pack lists, scenario index); `catalog/base/<DOMAIN>.md` for each domain in scope; `catalog/base/HS.md` whenever HO is in scope; `catalog/packs/<pack>/<DOMAIN>.md` for the same domains, for each pack the overlay's header (or, without an overlay, the review brief) names, and for a pack-only domain (UI) when the artifact has that surface; `catalog/scenarios.md` when scoping by scenario. Read each catalog file at most once per review.
- **Project overlay:** the project's own rules. Default path `docs/agents/design-compliance.md`; a project may name another path in its AGENTS.md or CLAUDE.md. Its header names the base version it was built against and the packs it uses. An overlay row that names a base or pack id under "Tightens" decides in place of that rule. No overlay: review against the base alone, with no pack, and say so.
- **Artifact:** the design, spec, plan or diff, at a fixed commit.
- **Verdict record:** where the project keeps verdicts. The overlay header names it (`Verdicts:` a tracking issue or PR, or a file path); default the file `docs/reviews/compliance/<artifact-name>.md`. It starts with the key line of the Output and holds the verdict table; each row names the artifact anchors (section headings or line ranges) its evidence cites.

If the overlay's base version differs from this plugin's base version, review anyway and list the base rules added or changed since that version under "Catalog drift".

## Steps

1. **Key and lookup.** A full review is costly, so never repeat one. Build the key: artifact path and git blob sha (`git hash-object <file>`, which needs no repository; a sha the request states is used as given), base version (one Grep for `^Version:` in `catalog/index.md`, not a Read), overlay blob sha, pack list, scope (`all`, or the focus). Look the verdict record up once. Same key: return the recorded verdict unchanged with a line `Reused: <record>` and stop; read no catalog file and start no reviewer.
2. **Incremental.** A record for the same artifact path with another key is the starting point; its rows carry over marked `carried from <old key>`, except the rows re-run here. Artifact changed: take the diff from the recorded blob to the new one (`git diff <old> <new>`, or the diff the request gives) and re-run only the rules that were BROKEN, the rules whose anchors the diff touches, and every rule of a domain that a newly added section brings into scope. Catalog changed: re-run only the ids `catalog/CHANGES.md` lists after the recorded base version and the overlay rows the overlay's diff changes. Load only the base domain files of the rules re-run, and a pack file only for a pack rule. No record: full review.
3. **Scope.** Read `catalog/index.md` and list the catalog domains that apply to the artifact (the scenario index names the domains each scenario touches). A domain is out of scope only with a one-line reason. Document, plan and process domains apply to every design and plan. When the request names a part (a section, a component, or a concern such as identity), the scope is only the domains and rules that part touches; every other domain is reported as `not reviewed (out of focus)`, never as HELD.
4. **Preview.** Before loading a domain file print `Plan: <n> rules, files <list>, <n> reviewers, ~<n> tokens` (a file is about its bytes / 4), and after the review `Actual:` in the same form. Loading an unchanged file again or re-checking a carried rule is a defect.
5. **Review.** Reviews run on Sonnet: a catalog row is written to be judged by it, and larger models are for building and auditing the catalog. With fewer than about 100 in-scope rules, review inline with no reviewer subagent. For a larger scope, split the in-scope domains across reviewers (at most five in parallel). Each reviewer gets the absolute paths of the index, its domains' base and pack files, the overlay and the artifact, and the brief in `templates/review-brief.md`. A reviewer reads only the catalog rows, the artifact and the code or documents the artifact names; the catalog row is the whole rule.
6. **Verdict per rule.**
   - **HELD:** the artifact satisfies the rule; cite where.
   - **BROKEN:** cite the artifact location and the evidence, and give the fix by the right standard, pattern or reuse of existing code. A runtime rule is BROKEN only with a concrete failing input or reachable state. A document, plan or process rule is BROKEN when a cited location breaks its text.
   - **NA:** one sentence why the rule does not apply.
   Anything that is not a catalog rule goes under "Possible missing rules" for the catalog owner. It is not a design finding and does not fail the review.
7. **Result.** The artifact passes when no in-scope rule is BROKEN. Record the Output in the verdict record, never inside the reviewed document. A verdict is a review reading: it never qualifies a capability and never gates a commit or release by itself.
8. **Fix and re-review.** The author fixes only the BROKEN rules; the re-review is the incremental run of step 2.
9. **Plan check.** For an implementation plan, also run the literal-follower dry run (`templates/plan-dry-run.md`): a low-cost model follows the first work lists exactly as written, read-only, and lists every point where it had to guess. Each guess is a BROKEN plan-format rule.

## Output

```
Key: <artifact path>@<blob sha> | base <version> | overlay <blob sha or none> | packs <names or none> | scope <all or the focus>
Catalog: base <version> + packs <names> + overlay <path>@<commit> (built against base <version>)
Artifact: <path>@<commit>
Scope: <domains>; out of scope: <domain: reason>
Plan: ... / Actual: ...
Verdict: PASS | FAIL (<n> BROKEN)
| Rule | Verdict | Anchors | Evidence | Fix |
Possible missing rules: <list or none>
Catalog drift: <list or none>
```
