# Compliance catalog

Version: 1.0.0

The fixed rule set a design, spec, decision record or implementation plan is reviewed against. A review records one reading per rule, so review rounds converge.

## Loading

1. This index.
2. `base/<DOMAIN>.md` for each domain in scope (DC, PN and PR apply to every design and plan; HS is loaded whenever HO is).
3. `packs/<pack>/<DOMAIN>.md` for the same domains, for each pack the project overlay's header (or, without an overlay, the review brief) names; a pack-only domain (UI) is in scope when the artifact has that surface.
4. The project overlay. An overlay row may tighten a base or pack rule; then the overlay row decides.
5. `scenarios.md` when scoping by scenario.

## Readings

- `HELD`: the artifact location that satisfies the rule.
- `BROKEN`: the rule id, the artifact location, the failing input, and the fix by the right standard, pattern or reused code. For a runtime domain (every domain but DC, PN, PR) the failing input is the concrete input or reachable state that gives a wrong product, data, money or recovery outcome. For DC, PN and PR the location that breaks the rule's text is enough.
- `NA`: one sentence why the rule has no surface. A whole domain with no surface is `NA` with one sentence.
- A requirement the reviewer infers and no row states is never `BROKEN`; it goes under `Possible missing rules` for the catalog owner.
- The artifact passes when no rule is `BROKEN`. A re-review checks only the rules that were `BROKEN` and the rules whose evidence the fix touched.
- A reading is a review record. It never qualifies a capability and never gates a commit or release.
- A provenance starting with "Convention:" marks a rule of this catalog that no public standard states.

## Terms

| Term | Meaning |
|---|---|
| Owner | the one tool or service that commits a fact |
| Project owner | the person accountable for the project's decisions and approvals |
| Hand-off | a fact, command or obligation that leaves one owner so another acts on it |
| Remote call | any network interaction across a process boundary, a remote shell command included |
| L0-L6 | lifecycle levels: L0 deployment record, L1 substrate, L2 durable authorities, L3 immutable configuration, L4 services, L5 operations, L6 durable results (defined in `base/LC.md`) |
| Install path | whatever builds an installation: a package, job, seed, operator resource or infrastructure-as-code root |
| Installation, class | one deployed instance of the platform; its class is development, verification or production |
| Capsule | the versioned state record of one persistent service |
| Named boundary | a recorded, project-owner-approved statement of what the platform does not do |
| Converge | one run of the configuration-management or reconciliation tool that brings a host or installation to its declared state |
| Profile | a declared deployment or integration variant (for example single-node, durable, rebuildable) with its loss, freshness and recovery bounds |
| Manifest | the one generated list of artifact names and digests a release pins |
| Gate | a check whose refusal stops a step, commit or release |
| Journey | one end-to-end user or business flow, from its entry to the owner's terminal fact |
| Pivot | the commit of a process after which it can no longer be compensated |
| Native rung | the level of mechanism used inside an adopted owner: 0 delete, 1 the owner's declarative artifact, 2 the owner's CLI or importer, 3 one call of its public API (`base/NO.md`, NO-06) |
| DLQ | dead-letter channel |
| Real-flow evidence | a run through the real staged services by their public entry points |
| Release smoke | the short end-to-end check a release runs after it applies |
| Memo | the stored key that lets an unchanged step be skipped |
| Release node | the one host that builds, signs and releases |
| Typed authority | the one schema-checked source that supplies URLs, ports and paths |
| Duty identity | the identity of one automated duty (plan, apply, release, read) |
| Adapter | our integration component in front of a backing store or provider |
| Cell | an independently failing deployment unit (site, region, environment) |
| Envelope | the message metadata outside the payload |
| IaC | infrastructure as code |

## Domains

| Domain | File | Rules | Scope |
|---|---|---|---|
| LC Lifecycle and ownership | `base/LC.md` | 38 | levels, parent-first acquisition, child-first release, crash recovery, one owner per fact, lineage |
| HO Hand-offs and remote calls | `base/HO.md` | 39 | messaging between owners, acknowledgement, idempotency, retries, deadlines, dead letters, sagas, reconciliation |
| HS Hand-off scenarios | `base/HS.md` | 24 | one row per kind of hand-off (event, command, webhook, bulk transfer, projection, repair, deletion, control plane) |
| RL Reliability and recovery | `base/RL.md` | 29 | detect, remediate, verify, escalate; deadlines; no timers; idempotent re-runs; rollback; unattended runs |
| ID Identity and secrets | `base/ID.md` | 14 | secret custody and transport, least privilege, rotation, revocation, tenant isolation of access |
| SC Supply chain | `base/SC.md` | 20 | build once, digests, signing, verification, admission, provenance, pinned dependencies |
| OB Observability | `base/OB.md` | 18 | operator screens, alerts, telemetry bounds, audit records, unknown is not healthy |
| PF Performance and footprint | `base/PF.md` | 15 | budgets with numbers, dirty-only work, parallelism, zero-copy, bounded settings |
| CI Concurrency and isolation | `base/CI.md` | 13 | serializers, locks, single writer, bulkheads between installations and tenants |
| CF Configuration and portability | `base/CF.md` | 19 | no hardcoded setup, one record, class parity, zero remembrance, named boundaries |
| NO Native owners and least code | `base/NO.md` | 27 | use the owner directly, OSS before code, lowest native rung, delete replaced wiring, no over-engineering |
| PL Platform reconciliation and release | `base/PL.md` | 4 | declared and pulled desired state, immutable releases, manual actions |
| DS Data safety and retention | `base/DS.md` | 17 | no deletion without backup or decision, recovery tiers, deletion eligibility, projections, erasure |
| DC Documents | `base/DC.md` | 12 | current-rule documents, one home per rule, conflicts named, no assumed capability |
| PN Plans | `base/PN.md` | 19 | step format a junior can follow, gates, traceability, real-flow evidence, rollback order |
| PR Process | `base/PR.md` | 13 | defect records, independent review, forward-only history, tests kept strict |
| UI Web frontend | (packs only) | 0 | browser clients; rules live in the frontend pack the overlay names |

## Packs

| Pack | Files | Rules | Scope |
|---|---|---|---|
| `gcp` (GCP) | `packs/gcp/ID.md` (service accounts, federation); `packs/gcp/OB.md` (audit logs) | 6 | IAM, service accounts, workload identity federation, audit logging |
| `opentofu` (TF) | `packs/opentofu/CI.md` (state lock); `packs/opentofu/ID.md` (secrets out of state); `packs/opentofu/PL.md` (plan then apply); `packs/opentofu/RL.md` (non-interactive runs); `packs/opentofu/DS.md` (destroy protection, state encryption) | 7 | state, locking, plans, secrets in state, destroy protection |
| `nats-jetstream` (NJ) | `packs/nats-jetstream/HO.md` (streams, consumers, ids, users, dead letters) | 8 | streams, consumers, message ids, users and accounts, dead letters |
| `kubernetes-flux` (KF) | `packs/kubernetes-flux/PL.md` (applier, dependencies, health, intervals, wake-ups, Helm, substitution); `packs/kubernetes-flux/RL.md` (Jobs, failure alerts); `packs/kubernetes-flux/DS.md` (prune); `packs/kubernetes-flux/ID.md` (secrets); `packs/kubernetes-flux/SC.md` (admission webhook) | 16 | one applier, dependency edges, health, intervals, Jobs, Helm, prune, secrets by External Secrets Operator, admission webhook |
| `react` (RX) | `packs/react/UI.md` (all rows) | 7 | request data, push channels, render flow, modularity |
| `postgresql` (PG) | `packs/postgresql/CI.md` (authentication includes, shared cluster); `packs/postgresql/HO.md` (replication slots) | 3 | shared cluster, per-tenant configuration, replication slots |
| `systemd` (SD) | `packs/systemd/RL.md` (timeouts, ordering, timers); `packs/systemd/CI.md` (drop-ins, one instance) | 5 | unit timeouts and results, ordering, drop-ins, timers |
| `salt` (SALT) | `packs/salt/RL.md` (requisites); `packs/salt/CI.md` (concurrent runs); `packs/salt/DS.md` (cleaned directories); `packs/salt/ID.md` (secrets) | 4 | requisites, concurrent runs, managed directories, secrets at render |

## Scenario index

Deciding rule ids are in `scenarios.md`.

| # | Scenario | Domains |
|---|---|---|
| 1 | First install on an empty machine | LC, RL, ID, SC, CF, DS |
| 2 | No-change release | LC, RL, SC, PF |
| 3 | Release with changes | LC, RL, SC, PF, NO, PL |
| 4 | From-scratch release | LC, RL, ID, CF, DS |
| 5 | Release killed, timed out, or host reboot mid-stage | LC, HO, RL, SC, CI, DS |
| 6 | Re-run after a failed or partial release | LC, HO, HS, RL, DS |
| 7 | Two installations releasing concurrently on one shared host | HS, RL, PF, CI |
| 8 | One installation's input missing or unreadable | LC, HO, RL, ID, OB, CI, CF |
| 9 | Installation retirement or purge | LC, HS, ID, DS |
| 10 | A different setup (other host, cloud project, user, domain) | ID, CF, PN |
| 11 | Credential rotation and revocation | LC, ID, SC |
| 12 | Unattended run with no person present | RL, ID, OB |
| 13 | Development, verification and production class differences | RL, CF, DS |
| 14 | Critical alert firing | RL, OB, PR |
| 15 | Observability backend down or destroyed | HS, RL, OB |
| 16 | Network partition or loss of the remote-shell connection | LC, HO, HS, RL |
| 17 | Cloud API 403, 404, 5xx or quota | HO, RL, ID, SC |
| 18 | Stale state lock | HS, CI |
| 19 | Owner-only actions (bootstrap apply, access-control deletions) | ID, PL, DS, PR |
| 20 | Data-bearing object deletion | LC, DS |
| 21 | Backup and restore | LC, HS, RL, DS |
| 22 | Image build, sign, verify | ID, SC, PF, NO |
| 23 | A bug found mid-work | RL, OB, NO, PR |
| 24 | A document that states an old rule | DC, PN |
| 25 | A plan step that cannot pass | DC, PN, PR |
| 26 | Schema, operator or store upgrade | LC, HO, RL, NO, DS |
| 27 | Rollback of a bad release | LC, RL, SC, PL, DS |
| 28 | Tenant or installation onboarding and change | HO, HS, ID, PF, CI, CF, DS |
| 29 | Duplicate, out-of-order or poison message | HO, HS |
| 30 | Crash between an effect's commit and its acknowledgement | LC, HO |
| 31 | Adding a platform package or adopting an OSS tool | SC, PF, CI, NO |
| 32 | Shared owner (database, identity provider, ingress) changed for one installation | LC, CI, NO |
| 33 | Operator manual repair or break-glass | HO, HS, RL, OB, PL |
| 34 | Secret found in a log, argument or state file | ID, OB, PR |
| 35 | Idle platform with zero customers | RL, PF, CI |
| 36 | External dependency (code host, registry, provider) unavailable | HO, HS, RL, CF |
| 37 | Replacing an old mechanism with a new one | HO, NO, DC |
| 38 | Tenant data export | LC, HO, HS, ID, PF, DS |
| 39 | Tenant erasure, including copies in projections, telemetry and backups | LC, HS, DS |
| 40 | Cost or budget overrun | HO, OB, PF, CF |
| 41 | Quota or rate-limit exhaustion (provider, cloud, entitlement) | HO, RL, CF |
| 42 | Clock skew and certificate expiry | HO, RL, OB, CF |
| 43 | DNS change | LC, HS, CF |
| 44 | Secret store sealed or down | LC, RL, ID, OB |
| 45 | Disk or inode full | LC, RL, DS |
| 46 | Dependency version drift (owner tag bump, base image bump) | LC, RL, SC, NO |
| 47 | Zone, region or host loss | LC, HS, CF, DS |
| 48 | Human error in a record | CF, NO, DS, PR |
| 49 | Concurrent edits of one record | HO, CI, CF |
| 50 | Change-data-capture replay or backfill | LC, HO, HS |
| 51 | Observability cardinality explosion | LC, OB, PF |
| 52 | Cross-tenant read attempt | HO, ID, CI |
| 53 | Admission webhook outage | SC |
| 54 | Signing key or registry loss | LC, ID, SC, DS |
| 55 | An approval pause expires | HS, RL |
| 56 | Browser push-channel loss | HS |
| 57 | Operator or resource-schema upgrade | LC, RL |
| 58 | Commissioning the first administrator | LC, ID |
| 59 | Partial apply of a release | LC, RL, CI |
| 60 | Inbound webhook from a provider | HO, HS |
| 61 | Interactive user command and synchronous read | HO, HS |
| 62 | Notification to a person | HO, HS |
| 63 | New integration edge designed | HO, RL, NO |
