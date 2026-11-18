# Design compliance overlay (mini project)

Base: 1.0.0 | Packs: postgresql | Date: 2026-11-18 | Sources: a1b2c3d | Verdicts: docs/reviews/compliance/<artifact-name>.md

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| MINI-DS-01 | A customer export is deleted no later than 14 days after its creation. | docs/adr/0012-export-retention.md §2 | Does the design delete every export within 14 days? |
| MINI-DC-01 | Every design names its owning team in an `Owner:` line under the title. | AGENTS.md "Design documents" | Is there an `Owner:` line under the title? |
