---
name: compliance-review
description: Review a design, spec, ADR, implementation plan or diff for compliance against a fixed rule catalog (the ready-made base catalog plus the project's overlay) and return one HELD/BROKEN/NA verdict per rule, so review rounds converge instead of finding new ad-hoc issues. Use for any design, spec, plan or architecture review, a re-review after fixes, or a check that a plan can be followed without decisions. Do NOT use to build or change a catalog (use compliance-catalog).
---

# Compliance review

A review checks the artifact against a fixed set of rules. It does not hunt for whatever it can find: an ad-hoc review always finds something new, while a compliance review converges because the set of BROKEN rules only shrinks.

## Inputs

- **Base catalog:** the `catalog/` directory of this plugin (two directories above this file). Ready to use; never rebuilt by a review. Load in this order, and nothing more: `catalog/index.md` (version, readings, terms, domain and pack lists, scenario index); `catalog/base/<DOMAIN>.md` for each domain in scope; `catalog/base/HS.md` whenever HO is in scope; `catalog/packs/<pack>/<DOMAIN>.md` for the same domains, for each pack the overlay's header (or, without an overlay, the review brief) names, and for a pack-only domain (UI) when the artifact has that surface; `catalog/scenarios.md` when scoping by scenario.
- **Project overlay:** the project's own rules. Default path `docs/agents/design-compliance.md`; a project may name another path in its AGENTS.md or CLAUDE.md. Its header names the base version it was built against and the packs it uses. An overlay row that names a base or pack id under "Tightens" decides in place of that rule. No overlay: review against the base alone, with no pack, and say so.
- **Artifact:** the design, spec, plan or diff, at a fixed commit.

If the overlay's base version differs from this plugin's base version, review anyway and list the base rules added or changed since that version under "Catalog drift".

## Steps

1. **Scope.** Read `catalog/index.md` and list the catalog domains that apply to the artifact (the scenario index names the domains each scenario touches). A domain is out of scope only with a one-line reason. Document, plan and process domains apply to every design and plan.
2. **Review.** For a large catalog, split the in-scope domains across reviewers (at most five in parallel). Each reviewer gets the absolute paths of the index, its domains' base and pack files, the overlay and the artifact, and the brief in `templates/review-brief.md`. A reviewer reads only the catalog rows, the artifact and the code or documents the artifact names; the catalog row is the whole rule.
3. **Verdict per rule.**
   - **HELD:** the artifact satisfies the rule; cite where.
   - **BROKEN:** cite the artifact location and the evidence, and give the fix by the right standard, pattern or reuse of existing code. A runtime rule is BROKEN only with a concrete failing input or reachable state. A document, plan or process rule is BROKEN when a cited location breaks its text.
   - **NA:** one sentence why the rule does not apply.
   Anything that is not a catalog rule goes under "Possible missing rules" for the catalog owner. It is not a design finding and does not fail the review.
4. **Result.** The artifact passes when no in-scope rule is BROKEN. Record the verdict table on the tracking issue or PR, never inside the reviewed document. A verdict is a review reading: it never qualifies a capability and never gates a commit or release by itself.
5. **Fix and re-review.** The author fixes only the BROKEN rules. The re-review checks only the rules that were BROKEN plus the rules whose evidence locations the fix touched.
6. **Plan check.** For an implementation plan, also run the literal-follower dry run (`templates/plan-dry-run.md`): a low-cost model follows the first work lists exactly as written, read-only, and lists every point where it had to guess. Each guess is a BROKEN plan-format rule.

## Output

```
Catalog: base <version> + packs <names> + overlay <path>@<commit> (built against base <version>)
Artifact: <path>@<commit>
Scope: <domains>; out of scope: <domain: reason>
Verdict: PASS | FAIL (<n> BROKEN)
| Rule | Verdict | Artifact location | Evidence | Fix |
Possible missing rules: <list or none>
Catalog drift: <list or none>
```
