# agent-compliance

A Claude Code plugin for reviewing designs, specs and implementation plans for compliance against a fixed rule catalog, so review rounds converge.

- `catalog/`: the ready-to-use base catalog, versioned data. `index.md` (version, readings, domains, packs, scenario index), `base/<DOMAIN>.md` (one file per domain), `packs/<pack>/<DOMAIN>.md` (technology packs a project opts into), `scenarios.md` (generic scenarios with their deciding rules), `CHANGES.md`. A reviewer loads the index and only the in-scope files.
- `skills/compliance-review`: the everyday skill. Reviews an artifact against the base catalog plus the project's overlay; one HELD/BROKEN/NA verdict per rule; re-reviews only what was broken; literal-follower dry run for plans.
- `skills/compliance-catalog`: the rare skill. Builds or rebuilds a project overlay or the base catalog, with an independent weakness audit.
- `templates/`: briefs for reviewers, catalog audits and plan dry runs.

## Install

```
/plugin marketplace add KrishnaPG/agent-compliance
/plugin install agent-compliance@agent-compliance
```

A project keeps its own rules in an overlay file (default `docs/agents/design-compliance.md`) whose header names the base version it was built against and the packs it uses.
