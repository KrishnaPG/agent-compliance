import os,re
E=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VER=re.search(r"^Version: (\S+)",open(E+"/../catalog/index.md").read(),re.M).group(1)
import os,shutil,json
R=E+'/accuracy'
shutil.rmtree(R,ignore_errors=True)
A="""# Tenant reports database design

## Tier

Tier: standard. RPO 1 hour, RTO 4 hours.

## Database

All tenants share one PostgreSQL 16 database, `reports`, and connect through the one role `app`.
Per-tenant client-authentication rules live in separate files under `include_dir`; the writer reads
`pg_hba_file_rules` for errors before any reload and applies with `pg_reload_conf()`, never a restart.
This design supersedes the reports design v1.

## Secrets

The database password is copied by hand into `/etc/reports/env` on each host.
The worker receives it as the command-line argument `--db-password`.
When the password is re-issued, the store emits an event and the worker reloads it at once; there is no periodic refresh.
Revocation removes the credential from the worker first, then drops the database role.
The export salt is generated once, created with create-if-missing behind a guard read; when reading it fails the worker stops and never regenerates it.

## Backup

A native `pg_basebackup` runs every 24 hours. An alert fires when the newest backup is older than the RPO, and a restore drill into an isolated target runs monthly.

## Tenant cancellation

When a tenant cancels its subscription, the worker drops that tenant's tables the same night. No backup of them is taken first and no owner decision on retention is recorded.

## Cleanup and reset

The cleanup job removes at most 100 report files per run and stops for an operator's confirmation above that.
`reports reset --installation <id>` is explicit and idempotent, is scoped to one installation, prints its target before changing anything, and asks for confirmation before a durable reset.

## Surface

The worker is a batch job: it accepts no inbound traffic, signs nothing, and the design defines no tests.
"""
B="""# Billing sync design

A single-tenant internal job copies invoices from the payment provider into the ledger every night.

## Identity

One service account, `deploy-all`, plans, applies, releases and reads; engineers hold a standing deployment role.
The provider API key is static and has no maximum age.
The sync step has a deadline of 30 minutes and runs with an access token that lives 15 minutes.
The token reaches the job only from the secret store, by a declared reference the platform resolves; when the store is unavailable the job does not start, and no other copy exists.
The job passes the token to the provider client on standard input, never in arguments, logs or messages.
The job uses only the `billing.read` grant, which the provider account already holds ("billing.read: granted 2026-09-01").

## Queue and cache

Failed invoices wait in a retry queue held in memory only.
The invoice cache is a rebuildable projection: source the provider API, replay horizon 30 days, rebuild path a full resync, retention 30 days, disposition delete; it never authorizes a deployment.
Receipts and their fingerprints are read from the provider for every invoice; none is computed or filled in by the job.

## Provider behaviour

The design assumes the provider supports idempotency keys on invoice reads; this is to be confirmed later.

## Goals

We will improve reliability and make the sync observable.

## Surface

The job accepts no inbound traffic, signs nothing, resolves nothing across tenants, and the design defines no tests.
"""
TRUTH={
 'reports-db':dict(doc=A,brief="identity and secrets, data safety, documents, and concurrency and isolation (domains ID, DS, DC, CI). No overlay exists; this brief names the pack postgresql.",
   broken={'ID-01':'db-password|Secrets','ID-10':'by hand|/etc/reports|Secrets','DS-01':'cancel|Tenant cancellation|drop','DS-13':'cancel|Tenant cancellation','DS-03':'24|Backup','PG-02':'reports|app|Database|share','DC-03':'supersede|Database','DS-08':'cancel|drop|L28','DS-07':'cleanup|target|L3[0-3]'},
   held=['ID-04','ID-05','ID-06','PG-01'], na=['ID-02','ID-09','DS-11']),
 'billing-sync':dict(doc=B,brief="identity and secrets, data safety and documents (domains ID, DS, DC). No overlay exists and no pack applies.",
   broken={'ID-11':'deploy-all|standing|Identity','ID-12':'30|15|Identity','ID-13':'static|maximum age|Identity','DS-17':'memory|Queue','DC-11':'assum|to be confirmed|Provider behaviour','DC-12':'improve reliability|observable|Goals'},
   held=['ID-01','ID-10','ID-14','DS-05','DS-14','DC-03'], na=['ID-02','ID-08','DS-11']),
}
V=r"\|\s*\*{0,2}`?%s`?\*{0,2}\s*\|\s*\*{0,2}%s"
for name,t in TRUTH.items():
    d=f"{R}/{name}"; os.makedirs(d+'/proj/docs'); os.makedirs(d+'/graders')
    open(d+'/proj/docs/design.md','w').write(t['doc'])
    open(d+'/case.yaml','w').write(f'schema_version: "1.1"\nname: accuracy-{name}\ncontext:\n  add_dirs: [proj]\n')
    open(d+'/prompt.md','w').write(f"---\ntags: [accuracy]\nmax_turns: 30\ntimeout_seconds: 900\nallowed_tools: [Skill, Read, Glob, Grep]\n---\nThe project is the directory {d}/proj. No shell is available in this session and nothing can be written; no verdict record exists yet. Print the verdict record in your reply, one table row per rule.\n\nReview docs/design.md for compliance, focused on {t['brief']}\n")
    def w(n,pat,extra=''): open(f"{d}/graders/{n}.md",'w').write(f"---\ntype: regex\npattern: '{pat}'\n{extra}---\n")
    for r,loc in t['broken'].items():
        w(f"{r}-broken",V%(r,'BROKEN'))
        w(f"{r}-location",r"\|\s*\*{0,2}`?%s`?\*{0,2}\s*\|[^\n]*(%s)"%(r,loc),"flags: i\n")
    for r in t['held']: w(f"{r}-held",V%(r,'HELD'))
    for r in t['na']: w(f"{r}-na",V%(r,'NA'))
json.dump({k:{'broken':list(v['broken']),'held':v['held'],'na':v['na']} for k,v in TRUTH.items()},open(R+'/truth.json','w'),indent=1)
