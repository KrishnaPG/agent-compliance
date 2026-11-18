# Kubernetes with Flux pack, RL rules

Pack `kubernetes-flux` for base catalog 1.0.0. Scope: one applier, dependency edges, health, intervals, Jobs, Helm, prune, secrets by External Secrets Operator, admission webhook. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| KF-06 | A Job keeps the Kubernetes default `backoffLimit` (6) as its one retry owner and carries `activeDeadlineSeconds`; `restartPolicy: OnFailure` is never used as a retry. A Job that is a completion marker has no `ttlSecondsAfterFinished` and is never reaped; a changed Job spec is recreated by Flux's force annotation; a Complete Job never re-runs. | Kubernetes documentation: Jobs; Flux documentation: `kustomize.toolkit.fluxcd.io/force` | How is each Job bounded, retried, kept and re-run? |
| KF-13 | Failures are detected by one generic alert rule over the Ready condition of every Kustomization plus the monitoring stack's default rules; a per-symptom rule exists only for what no Ready condition shows. | Flux documentation: Monitoring, Metrics (`gotk_resource_info`); kube-prometheus-stack default rules | Which failure of the design does no Ready condition or default rule show? |
