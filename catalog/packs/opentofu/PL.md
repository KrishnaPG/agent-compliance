# OpenTofu pack, PL rules

Pack `opentofu` for base catalog 1.0.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-04 | Each root has one applier, which applies the plan file produced in the same run; no plan is reused across runs, and the tool's stale-plan refusal is the guard between plan and apply. | OpenTofu documentation: `plan -out`, `apply` | Who applies each root, and is any plan reused across runs? |
