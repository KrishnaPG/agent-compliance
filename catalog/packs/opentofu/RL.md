# OpenTofu pack, RL rules

Pack `opentofu` for base catalog 1.0.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-05 | An unattended plan or apply runs with input disabled (`-input=false`), so a missing variable fails instead of prompting. | OpenTofu documentation: `plan`, `apply` | Can any unattended run stop at a prompt? |
