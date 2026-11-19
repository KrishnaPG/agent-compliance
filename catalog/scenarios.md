# Scenarios

Base catalog 1.1.0. Each scenario lists the base rules that decide it, and the pack rules that add to them when the pack is in use. A scenario the artifact touches puts every listed rule in scope; the project overlay adds its own rules and scenarios.

| # | Scenario | Base rules | Pack rules |
|---|---|---|---|
| 1 | First install on an empty machine | LC-01, LC-02, LC-05, LC-06, LC-07, LC-08, LC-16, LC-30, LC-33, RL-05, RL-06, RL-27, ID-14, LC-35, SC-14, CF-04, CF-06, DS-03, DS-12, ID-10, ID-06, RL-10 | KF-04, KF-02, KF-12 |
| 2 | Release whose commit leaves a stage's inputs unchanged | PF-12, PF-02, LC-03, RL-09, SC-05 | KF-05, KF-07 |
| 3 | Release with changes | LC-03, LC-23, LC-24, LC-25, LC-32, NO-20, LC-02, PL-03, PF-12, PF-03, RL-28, SC-05, SC-11, NO-24, NO-25 | TF-04, KF-07 |
| 4 | From-scratch release | LC-02, LC-19, LC-20, LC-16, DS-01, DS-02, DS-07, DS-10, DS-12, DS-09, RL-27, CF-04, RL-05, ID-06 | KF-10 |
| 5 | Release killed, timed out, or host reboot mid-stage | LC-18, LC-21, LC-28, RL-06, RL-07, RL-14, RL-17, HO-17, HO-32, HO-06, DS-10, SC-11, CI-13 | TF-02, KF-06, SD-01 |
| 6 | Re-run after a failed or partial release | RL-25, RL-07, DS-09, HO-07, LC-18, LC-21, LC-34, HO-16, HS-23, DS-10 | KF-06, KF-07 |
| 7 | Two installations releasing concurrently on one shared host | CI-01, CI-02, CI-03, CI-04, CI-05, CI-06, CI-07, CI-08, CI-09, HS-22, HS-24, RL-03, PF-07 | SD-05, SD-03, PG-01, SALT-02, TF-01 |
| 8 | One installation's input missing or unreadable | RL-10, CI-07, HO-26, HO-11, HO-31, ID-06, CF-18, CF-06, OB-11, LC-27, OB-05 |  |
| 9 | Installation retirement or purge | DS-16, DS-13, DS-04, DS-01, LC-02, LC-11, LC-20, ID-05, HS-21 | TF-06, KF-10, NJ-07 |
| 10 | A different setup (other host, cloud project, user, domain) | CF-01, CF-18, CF-03, CF-05, CF-08, CF-09, CF-14, CF-15, PN-05, ID-09 |  |
| 11 | Credential rotation and revocation | ID-12, ID-03, ID-13, ID-04, ID-05, ID-06, LC-35, SC-14 | TF-03, NJ-07, GCP-05, GCP-01, KF-12 |
| 12 | Unattended run with no person present | RL-16, RL-17, RL-26, RL-06, RL-14, ID-11, OB-09 | GCP-01, TF-05, TF-01, SD-01 |
| 13 | Development, verification and production class differences | CF-03, CF-04, RL-27, RL-26, DS-12 | NJ-01 |
| 14 | Critical alert firing | RL-26, RL-19, RL-25, RL-03, RL-04, RL-24, RL-02, RL-29, OB-03, PR-01 |  |
| 15 | Observability backend down or destroyed | OB-09, OB-10, OB-11, OB-07, OB-06, RL-02, RL-04, HS-11 |  |
| 16 | Network partition or loss of the remote-shell connection | HO-17, HO-19, HO-20, HO-06, RL-06, RL-12, HS-16, HS-22, LC-21, HO-40 | SALT-02 |
| 17 | Cloud API 403, 404, 5xx or quota | HO-18, HO-12, HO-07, HO-19, RL-12, RL-18, SC-07, ID-14, HO-17, HO-28 | GCP-05 |
| 18 | Stale state lock | CI-03, CI-01, HS-18, HS-22, CI-13 | TF-01, TF-02 |
| 19 | Owner-only actions (bootstrap apply, access-control deletions) | ID-14, ID-03, ID-11, PL-01, DS-08, PR-10 | GCP-04 |
| 20 | Data-bearing object deletion | DS-01, DS-02, DS-04, DS-07, DS-08, DS-12, DS-13, LC-07, LC-11, LC-20, LC-22, DS-17 | KF-10, TF-06, SALT-03 |
| 21 | Backup and restore | DS-03, DS-12, DS-09, LC-15, LC-16, LC-24, RL-28, HS-20 |  |
| 22 | Image build, sign, verify | SC-01, SC-02, SC-03, SC-04, SC-05, SC-14, ID-12, SC-15, SC-06, SC-07, SC-10, NO-11, SC-11, SC-13, ID-02, PF-05, SC-16, SC-17, SC-20 |  |
| 23 | A bug found mid-work | PR-01, OB-01, PR-09, RL-29, NO-12 |  |
| 24 | A document that states an old rule | DC-01, DC-02, DC-03, DC-04, DC-09, DC-10, PN-04 |  |
| 25 | A plan step that cannot pass | PN-03, PN-16, PR-10, PR-07, PR-08, DC-07, DC-11 |  |
| 26 | Schema, operator or store upgrade | LC-24, LC-25, LC-32, RL-28, RL-22, DS-03, HO-14, NO-07 | KF-09 |
| 27 | Rollback of a bad release | RL-28, SC-15, PL-03, DS-10, LC-24 | KF-09 |
| 28 | Tenant or installation onboarding and change | CF-18, CF-02, CF-16, PF-02, DS-13, CI-12, CI-07, HS-02, HO-16, HO-17, ID-07, PF-13, CI-14 | NJ-07 |
| 29 | Duplicate, out-of-order or poison message | HO-16, HO-08, HO-09, HO-03, HO-18, HO-31, HO-32, HS-19 | NJ-05, NJ-04 |
| 30 | Crash between an effect's commit and its acknowledgement | HO-06, HO-16, HO-17, HO-02, HO-34, HO-09, LC-21, HO-40 |  |
| 31 | Adding a platform package or adopting an OSS tool | NO-05, NO-06, NO-07, SC-08, SC-09, CI-12, PF-13, NO-28, NO-29 | KF-01, KF-02, KF-04 |
| 32 | Shared owner (database, identity provider, ingress) changed for one installation | CI-05, CI-08, CI-09, CI-12, NO-18, LC-13 | PG-01, PG-02, SD-03 |
| 33 | Operator manual repair or break-glass | RL-25, HS-19, HO-33, PL-01, OB-01 | TF-02 |
| 34 | Secret found in a log, argument or state file | ID-01, ID-13, OB-08, ID-05, PR-01 | TF-03, KF-12, TF-07, SALT-04 |
| 35 | Idle platform with zero customers | PF-13, CI-12, RL-11, RL-09 |  |
| 36 | External dependency (code host, registry, provider) unavailable | HO-20, HO-12, RL-12, RL-26, HS-07, CF-14 |  |
| 37 | Replacing an old mechanism with a new one | NO-11, NO-14, NO-26, NO-22, HO-14, DC-02 |  |
| 38 | Tenant data export | HS-10, HS-12, HO-04, HO-15, HO-33, PF-05, LC-26, ID-08, DS-14 |  |
| 39 | Tenant erasure, including copies in projections, telemetry and backups | HS-21, DS-15, DS-04, DS-13, DS-12, LC-36, HS-13, HS-11, CI-14 |  |
| 40 | Cost or budget overrun | PF-01, PF-14, CF-13, HO-12, OB-06 |  |
| 41 | Quota or rate-limit exhaustion (provider, cloud, entitlement) | HO-18, HO-12, HO-20, HO-28, RL-12, CF-14 |  |
| 42 | Clock skew and certificate expiry | HO-21, CF-13, OB-17, RL-09, RL-19 |  |
| 43 | DNS change | CF-17, CF-08, CF-09, LC-35, HS-24, LC-02 |  |
| 44 | Secret store sealed or down | ID-06, LC-16, RL-05, OB-01, ID-10, OB-11 | KF-12 |
| 45 | Disk or inode full | LC-06, RL-11, RL-19, RL-24, DS-12 |  |
| 46 | Dependency version drift (owner tag bump, base image bump) | SC-08, SC-06, LC-25, NO-07, RL-22, NO-29 |  |
| 47 | Zone, region or host loss | LC-15, LC-16, DS-12, CF-14, HS-16 |  |
| 48 | Human error in a record | CF-18, CF-16, NO-23, DS-13, PR-03 |  |
| 49 | Concurrent edits of one record | CF-16, CI-05, HO-09 |  |
| 50 | Change-data-capture replay or backfill | HS-20, HO-02, HO-33, LC-28, HO-16 | NJ-06, NJ-05, PG-03 |
| 51 | Observability cardinality explosion | OB-16, OB-02, OB-07, LC-26, PF-06 |  |
| 52 | Cross-tenant read attempt | ID-08, ID-07, HO-05, CI-12, ID-15, CI-14 | NJ-03, PG-02 |
| 53 | Admission webhook outage | SC-12, SC-14 | KF-15 |
| 54 | Signing key or registry loss | SC-06, SC-10, SC-11, SC-15, SC-18, ID-02, ID-13, DS-03, LC-16 |  |
| 55 | An approval pause expires | HS-09, RL-20, RL-14 |  |
| 56 | Browser push-channel loss | HS-15 | RX-02, RX-05 |
| 57 | Operator or resource-schema upgrade | LC-24, RL-28, LC-25, RL-22 | KF-09, KF-04, KF-02 |
| 58 | Commissioning the first administrator | LC-30, ID-11, ID-14 |  |
| 59 | Partial apply of a release | CI-10, LC-18, RL-07, RL-14 | KF-02, KF-03, KF-07 |
| 60 | Inbound webhook from a provider | HS-05, HO-06, HO-11, HO-16, ID-15 |  |
| 61 | Interactive user command and synchronous read | HS-03, HS-04, HO-19, HO-20, ID-15 |  |
| 62 | Notification to a person | HS-08, HO-16 |  |
| 63 | New integration edge designed | HO-01, HO-23, HO-24, HO-25, HO-36, HO-37, NO-15, RL-23, HO-40, ID-15 |  |
