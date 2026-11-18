# Billing sync design

A single-tenant internal job copies invoices from the payment provider into the ledger every night.

## Identity

One service account, `deploy-all`, plans, applies, releases and reads; engineers hold a standing deployment role.
The provider API key is static and has no maximum age.
The sync step has a deadline of 30 minutes and runs with an access token that lives 15 minutes.
The token reaches the job only from the secret store, by a declared reference the platform resolves; when the store is unavailable the job does not start, and no other copy exists.
The job passes the token to the provider client on standard input, never in arguments, logs or messages.
The job uses only the `billing.read` grant, which the provider account already holds ("billing.read: granted 2026-09-01").

## Queue and cache

Failed invoices wait in a retry queue held in memory only.
The invoice cache is a rebuildable projection: source the provider API, replay horizon 30 days, rebuild path a full resync, retention 30 days, disposition delete; it never authorizes a deployment.
Receipts and their fingerprints are read from the provider for every invoice; none is computed or filled in by the job.

## Provider behaviour

The design assumes the provider supports idempotency keys on invoice reads; this is to be confirmed later.

## Goals

We will improve reliability and make the sync observable.

## Surface

The job accepts no inbound traffic, signs nothing, resolves nothing across tenants, and the design defines no tests.
