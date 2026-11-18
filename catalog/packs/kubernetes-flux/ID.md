# Kubernetes with Flux pack, ID rules

Pack `kubernetes-flux` for base catalog 1.0.0. Scope: one applier, dependency edges, health, intervals, Jobs, Helm, prune, secrets by External Secrets Operator, admission webhook. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| KF-12 | Where External Secrets Operator supplies Secrets, a Secret reaches the cluster as an `ExternalSecret` resolved from the secret store, health-checked before its readers, so nothing starts on a missing credential; a generated-once Secret is created once (`refreshPolicy: CreatedOnce`, `target.immutable: true`, `creationPolicy: Orphan`) and never refreshed. | External Secrets Operator documentation | By which object does each Secret arrive, and what starts when it is not Ready? |
