import os,re
E=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VER=re.search(r"^Version: (\S+)",open(E+"/../catalog/index.md").read(),re.M).group(1)
import os,subprocess,shutil
R=E+'/cost'
shutil.rmtree(R,ignore_errors=True)
def sha(text):
    return subprocess.run(['git','hash-object','--stdin'],input=text.encode(),capture_output=True).stdout.decode().strip()[:12]
def design(ret_fixed=False):
    ret = ("Exports are deleted 30 days after creation. The project owner decided on 2026-10-02 (issue #41) that exports are not retained beyond 30 days; each is rebuilt on request from the orders database.\n"
           if ret_fixed else
           "Exports older than 30 days are deleted by the nightly job. No backup of the bucket exists and no retention decision is recorded.\n")
    return f"""# Export cleanup design

Owner: data-platform on-call

## Purpose

Customers download CSV exports of their orders. Each export is one object in the `exports` bucket.
The nightly cleanup job removes old exports so the bucket stays under 50 GB.

## Storage

One bucket, `exports`, one object per export, keyed by tenant and export id.
This section supersedes the 2025 storage note.

## Retention

{ret}
## Access

The job authenticates to the bucket with a service-account key file kept on the host at /etc/exports/key.json.
The key is passed to the job as the command-line argument --key.

## Operations

The job logs each deleted key and raises an alert when a run fails.
"""
def overlay(days=30):
    return f"""# Design compliance overlay (mini project)

Base: {VER} | Packs: postgresql | Date: 2026-11-18 | Sources: a1b2c3d | Verdicts: docs/reviews/compliance/<artifact-name>.md

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| MINI-DS-01 | A customer export is deleted no later than {days} days after its creation. | docs/adr/0012-export-retention.md §2 | Does the design delete every export within {days} days? |
| MINI-DC-01 | Every design names its owning team in an `Owner:` line under the title. | AGENTS.md "Design documents" | Is there an `Owner:` line under the title? |
"""
def record(key, ds01_broken=True):
    rows=[("DC-03","BROKEN","Storage","\"This section supersedes the 2025 storage note\"","delete the sentence; provenance goes in the commit message")]
    rows+=[(f"DC-{i:02d}","HELD" if i in(1,5,12) else "NA","whole document" if i in(1,5,12) else "-","no line breaks the rule" if i in(1,5,12) else "no such surface in this design","-") for i in range(1,13) if i!=3]
    rows.append(("DS-01","BROKEN","Retention","bucket objects deleted with no backup and no recorded owner decision","record the project-owner retention decision or add a restore-tested backup"))
    rows+=[("DS-04","HELD","Retention","deletion is by age of the export only; no retained record references an export","-"),
           ("DS-08","HELD","Purpose; Operations","nightly job logs each deleted key and alerts on failure","-"),
           ("DS-13","HELD","Retention","deletion follows age, never a cancellation","-")]
    rows+=[(f"DS-{i:02d}","NA","-","no such surface in this design","-") for i in range(1,18) if i not in(1,4,8,13)]
    rows+=[("PN (all 19)","NA","-","the artifact is a design, not a plan","-"),("PR (all 13)","NA","-","no process surface in this design","-"),
           ("MINI-DS-01","HELD","Retention","exports are deleted at 30 days","-"),("MINI-DC-01","HELD","title block","`Owner: data-platform on-call`","-")]
    rows.sort()
    t="\n".join("| "+" | ".join(r)+" |" for r in rows)
    return f"""Key: {key}
Catalog: base {VER} + packs postgresql + overlay docs/agents/design-compliance.md (built against base {VER})
Artifact: docs/design.md
Scope: DC, DS, PN, PR; out of scope: every other domain: no surface in this design
Verdict: FAIL (2 BROKEN)
| Rule | Verdict | Anchors | Evidence | Fix |
|---|---|---|---|---|
{t}
Possible missing rules: none
Catalog drift: none
"""
def key(d,o,scope='all'): return f"docs/design.md@{sha(d)} | base {VER} | overlay {sha(o)} | packs postgresql | scope {scope}"
def tool(name,tool,match,lo,hi=None):
    s=f"---\ntype: tool_used\ntool: {tool}\n"+(f"input_match: '{match}'\n" if match else "")+f"min: {lo}\n"+(f"max: {hi}\n" if hi is not None else "")+"---\n"
    return name,s
def rx(name,pat,match=None,target=None,flags=None):
    s=f"---\ntype: regex\npattern: '{pat}'\n"+(f"match: {match}\n" if match else "")+(f"target: {target}\n" if target else "")+(f"flags: {flags}\n" if flags else "")+"---\n"
    return name,s
FIRED=("skill-fired","---\ntype: tool_used\ntool: Skill\ninput_match: 'compliance-review'\nmin: 1\n---\n")
NODUP=rx("no-catalog-file-read-twice", r'file_path\\?":\s*\\?"([^"\\]*/catalog/[^"\\]+)\\?"[\s\S]*file_path\\?":\s*\\?"\1\\?"', 'not_contains','trace')
def case(name,files,ask,graders,turns=25):
    d=f"{R}/{name}"; p=f"{d}/proj"
    for rel,txt in files.items():
        os.makedirs(os.path.dirname(f"{p}/{rel}"),exist_ok=True); open(f"{p}/{rel}",'w').write(txt)
    os.makedirs(d+'/graders')
    open(d+'/case.yaml','w').write(f'schema_version: "1.1"\nname: {name}\ncontext:\n  add_dirs: [proj]\n')
    D=files['docs/design.md']; O=files['docs/agents/design-compliance.md']
    pre=f"The project is the directory {p} (overlay at docs/agents/design-compliance.md). No shell is available in this session, so here are the git blob shas: docs/design.md = {sha(D)}, docs/agents/design-compliance.md = {sha(O)}. Nothing can be written here; print the verdict record in your reply.\n\n"
    open(d+'/prompt.md','w').write(f"---\ntags: [cost]\nmodel: sonnet\nmax_turns: {turns}\ntimeout_seconds: 600\nallowed_tools: [Skill, Read, Glob, Grep, Agent]\n---\n{pre}{ask}\n")
    for n,g in [FIRED,NODUP]+graders: open(f"{d}/graders/{n}.md",'w').write(g)
D0,D1,O30,O14=design(),design(True),overlay(30),overlay(14)
OV='docs/agents/design-compliance.md'; REC='docs/reviews/compliance/design.md'
# 1 full review, no record
case('full-review',{'docs/design.md':D0,OV:O30},"Review docs/design.md for compliance.",[
 tool('index-read-once','Read',r'catalog/index\.md',1,1),
 tool('not-all-of-base','Read',r'catalog/base/',1,8),
 tool('no-unrelated-domain','Read',r'catalog/base/(SC|HO|HS|PL|LC)\.md',0,0),
 tool('no-unnamed-pack','Read',r'catalog/packs/(?!postgresql/)',0,0),
 tool('at-most-five-reviewers','Agent',None,0,5),
 rx('key-line',r'Key: docs/design\.md@'+sha(D0)),
 rx('plan-and-actual',r'Plan:[\s\S]*Actual:'),
 rx('ds01-broken',r'DS-01[^\n]*BROKEN'), rx('dc03-broken',r'DC-03[^\n]*BROKEN')],turns=30)
# 2 cached
case('cached-unchanged',{'docs/design.md':D0,OV:O30,REC:record(key(D0,O30))},"Review docs/design.md for compliance.",[
 tool('no-catalog-file-read','Read',r'/catalog/',0,0),
 tool('one-record-lookup','Read',r'docs/reviews/compliance/',1,1),
 tool('no-reviewer','Agent',None,0,0),
 rx('reused-line',r'Reused:'), rx('same-verdict',r'FAIL \(2 BROKEN\)')],turns=12)
# 3 incremental: one section edited
diff="""--- a/docs/design.md
+++ b/docs/design.md
@@ -17,3 +17,3 @@ This section supersedes the 2025 storage note.
 ## Retention
 
-Exports older than 30 days are deleted by the nightly job. No backup of the bucket exists and no retention decision is recorded.
+Exports are deleted 30 days after creation. The project owner decided on 2026-10-02 (issue #41) that exports are not retained beyond 30 days; each is rebuilt on request from the orders database.
"""
case('incremental-section-edit',{'docs/design.md':D1,OV:O30,REC:record(key(D0,O30)),'docs/design.diff':diff},
 "I fixed the Retention section of docs/design.md after the last review (the diff from the reviewed blob is docs/design.diff). Re-review it.",[
 tool('only-dc-ds-domain-files','Read',r'catalog/base/(?!(DC|DS)\.md)',0,0),
 tool('no-pack-file','Read',r'catalog/packs/',0,0),
 tool('no-reviewer','Agent',None,0,0),
 rx('ds01-now-held',r'DS-01[^\n]*HELD'), rx('dc03-still-broken',r'DC-03[^\n]*BROKEN'),
 rx('untouched-rows-carried',r'carried from',flags='i'),
 rx('ds01-not-carried',r'\| DS-01 [^\n]*carried','not_contains',flags='i')],turns=15)
# 4 focused
case('focused-identity',{'docs/design.md':D0,OV:O30},"Check only how docs/design.md handles identity and secrets (the Access section) for compliance. Skip the rest.",[
 tool('only-id-domain-file','Read',r'catalog/base/(?!ID\.md)',0,0),
 tool('id-domain-read','Read',r'catalog/base/ID\.md',1,1),
 tool('no-unnamed-pack','Read',r'catalog/packs/(?!postgresql/)',0,0),
 tool('no-reviewer','Agent',None,0,0),
 rx('rest-out-of-focus',r'(not reviewed|out of focus)[^\n]{0,40}(out of focus|not reviewed)',flags='i'),
 rx('id01-broken',r'ID-01[^\n]*BROKEN'),
 rx('no-verdict-outside-focus',r'(DS|DC|PN|PR)-\d\d[^\n]*\b(HELD|BROKEN)\b','not_contains')],turns=15)
# 5 catalog bump: one overlay row changed
odiff="""--- a/docs/agents/design-compliance.md
+++ b/docs/agents/design-compliance.md
@@ -7 +7 @@
-| MINI-DS-01 | A customer export is deleted no later than 30 days after its creation. | docs/adr/0012-export-retention.md §2 | Does the design delete every export within 30 days? |
+| MINI-DS-01 | A customer export is deleted no later than 14 days after its creation. | docs/adr/0012-export-retention.md §2 | Does the design delete every export within 14 days? |
"""
case('catalog-bump-one-rule',{'docs/design.md':D0,OV:O14,REC:record(key(D0,O30)),'docs/agents/design-compliance.diff':odiff},
 "Our overlay changed since the last review of docs/design.md (the overlay's diff is docs/agents/design-compliance.diff); the design itself did not. Review docs/design.md for compliance.",[
 tool('no-base-domain-file','Read',r'catalog/base/',0,0),
 tool('no-pack-file','Read',r'catalog/packs/',0,0),
 tool('no-reviewer','Agent',None,0,0),
 rx('changed-rule-rechecked',r'MINI-DS-01[^\n]*BROKEN'),
 rx('other-rows-carried',r'carried',flags='i'),
 rx('changed-rule-not-carried',r'\| MINI-DS-01 [^\n]*carried','not_contains',flags='i')],turns=15)
print(sha(D0),sha(D1),sha(O30),sha(O14))
