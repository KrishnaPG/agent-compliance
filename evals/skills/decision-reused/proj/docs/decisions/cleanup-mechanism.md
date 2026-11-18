Decision: Should the nightly cleanup cron be replaced with the bucket's own lifecycle rule? (2026-11-10, a1b2c3d)
Catalog: base 1.1.0 + packs none + overlay none
Current: src/cleanup.py:3 lists the bucket and removes objects older than 30 days; it must keep "no export older than 30 days".
Options: O1 keep the cron job; O2 the bucket's lifecycle rule (native to the bucket owner); O3 delete the mechanism
Trace: O1 cron -> gsutil -> bucket; O2 bucket applies the rule itself; O3 nothing removes exports
| Rule | Option | Verdict | Evidence |
|---|---|---|---|
| NO-06 | O1 | BROKEN | src/cleanup.py:3 re-implements an expiry the bucket owner provides natively |
| NO-06 | O2 | HELD | infra/bucket.tf:4 lifecycle_rule age = 30, action Delete |
| PF-01 | O3 | BROKEN | no bound on bucket growth once nothing removes exports |
Other in-scope rules: 41 HELD or NA for every option.
Attack: O2 removes the per-key log line of the cron job; the bucket's own access log records each lifecycle delete.
Falsifying call: `gsutil lifecycle get gs://exports` -> {"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}
Recommendation: O2; rejected: O1 (NO-06), O3 (PF-01)
Owner decides: none
