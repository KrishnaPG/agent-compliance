"""Writes the trigger, disambiguation and no-trigger cases. Run after changing a prompt here."""
import os
E=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VD,OSS,BUG='vetted-decision','vet-oss','bug-analysis'
ALL=[VD,OSS,BUG]
def g(skill,lo,hi=None):
    return f"---\ntype: tool_used\ntool: Skill\ninput_match: '{skill}'\nmin: {lo}\n"+(f"max: {hi}\n" if hi is not None else "")+"arm: both\n---\n"
def case(group,name,prompt,want,ungraded=()):
    d=f"{E}/{group}/{name}"; os.makedirs(d+'/graders',exist_ok=True)
    open(d+'/prompt.md','w').write(f"---\ntags: [trigger, {group}]\nmodel: sonnet\nmax_turns: 2\nallowed_tools: [Skill]\n---\n{prompt}\n")
    for sk in ALL:
        if sk==want: open(f"{d}/graders/{sk}-fires.md",'w').write(g(sk,1))
        elif sk not in ungraded: open(f"{d}/graders/{sk}-silent.md",'w').write(g(sk,0,0))
P=[
('trigger-decision','options-1',"Which option should we choose for storing session state: the existing PostgreSQL cluster or a table in the service's own database?",VD),
('trigger-decision','replace-2',"Should we replace the nightly cleanup cron with the bucket's own lifecycle rule?",VD),
('trigger-oss','find-1',"Is there an OSS tool that could take over our database backups?",OSS,(VD,)),
('trigger-oss','adopt-2',"Should we adopt Velero for the cluster backups?",OSS,(VD,)),
('trigger-bug','test-fails-1',"tests/test_export.py::test_expired fails on main with an AssertionError. Find out why.",BUG),
('trigger-bug','release-broke-2',"The release broke: the cleanup job ends in ImagePullBackOff.",BUG),
('trigger-bug','wrong-value-3',"The invoice total shows 104.50 instead of 100.45. Fix this wrong value.",BUG),
('disambiguation','decision-not-design-review',"docs/design/session-store.md lists three options for the session store. Which one should we take?",VD),
('disambiguation','tool-adoption-not-decision',"Should we adopt Velero or keep our own backup script?",OSS,(VD,)),
('disambiguation','decision-not-tool-adoption',"Should backups be run by the platform team's one job or by each service itself?",VD),
('disambiguation','bug-not-design-review',"Exports are being deleted after 3 days instead of 30 in production.",BUG),
('no-trigger','unmerged-test-fails',"My change on this branch makes tests/test_export.py::test_expired fail. Make it pass before I open the PR.",None),
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
