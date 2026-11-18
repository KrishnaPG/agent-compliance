---
name: compliance-catalog
description: Build or rebuild a compliance rule catalog: a project's overlay (its own rules beyond the base catalog) or the base catalog itself, then audit it for weakness with a fresh agent that shares no context with the author. Use only when a project has no overlay yet, its own rules changed, a "possible missing rule" was accepted, or an industry standard changed. Normal reviews use compliance-review with the existing catalog and never rebuild.
---

# Compliance catalog

The base catalog (`catalog/` two directories above this file: `index.md`, one `base/<DOMAIN>.md` per domain, `packs/<pack>/<DOMAIN>.md` per technology pack, `scenarios.md`) is the reusable product: industry-standard rules and generic scenarios that hold across projects. A project adds only an overlay with its own rules. Rebuild only when a trigger in the description holds.

## Row format (both catalogs)

`| ID | Rule | Provenance | Test question |`

- **Rule:** the full testable rule in one line: must or never, its numbers (budgets, timeouts, bounds, retention, recovery targets), the exceptions its source allows, and the case it governs. A reviewer judges it from this row alone. Never stricter or weaker than its source.
- **Provenance:** where it comes from (project file + clause, or the external standard + section). Provenance only; the reviewer need not open it.
- **External standards are never copied verbatim.** Each is applied as the catalog's own concise rule that keeps its substance.
- Ids are stable: a changed rule keeps its id; a removed rule's id is not reused.

## Building an overlay

1. Read the project's binding sources: AGENTS.md or CLAUDE.md, coding standards, ADRs, approved specs, and owner rulings recorded in the repository.
2. For each binding must or never: if a base rule already states it, skip it. If the project's version is stricter or adds a number, add an overlay row that names the base id it tightens. Otherwise add a new overlay row.
3. Scenario coverage: list the project's scenarios (start from the base scenario library and add the project's own). Every scenario names the rules that decide it. A scenario with no deciding rule is a gap: add a rule from an industry standard with its provenance, or list it under "Gaps".
4. Source conflicts: where two project sources disagree, the catalog states the newer explicit owner ruling and lists the conflicting lines under "Source conflicts" for the project to clean up.
5. Header: the base version the overlay was built against, the packs it uses, the date, the commit of the sources read, and where review verdicts are recorded (`Verdicts:` a tracking issue or PR, or a file path).
6. **Weakness audit** by a fresh agent that shares no context with the author (`templates/catalog-audit.md`): missing rules, weak or unfalsifiable rules, wrong provenance (external citations fetched where possible), scenarios that cannot be judged, and missing scenarios. Apply the findings, then re-audit only the audit's sections. The catalog is ready when the audit rates it ADEQUATE.

## Updating the base catalog

Same steps, for project-independent rules only. A rule found in several project overlays moves to the base. Bump the base version and add a one-line entry per added or changed id to `catalog/CHANGES.md`, so overlays can see the drift.
