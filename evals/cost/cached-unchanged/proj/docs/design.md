# Export cleanup design

Owner: data-platform on-call

## Purpose

Customers download CSV exports of their orders. Each export is one object in the `exports` bucket.
The nightly cleanup job removes old exports so the bucket stays under 50 GB.

## Storage

One bucket, `exports`, one object per export, keyed by tenant and export id.
This section supersedes the 2025 storage note.

## Retention

Exports older than 30 days are deleted by the nightly job. No backup of the bucket exists and no retention decision is recorded.

## Access

The job authenticates to the bucket with a service-account key file kept on the host at /etc/exports/key.json.
The key is passed to the job as the command-line argument --key.

## Operations

The job logs each deleted key and raises an alert when a run fails.
