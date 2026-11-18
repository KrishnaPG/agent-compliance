# OpenTofu pack, ID rules

Pack `opentofu` for base catalog 1.1.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-03 | From OpenTofu 1.11, and where the provider offers a write-only attribute, a generated password or token is an ephemeral resource written through that attribute, so its value never enters state or a plan file; otherwise the value is generated outside the root and the root holds only its reference. | OpenTofu documentation: ephemeral resources, write-only attributes | Does any generated secret land in state or a plan file? |
