# agent-compliance

A Claude Code plugin for reviewing designs, specs and implementation plans for compliance against a fixed rule catalog, so review rounds converge.

- `catalog/base.md`: the ready-to-use base catalog (industry-standard rules and generic scenarios). Versioned data.
- `skills/compliance-review`: the everyday skill. Reviews an artifact against the base catalog plus the project's overlay; one HELD/BROKEN/NA verdict per rule; re-reviews only what was broken; literal-follower dry run for plans.
- `skills/compliance-catalog`: the rare skill. Builds or rebuilds a project overlay or the base catalog, with an independent weakness audit.
- `templates/`: briefs for reviewers, catalog audits and plan dry runs.

## Install

```
/plugin marketplace add KrishnaPG/agent-compliance
/plugin install agent-compliance@agent-compliance
```

A project keeps its own rules in an overlay file (default `docs/agents/design-compliance.md`) whose header names the base version it was built against.
