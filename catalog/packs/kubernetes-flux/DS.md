# Kubernetes with Flux pack, DS rules

Pack `kubernetes-flux` for base catalog 1.1.0. Scope: one applier, dependency edges, health, intervals, Jobs, Helm, prune, secrets by External Secrets Operator, admission webhook. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| KF-10 | Prune is on, and disabled by annotation only for data-bearing kinds and what cascades to them (Namespaces, CRDs, volumes and claims, database, storage and stream objects, generated-once secrets, operator and data-chart releases); the render refuses such a kind without the annotation; an admission policy refuses DELETE of a data kind without a named authority; data objects carry the chart's keep policy. | Flux documentation: prune; Kubernetes documentation: ValidatingAdmissionPolicy; Helm documentation: resource policy | Can removing an object from the render, or a hand delete, destroy data? |
