# PL: Platform reconciliation and release

Base catalog 1.0.0. Scope: declared and pulled desired state, immutable releases, manual actions. Each row is the whole rule; judge it from the row alone.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| PL-01 | An operator or break-glass action is one native call that keeps no orchestration state and polls nothing; the platform's access control decides who may run it; a destructive action needs its target's name typed as confirmation. | OpenGitOps v1.0.0 | Is each manual action one call, what authorizes it, and what does it confirm before destroying? |
| PL-02 | Desired state is declared, not scripted; stored versioned and immutable with its history; pulled by the platform's own agent, not pushed by hand; and continuously reconciled by that agent. | OpenGitOps v1.0.0 1, 2, 3, 4 | Is any desired state imperative, mutable in place, or pushed by hand? |
| PL-03 | Build, release and run are separate stages: a release is an immutable pinned commit with its digests, and a running host changes no code or artifact. | Twelve-Factor App V | Can the running system differ from its release without a new release? |
| PL-04 | Nothing optional is health-gated, and nothing a consumer needs is optional. | OpenGitOps v1.0.0 | Which dependencies are optional, and does anything wait on them? |
