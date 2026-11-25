# Lookup and judging method

The one place that says how the catalog is found and how a rule is judged. The skills and the harness jobs that judge against the catalog read this file; none of them copies it.

## Inputs

- **Base catalog:** this `catalog/` directory. Load in this order, and nothing more: `index.md` (version, readings, terms, domain and pack lists, scenario index); `base/<DOMAIN>.md` for each domain in scope; `base/HS.md` whenever HO is in scope; `packs/<pack>/<DOMAIN>.md` for the same domains, for each pack the overlay's header (or, without an overlay, the request) names, and for a pack-only domain (UI) when the artifact has that surface; `scenarios.md` when scoping by scenario. Read each catalog file at most once.
- **Project bindings:** the file the project's AGENTS.md or CLAUDE.md names as its compliance bindings; failing that, `docs/agents/bindings.md`. The bindings name the overlay, the tracker, where records are posted, the clone directory, the evidence environment and the escalation categories; a path or command is read from them, never assumed. No bindings: do the work, put the result in the reply and say it is unrecorded.
- **Project overlay:** the project's own rules, at the bindings' Overlay row; failing that, `docs/agents/design-compliance.md`. Its header names the base version it was built against and the packs it uses. An overlay row that names a base or pack id under "Tightens" decides in place of that rule. No overlay: judge against the base alone, with no pack, and say so.
- **Artifact:** the design, spec, plan, option or diff, at a fixed commit.

If the overlay's base version differs from this catalog's, judge anyway and list the base rules added or changed since (`git diff <tag of that version> -- catalog`, lines in `CHANGES.md`) as catalog drift.

## Scope

Read `index.md` and list the domains that apply to the artifact (the scenario index names the domains each scenario touches). A domain is out of scope only with a one-line reason. Document, plan and process domains apply to every design and plan.

Life and death are judged together: an artifact that acquires a resource, or has any runtime, data or access effect that ends, removes or destroys something (not an edit of a document or source file), has LC and DS in scope: the level rows at each acquisition and the termination rows (LC-39 to LC-43, with the overlay rows that tighten them) at each termination.

When the request names a part (a section, a component, a concern such as identity), the scope is the domains and rules that part touches; every other domain is reported as `not reviewed (out of focus)`, never as HELD.

## Verdict per rule

One row per in-scope rule: `| Rule | Verdict | Anchors | Evidence | Fix |`.

- **HELD:** the artifact satisfies the rule; cite where.
- **BROKEN:** cite the artifact location and the evidence, and give the fix by the right standard, pattern or reuse of existing code. A runtime rule is BROKEN only with a concrete failing input or reachable state. A document, plan or process rule is BROKEN when a cited location breaks its text. A termination the artifact adds or changes is BROKEN under LC-39 when no tier, number and native mechanism is stated for it, under LC-40 when a T0 effect is not checked at the action, under LC-42 when it removes the person or data beyond the stated policy, under LC-41 and ID-05 when access still works after its declared bound, under LC-02 when its release is not child-first, and under LC-43 when the code site lacks the rule ids in its comment.
- **NA:** one sentence why the rule does not apply.

Anything that is not a catalog rule goes under "Possible missing rules" for the catalog owner; it is not a finding about the artifact. A verdict is a reading of the artifact: it never qualifies a capability and never gates a commit or release by itself.

Models: a catalog row is written to be judged by Sonnet. With fewer than about 100 in-scope rules, judge inline; for a larger scope split the domains across reviewers (at most five in parallel), each given the absolute paths of the index, its domains' files, the overlay and the artifact.
