# Export cleanup design

Owner: data-platform on-call

## Purpose

Customers download CSV exports of their orders. Each export is one object in the `exports` bucket.
The nightly cleanup job removes old exports so the bucket stays under 50 GB.

## Storage

One bucket, `exports`, one object per export, keyed by tenant and export id.
This section supersedes the 2025 storage note.

## Retention

Exports are deleted 30 days after creation. The project owner decided on 2026-10-02 (issue #41) that exports are not retained beyond 30 days; each is rebuilt on request from the orders database.

## Access

The job authenticates to the bucket with a service-account key file kept on the host at /etc/exports/key.json.
The key is passed to the job as the command-line argument --key.

## Operations

The job logs each deleted key and raises an alert when a run fails.
