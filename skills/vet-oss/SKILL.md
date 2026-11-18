---
name: vet-oss
description: Vet a third-party tool at its pinned version against the compliance catalog before it is named. Load before any search when about to suggest, compare or adopt an OSS tool, operator, chart, library, container image or SaaS, or to replace the project's own code with one. Do NOT use to upgrade the version of a tool already adopted (read its changelog) or for how-to questions about an adopted tool.
---

# Vet an OSS candidate

Every verdict names a catalog rule id and its evidence (step 3 sets which evidence each tier needs).

## Inputs

- **Catalog and overlay:** as `../compliance-review/SKILL.md` "Inputs" loads them. The domains that judge a tool are at least NO, SC, ID, LC, RL, OB, DS and PF, plus those of the job it takes over.
- **Project bindings:** found as `../compliance-review/SKILL.md` "Inputs" says: where a vetting is recorded, the clone directory, the evidence environment. No bindings: clone to a new temporary directory, put the full result in the reply, say it is unrecorded and give the setup prompt.

**Once per candidate and tag.** The result is recorded where the bindings say, headed `Vetted: <tool> <tag>` with the date. Search for that heading first: reuse it unless the tag or a rule it cites changed.

**Cost by tier** (step 3): adopted, about 3 tool calls; established, about 8; other, about 20. Never clone an established or adopted project.

## Steps

1. **Requirements.** Every effect the current mechanism has, implicit ones included, each as `path:line` plus a few words from the project's code and its approved decision. State whether the tool would run in the product or only in the development toolchain: a toolchain tool is judged on maintenance, pinned install, fitness for the job, bounded blast radius and observability.
2. **Candidates.** Upstream first, then community: repository, license, latest release and date, last commit. An archived project is dropped, and the answer says so.
3. **Evidence, by tier:**
   - **Adopted** (the project already runs it at a pinned version): cite its existing `Vetted:` record or the approved decision that adopted it; judge only the new use, from the owner's documentation of that feature at the pinned version.
   - **Established** (a foundation or vendor project in wide production use, e.g. PostgreSQL, ClickHouse, Kubernetes, Prometheus, OpenSSH): no clone. Evidence is its versioned official documentation, release notes, security advisories and release signing or provenance page. A runtime claim the documentation does not settle is read from one file at the pinned tag (the forge's raw-file or contents API), never a clone.
   - **Other** (small, young or single-maintainer): `git clone --depth 1 --branch <tag> <url> <clone directory>/<name>`, then read its API types or CRDs; its delete, revoke and crash-reread paths; its chart or install manifest (RBAC scope, image digest); its open issues and declared non-goals in the needed paths; its release pipeline (signing, SBOM, provenance).
4. **Judge.** Per candidate, one row per requirement and per in-scope catalog rule: `| Rule or requirement | Candidate | HELD/BROKEN/NA/UNVERIFIED | Evidence |`. Evidence is a `path:line` in the source, a versioned documentation URL with its section (adopted and established tiers only), or the answer of a real install. A README sentence or star count is never evidence. A runtime behaviour the evidence does not settle is UNVERIFIED.
5. **Verdict.** Present a candidate only when no row is BROKEN or UNVERIFIED. Otherwise say "no OSS meets the rules", list each candidate's BROKEN rule ids, keep the current owner, and name an upstream contribution that would close a near miss. When every candidate fails, check what the industry uses for the job before concluding none fits.

## Output

```
Vetted: <tool> <tag> (<date>)
Catalog: base <version> + packs <names> + overlay <path>@<commit>
Class: product | toolchain
Requirements: ...
Candidates: ...
| Rule or requirement | Candidate | Verdict | Evidence |
Verdict: <candidate> passes | no OSS meets the rules (<candidate>: <rule ids>)
```
