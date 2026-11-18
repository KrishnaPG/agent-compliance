# Tenant reports database design

## Tier

Tier: standard. RPO 1 hour, RTO 4 hours.

## Database

All tenants share one PostgreSQL 16 database, `reports`, and connect through the one role `app`.
Per-tenant client-authentication rules live in separate files under `include_dir`; the writer reads
`pg_hba_file_rules` for errors before any reload and applies with `pg_reload_conf()`, never a restart.
This design supersedes the reports design v1.

## Secrets

The database password is copied by hand into `/etc/reports/env` on each host.
The worker receives it as the command-line argument `--db-password`.
When the password is re-issued, the store emits an event and the worker reloads it at once; there is no periodic refresh.
Revocation removes the credential from the worker first, then drops the database role.
The export salt is generated once, created with create-if-missing behind a guard read; when reading it fails the worker stops and never regenerates it.

## Backup

A native `pg_basebackup` runs every 24 hours. An alert fires when the newest backup is older than the RPO, and a restore drill into an isolated target runs monthly.

## Tenant cancellation

When a tenant cancels its subscription, the worker drops that tenant's tables the same night. No backup of them is taken first and no owner decision on retention is recorded.

## Cleanup and reset

The cleanup job removes at most 100 report files per run and stops for an operator's confirmation above that.
`reports reset --installation <id>` is explicit and idempotent, is scoped to one installation, prints its target before changing anything, and asks for confirmation before a durable reset.

## Surface

The worker is a batch job: it accepts no inbound traffic, signs nothing, and the design defines no tests.
