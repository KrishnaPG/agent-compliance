# OpenTofu pack, ID rules

Pack `opentofu` for base catalog 1.0.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-03 | A generated password or token is an ephemeral resource written through a write-only attribute, so its value never enters state or a plan file. | OpenTofu documentation: ephemeral resources, write-only attributes | Does any generated secret land in state or a plan file? |
