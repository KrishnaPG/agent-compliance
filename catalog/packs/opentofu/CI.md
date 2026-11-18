# OpenTofu pack, CI rules

Pack `opentofu` for base catalog 1.1.0. Scope: state, locking, plans, secrets in state, destroy protection. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| TF-01 | A held state lock is a fault to report: an apply uses a lock timeout of 0, is the only applier, and never waits a lock out or breaks it automatically. A read-only plan runs without the lock. | OpenTofu documentation "State Locking" | What does a run do when it finds the lock held? |
| TF-02 | A stale lock is released only by the owner's own unlock with the lock id, as a named runbook step, after a person confirmed its holder is gone. | OpenTofu documentation, `force-unlock` command | How is a lock left by a killed run cleared, and who confirms the holder is dead? |
