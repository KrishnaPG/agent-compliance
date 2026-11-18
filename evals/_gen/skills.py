"""Writes the behaviour cases of vetted-decision, bug-analysis and vet-oss."""
import os,re,shutil
E=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VER=re.search(r"^Version: (\S+)",open(E+"/../catalog/index.md").read(),re.M).group(1)
R=E+'/skills'
shutil.rmtree(R,ignore_errors=True)
def tool(name,tool,match,lo,hi=None):
    return name,f"---\ntype: tool_used\ntool: {tool}\n"+(f"input_match: '{match}'\n" if match else "")+f"min: {lo}\n"+(f"max: {hi}\n" if hi is not None else "")+"---\n"
def rx(name,pat,match=None,target=None,flags=None):
    return name,f"---\ntype: regex\npattern: '{pat}'\n"+(f"match: {match}\n" if match else "")+(f"target: {target}\n" if target else "")+(f"flags: {flags}\n" if flags else "")+"---\n"
NODUP=rx("no-catalog-file-read-twice", r'file_path\\?":\s*\\?"([^"\\]*/catalog/[^"\\]+)\\?"[\s\S]*file_path\\?":\s*\\?"\1\\?"','not_contains','trace')
def case(name,skill,files,ask,graders,turns):
    d=f"{R}/{name}"; p=d+'/proj'
    for rel,txt in files.items():
        os.makedirs(os.path.dirname(f"{p}/{rel}"),exist_ok=True); open(f"{p}/{rel}",'w').write(txt)
    os.makedirs(d+'/graders')
    open(d+'/case.yaml','w').write(f'schema_version: "1.1"\nname: {name}\ncontext:\n  add_dirs: [proj]\n')
    open(d+'/prompt.md','w').write(f"---\ntags: [skills]\nmodel: sonnet\nmax_turns: {turns}\ntimeout_seconds: 900\nallowed_tools: [Skill, Read, Glob, Grep, Agent]\n---\nThe project is the directory {p}. No shell or network is available in this session and nothing can be written; put the result in your reply.\n\n{ask}\n")
    for n,g in [tool('skill-fired','Skill',skill,1),NODUP]+graders: open(f"{d}/graders/{n}.md",'w').write(g)
CLEAN='''import datetime, subprocess

def run(bucket, days=30):
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for key in subprocess.run(["gsutil", "ls", f"gs://{bucket}/"], capture_output=True, text=True).stdout.split():
        if key_date(key) < cutoff:
            subprocess.run(["gsutil", "rm", key], check=True)
'''
TF='''resource "google_storage_bucket" "exports" {
  name     = "exports"
  location = "EU"
  lifecycle_rule {
    condition { age = 30 }
    action { type = "Delete" }
  }
}
'''
BIND="# Compliance bindings\n\n- Decisions are recorded in `docs/decisions/<slug>.md`, one file per question.\n- Tracker: none. Evidence environment: none.\n"
DEC=f'''Decision: Should the nightly cleanup cron be replaced with the bucket's own lifecycle rule? (2026-11-10, a1b2c3d)
Catalog: base {VER} + packs none + overlay none
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
Falsifying call: `gsutil lifecycle get gs://exports` -> {{"rule":[{{"action":{{"type":"Delete"}},"condition":{{"age":30}}}}]}}
Recommendation: O2; rejected: O1 (NO-06), O3 (PF-01)
Owner decides: none
'''
case('decision-reused','vetted-decision',{'docs/agents/compliance-bindings.md':BIND,'docs/decisions/cleanup-mechanism.md':DEC,'src/cleanup.py':CLEAN,'infra/bucket.tf':TF},
 "Should we replace the nightly cleanup cron with the bucket's own lifecycle rule? The repository is still at commit a1b2c3d.",[
 tool('no-catalog-file-read','Read',r'/catalog/',0,0),
 tool('record-read-once','Read',r'docs/decisions/',1,1),
 tool('no-subagent','Agent',None,0,0),
 rx('same-recommendation',r'O2'), rx('says-reused',r'reus|recorded|already decided',flags='i'),
 rx('no-other-recommendation',r'Recommendation:\s*\**\s*O[13]\b','not_contains')],12)
BUGSRC='''import logging, subprocess

def run(token, bucket):
    logging.info("cleanup start bucket=%s token=%s", bucket, token)
    subprocess.run(["gsutil", "-o", f"Credentials:gs_oauth2_refresh_token={token}", "rm", f"gs://{bucket}/expired/**"], check=True)
'''
case('bug-record-rule-lines','bug-analysis',{'src/cleanup.py':BUGSRC},
 "The cleanup job writes the bucket token into its log (src/cleanup.py). Record the bug; do not fix it yet. There is no tracker and no bindings file.",[
 tool('index-read-at-most-once','Read',r'catalog/index\.md',0,1),
 tool('only-touched-domain-files','Read',r'catalog/base/(?!(ID|OB)\.md)',0,0),
 rx('rule-row-read-not-guessed',r'No secret appears in process arguments',target='trace'),
 tool('no-pack-file','Read',r'catalog/packs/',0,0),
 tool('no-subagent','Agent',None,0,0),
 rx('analysis-heading',r'Analysis:'), rx('rule-line-id01',r'Rule:\s*\**\s*ID-01\s*\**\s*BROKEN'),
 rx('says-unrecorded',r'unrecorded|not recorded',flags='i'),
 rx('gives-setup-prompt',r'compliance bindings from templates/compliance-bindings\.md',flags='i')],18)
REL='''name: release
on: { push: { tags: ["v*"] } }
jobs:
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t ghcr.io/tinybackup/tinybackup:latest .
      - run: docker push ghcr.io/tinybackup/tinybackup:latest
'''
RBAC='''apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: tinybackup }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cluster-admin }
subjects: [{ kind: ServiceAccount, name: tinybackup, namespace: tinybackup }]
'''
PRUNE='''package cmd

// Prune removes every snapshot older than keep. It asks for no confirmation and has no limit.
func Prune(store Store, keep time.Duration) error {
	for _, s := range store.List() {
		if time.Since(s.Created) > keep {
			store.Delete(s.ID)
		}
	}
	return nil
}
'''
BK='''#!/bin/sh
# nightly: one native dump per database, uploaded; the restore drill reads the newest dump
pg_dump --format=custom "$DATABASE" | gsutil cp - "gs://backups/$DATABASE/$(date +%F).dump"
'''
case('oss-judged-by-rule-ids','vet-oss',{'scripts/backup.sh':BK,'clone/tinybackup/LICENSE':'MIT License\n','clone/tinybackup/.github/workflows/release.yml':REL,
   'clone/tinybackup/chart/values.yaml':'image:\n  repository: ghcr.io/tinybackup/tinybackup\n  tag: latest\n','clone/tinybackup/chart/templates/rbac.yaml':RBAC,'clone/tinybackup/cmd/prune.go':PRUNE},
 "Should we adopt tinybackup v1.2.0 in place of scripts/backup.sh? Its source at tag v1.2.0 is already cloned at clone/tinybackup, and that clone is everything the project publishes. There is no bindings file and no overlay.",[
 tool('index-read-once','Read',r'catalog/index\.md',1,1),
 tool('no-unrelated-domain','Read',r'catalog/base/(HO|HS|PN|PR|DC|PL)\.md',0,0),
 tool('not-all-of-base','Read',r'catalog/base/',1,11),
 tool('no-pack-file','Read',r'catalog/packs/',0,0),
 rx('rows-carry-rule-ids',r'\|\s*\**`?(SC|ID|NO|DS|RL|OB|LC|PF)-\d\d'),
 rx('supply-chain-rule-broken',r'SC-\d\d[^\n]*BROKEN'),
 rx('not-presented',r'no OSS meets the rules',flags='i'),
 rx('gives-setup-prompt',r'compliance bindings from templates/compliance-bindings\.md',flags='i')],40)
