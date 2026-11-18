"""Writes the trigger, disambiguation and no-trigger cases. Run after changing a prompt here."""
import os,shutil
E=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REV,CAT,VD,OSS,BUG='compliance-review','compliance-catalog','vetted-decision','vet-oss','bug-analysis'
ALL=[REV,CAT,VD,OSS,BUG]
def g(skill,lo,hi=None):
    return f"---\ntype: tool_used\ntool: Skill\ninput_match: '{skill}'\nmin: {lo}\n"+(f"max: {hi}\n" if hi is not None else "")+"arm: both\n---\n"
def case(group,name,prompt,want,ungraded=()):
    d=f"{E}/{group}/{name}"; shutil.rmtree(d,ignore_errors=True); os.makedirs(d+'/graders')
    open(d+'/prompt.md','w').write(f"---\ntags: [trigger, {group}]\nmodel: sonnet\nmax_turns: 2\nallowed_tools: [Skill]\n---\n{prompt}\n")
    for sk in ALL:
        if sk==want: open(f"{d}/graders/{sk}-fires.md",'w').write(g(sk,1))
        elif sk not in ungraded: open(f"{d}/graders/{sk}-silent.md",'w').write(g(sk,0,0))
P=[
('trigger-review','design-1',"Review docs/design/export-cleanup.md for compliance against our catalog before I send it for approval.",REV),
('trigger-review','design-2',"Is docs/design/export-cleanup.md okay by our standards? Go through it rule by rule and tell me which rules it breaks.",REV),
('trigger-review','rereview-1',"I fixed the two BROKEN rules from the last compliance review of docs/design/export-cleanup.md. Re-review it.",REV),
('trigger-review','rereview-2',"The findings from yesterday's design check on docs/specs/billing.md are fixed in commit 4e1f9aa. Check it again, only what failed.",REV),
('trigger-review','plan-1',"Run the compliance plan check on docs/plans/migrate-queue.md: can it be followed without decisions?",REV),
('trigger-review','plan-2',"Could a junior engineer follow docs/plans/migrate-queue.md step by step without having to guess anything? Verify that before we hand it over.",REV),
('trigger-catalog','overlay-1',"This repo has no compliance overlay yet. Build one from AGENTS.md and the ADRs.",CAT),
('trigger-catalog','overlay-2',"We are onboarding a new project to the design-review rule set. Collect its own binding rules from CLAUDE.md, the coding standards and the ADRs into the project rule list our reviews check against.",CAT),
('trigger-catalog','base-1',"SLSA released a new version that changes the provenance requirements. Update the base catalog.",CAT),
('trigger-catalog','base-2',"The OWASP ASVS section that our review rules cite was revised last month. Bring the affected rule rows up to date and re-audit them.",CAT),
('trigger-decision','options-1',"Which option should we choose for storing session state: the existing PostgreSQL cluster or a table in the service's own database?",VD),
('trigger-decision','replace-2',"Should we replace the nightly cleanup cron with the bucket's own lifecycle rule?",VD),
('trigger-oss','find-1',"Is there an OSS tool that could take over our database backups?",OSS,(VD,)),
('trigger-oss','adopt-2',"Should we adopt Velero for the cluster backups?",OSS,(VD,)),
('trigger-bug','test-fails-1',"tests/test_export.py::test_expired fails on main with an AssertionError. Find out why.",BUG),
('trigger-bug','release-broke-2',"The release broke: the cleanup job ends in ImagePullBackOff.",BUG),
('trigger-bug','wrong-value-3',"The invoice total shows 104.50 instead of 100.45. Fix this wrong value.",BUG),
('disambiguation','rules-changed-update',"Our rules changed: ADR-0012 now requires 14-day retention for exports. Update the catalog.",CAT),
('disambiguation','check-spec-against-rules',"Check docs/specs/billing.md against our rules.",REV),
('disambiguation','accepted-missing-rule',"The last review of the billing spec listed a possible missing rule about webhook retries, and the owner accepted it. Add it.",CAT),
('disambiguation','standard-changed-still-holds',"The catalog was already updated for the new supply-chain standard. Does docs/design/release.md still hold?",REV),
('disambiguation','design-review-not-decision',"Review docs/design/session-store.md, which proposes a shared PostgreSQL table for sessions, against our rules.",REV),
('disambiguation','decision-not-design-review',"docs/design/session-store.md lists three options for the session store. Which one should we take?",VD),
('disambiguation','tool-adoption-not-decision',"Should we adopt Velero or keep our own backup script?",OSS,(VD,)),
('disambiguation','decision-not-tool-adoption',"Should backups be run by the platform team's one job or by each service itself?",VD),
('disambiguation','bug-not-design-review',"Exports are being deleted after 3 days instead of 30 in production.",BUG),
('disambiguation','design-review-not-bug',"Check the retention section of docs/design/export-cleanup.md against our standards.",REV),
('disambiguation','failing-test-not-plan-check',"The test in step 4 of docs/plans/migrate-queue.md fails when I run it: `queue_depth` returns -1.",BUG),
('disambiguation','plan-check-not-failing-test',"Before we start: can docs/plans/migrate-queue.md be followed exactly as written, including its test steps?",REV),
('no-trigger','explain-function',"Explain what this function does:\n\n```python\ndef expired(keys, now, days=30):\n    return [k for k in keys if (now - k.created).days > days]\n```",None),
('no-trigger','run-test',"Run `pytest tests/test_export.py -q` and tell me whether it passes.",None),
('no-trigger','rename-variable',"In src/export.py rename the variable `tmp` to `expired_keys`.",None),
('no-trigger','commit-message',"Write a commit message for this diff:\n\n```diff\n-    days = 30\n+    days = 14\n```\n\nIt shortens how long exports are kept.",None),
('no-trigger','standards-question',"In general, what do industry standards such as ISO 27001 say about how long backups should be retained?",None),
('no-trigger','fix-typo',"Fix the typo \"retreive\" in docs/design/export-cleanup.md.",None),
('no-trigger','pr-bug-review',"Review this PR for bugs:\n\n```diff\n def expired(keys, now, days=30):\n-    return [k for k in keys if (now - k.created).days > days]\n+    return [k for k in keys if (now - k.created).days >= days or k.created is None]\n```",None),
]
for p in P: case(*p)
print(len(P))
