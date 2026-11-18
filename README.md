# agent-compliance

A Claude Code plugin for reviewing designs, specs and implementation plans for compliance against a fixed rule catalog, so review rounds converge.

- `catalog/`: the ready-to-use base catalog, versioned data. `index.md` (version, readings, domains, packs, scenario index), `base/<DOMAIN>.md` (one file per domain), `packs/<pack>/<DOMAIN>.md` (technology packs a project opts into), `scenarios.md` (generic scenarios with their deciding rules), `CHANGES.md`. A reviewer loads the index and only the in-scope files.
- `skills/compliance-review`: the everyday skill. Reviews an artifact against the base catalog plus the project's overlay; one HELD/BROKEN/NA verdict per rule; re-reviews only what was broken; literal-follower dry run for plans.
- `skills/compliance-catalog`: the rare skill. Builds or rebuilds a project overlay or the base catalog, with an independent weakness audit.
- `skills/vetted-decision`: decides a design question; every option judged against the catalog, the recommendation has no BROKEN rule.
- `skills/vet-oss`: vets a third-party tool from its pinned source against the catalog before it is named.
- `skills/bug-analysis`: the bug record (cause, broken rule ids, siblings, test), `fix(#N):` commits, closure only when the record's test passes.
- `templates/`: briefs for reviewers, catalog audits and plan dry runs; the bug record; the project bindings file.

## Install

```
/plugin marketplace add KrishnaPG/agent-compliance
/plugin install agent-compliance@agent-compliance
```

A project keeps its own rules in an overlay file (default `docs/agents/design-compliance.md`) whose header names the base version it was built against and the packs it uses.

A project names its tracker, ledger, commands and escalation categories in a bindings file (default `docs/agents/compliance-bindings.md`, from `templates/compliance-bindings.md`); the skills read it for anything project-specific.
