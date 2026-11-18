# Google Cloud pack, OB rules

Pack `gcp` for base catalog 1.0.0. Scope: IAM, service accounts, workload identity federation, audit logging. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| GCP-05 | Admin activity, IAM changes and data access on security-relevant cloud services are audit-logged, and an alert fires on project-ownership, audit-configuration and custom-role changes. | CIS GCP Foundation v4.0.0 2.1, 2.4, 2.5, 2.6; NIST SP 800-53 Rev. 5 AU-2, AU-12 | Which log shows who changed each grant or resource, and what alerts on it? |
| GCP-06 | Audit records cannot be modified or deleted by the principals they record, and their retention is set and locked. | CIS GCP Foundation v4.0.0 2.3; NIST SP 800-53 Rev. 5 AU-9, AU-11 | Can an identity the design creates erase its own trail? |
