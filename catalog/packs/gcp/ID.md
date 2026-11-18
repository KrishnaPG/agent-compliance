# Google Cloud pack, ID rules

Pack `gcp` for base catalog 1.0.0. Scope: IAM, service accounts, workload identity federation, audit logging. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| GCP-01 | A workload authenticates by its attached service account or by workload identity federation. No user-managed service account key is created, downloaded or stored. | CIS GCP Foundation v4.0.0 1.4; Google Cloud IAM "Best practices for managing service account keys" | Does any step need a downloaded key file? |
| GCP-02 | A federated identity is admitted by a provider with an attribute condition, mapped on attributes the workload cannot change (instance id, subject), and the grant names that one subject, never the whole pool. | Google Cloud IAM "Best practices for using workload identity federation" | What exactly may assume each federated identity? |
| GCP-03 | No VM or job runs as the default Compute service account, with full-API access scopes, or with the Editor role; each workload has its own single-purpose account. | CIS GCP Foundation v4.0.0 4.1, 4.2; Google Cloud IAM "Best practices for using service accounts securely" | Which account does each VM and job run as, and what else shares it? |
| GCP-04 | The right to impersonate or mint tokens is granted on the specific service account, never project-wide, and one person never holds both the administration and the use of the same account. | CIS GCP Foundation v4.0.0 1.6, 1.8; NIST SP 800-53 Rev. 5 AC-5 | Who may impersonate each account, and at which resource level is that granted? |
