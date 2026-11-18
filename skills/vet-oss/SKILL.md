---
name: vet-oss
description: Vet a third-party tool from its pinned source against the compliance catalog before it is named. Load before any search when about to suggest, compare or adopt an OSS tool, operator, chart, library, container image or SaaS, or to replace the project's own code with one. Do NOT use to upgrade the version of a tool already adopted (read its changelog) or for how-to questions about an adopted tool.
---

# Vet an OSS candidate

Every verdict names a catalog rule id and evidence from the candidate's own source or a real install. A README sentence or a star count proves nothing.

## Inputs

- **Catalog and overlay:** as `../compliance-review/SKILL.md` "Inputs" loads them. The domains that judge a tool are at least NO, SC, ID, LC, RL, OB, DS and PF, plus those of the job it takes over.
- **Project bindings:** `docs/agents/compliance-bindings.md`, or the path the project's AGENTS.md or CLAUDE.md names: where a vetting is recorded, the clone directory, the evidence environment. No bindings file: clone to a new temporary directory, put the result in the reply and say it is unrecorded.

**Once per candidate and tag.** The result is recorded where the bindings say, headed `Vetted: <tool> <tag>` with the date. Search for that heading before cloning: reuse it unless the tag or a rule it cites changed.

**Cost:** read line ranges of the clone; about 20 tool calls.

## Steps

1. **Requirements.** Every effect the current mechanism has, implicit ones included, each as `path:line` plus a few words from the project's code and its approved decision. State whether the tool would run in the product or only in the development toolchain: a toolchain tool is judged on maintenance, pinned install, fitness for the job, bounded blast radius and observability.
2. **Candidates.** Upstream first, then community: repository, license, latest release and date, last commit. An archived project is dropped, and the answer says so.
3. **Source read.** `git clone --depth 1 --branch <tag> <url> <clone directory>/<name>`, then read from the clone:
   - its API types or CRDs;
   - its paths for delete, revoke and reread after a crash;
   - its chart or install manifest (RBAC scope, image tag or digest);
   - its open issues, decision records and docs (declared non-goals, known defects in the needed paths);
   - its release pipeline (signing, SBOM, provenance).
4. **Judge.** Per candidate, one row per requirement and per in-scope catalog rule: `| Rule or requirement | Candidate | HELD/BROKEN/NA/UNVERIFIED | Evidence |`, evidence being a `path:line` in the clone or the answer of a real install. Runtime behaviour without an install answer is UNVERIFIED.
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
