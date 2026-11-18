# PostgreSQL pack, CI rules

Pack `postgresql` for base catalog 1.0.0. Scope: shared cluster, per-tenant configuration, replication slots. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| PG-01 | Per-tenant or per-installation client-authentication rules live in separate files of an included directory (`include_dir`, PostgreSQL 16 or later); the writer reads the file-rules view for errors before any reload and applies with `pg_reload_conf()`, never a restart. | PostgreSQL documentation "The pg_hba.conf File", `pg_hba_file_rules`, `pg_reload_conf()` | How does one tenant's rule change without editing the shared file or restarting the server? |
| PG-02 | A shared cluster gives each tool or tenant its own database and owner role behind a pooler; CONNECT on each database is revoked from PUBLIC (which holds it by default) and granted only to its owner role, so no tool can connect to another's database; each logical database has its own migration and backup inventory. | PostgreSQL documentation: roles and privileges | What separates each tenant on the shared cluster? |
