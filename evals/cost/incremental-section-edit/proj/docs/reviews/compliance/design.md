Key: docs/design.md@60fed050f25e | base 1.0.0 | overlay f2ba8695ef26 | packs postgresql | scope all
Catalog: base 1.0.0 + packs postgresql + overlay docs/agents/design-compliance.md (built against base 1.0.0)
Artifact: docs/design.md
Scope: DC, DS, PN, PR; out of scope: every other domain: no surface in this design
Verdict: FAIL (2 BROKEN)
| Rule | Verdict | Anchors | Evidence | Fix |
|---|---|---|---|---|
| DC-01 | HELD | whole document | no line breaks the rule | - |
| DC-02 | NA | - | no such surface in this design | - |
| DC-03 | BROKEN | Storage | "This section supersedes the 2025 storage note" | delete the sentence; provenance goes in the commit message |
| DC-04 | NA | - | no such surface in this design | - |
| DC-05 | HELD | whole document | no line breaks the rule | - |
| DC-06 | NA | - | no such surface in this design | - |
| DC-07 | NA | - | no such surface in this design | - |
| DC-08 | NA | - | no such surface in this design | - |
| DC-09 | NA | - | no such surface in this design | - |
| DC-10 | NA | - | no such surface in this design | - |
| DC-11 | NA | - | no such surface in this design | - |
| DC-12 | HELD | whole document | no line breaks the rule | - |
| DS-01 | BROKEN | Retention | bucket objects deleted with no backup and no recorded owner decision | record the project-owner retention decision or add a restore-tested backup |
| DS-02 | NA | - | no such surface in this design | - |
| DS-03 | NA | - | no such surface in this design | - |
| DS-04 | HELD | Retention | deletion is by age of the export only; no retained record references an export | - |
| DS-05 | NA | - | no such surface in this design | - |
| DS-06 | NA | - | no such surface in this design | - |
| DS-07 | NA | - | no such surface in this design | - |
| DS-08 | HELD | Purpose; Operations | nightly job logs each deleted key and alerts on failure | - |
| DS-09 | NA | - | no such surface in this design | - |
| DS-10 | NA | - | no such surface in this design | - |
| DS-11 | NA | - | no such surface in this design | - |
| DS-12 | NA | - | no such surface in this design | - |
| DS-13 | HELD | Retention | deletion follows age, never a cancellation | - |
| DS-14 | NA | - | no such surface in this design | - |
| DS-15 | NA | - | no such surface in this design | - |
| DS-16 | NA | - | no such surface in this design | - |
| DS-17 | NA | - | no such surface in this design | - |
| MINI-DC-01 | HELD | title block | `Owner: data-platform on-call` | - |
| MINI-DS-01 | HELD | Retention | exports are deleted at 30 days | - |
| PN (all 19) | NA | - | the artifact is a design, not a plan | - |
| PR (all 13) | NA | - | no process surface in this design | - |
Possible missing rules: none
Catalog drift: none
