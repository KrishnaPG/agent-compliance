# Kubernetes with Flux pack, SC rules

Pack `kubernetes-flux` for base catalog 1.0.0. Scope: one applier, dependency edges, health, intervals, Jobs, Helm, prune, secrets by External Secrets Operator, admission webhook. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| KF-15 | The admission webhook runs at least 2 replicas with a PodDisruptionBudget keeping at least 1 available; the `kube-system` namespace, the reconciler's namespace and its own namespace are excluded from its match. | Kubernetes documentation: Admission Webhook Good Practices (high availability; avoid matching `kube-system`) | Can a webhook outage block the controllers that restore it? |
