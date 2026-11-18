# OpenTofu pack, DS rules

Pack `opentofu` for base catalog 1.0.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-06 | A data-bearing resource (data disk, bucket, key, state bucket) is protected from destroy by the resource's lifecycle setting, so a plan that would destroy it fails. | OpenTofu documentation "Resource Behavior" (`prevent_destroy`) | Can a plan destroy a data-bearing resource without an explicit, reviewed change? |
| TF-07 | State and plan files are encrypted with a managed key. A root that cannot be encrypted (it creates its own key) holds no secret value. The state bucket is versioned. | OpenTofu documentation "State and Plan Encryption" | What sensitive value could a state or plan file reveal? |
