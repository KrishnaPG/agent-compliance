# PostgreSQL pack, HO rules

Pack `postgresql` for base catalog 1.0.0. Scope: shared cluster, per-tenant configuration, replication slots. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| PG-03 | A change-data-capture producer is a singleton fenced by its replication slot; a slot is declared, monitored for retained log growth and dropped with its consumer. | PostgreSQL documentation: replication slots, logical decoding | What fences a second capture process, and what bounds the log a stalled slot retains? |
