# agent-compliance

A Claude Code plugin that reviews designs, specs, ADRs, implementation plans, design decisions, third-party tool choices and bug records against a fixed, versioned catalog of industry-standard rules (332 base rules in 16 domains, plus optional technology packs). Your project adds its own rules in a small overlay file. Every review gives one HELD, BROKEN or NA verdict per rule, with the evidence, so the same artifact is judged the same way each time.

## Why use it

- **Ad-hoc reviews do not converge.** An open-ended review always finds something new, so every round produces new findings and the work never settles. A review against a fixed catalog has a finite set of rules, and the set of BROKEN rules only shrinks. A re-review checks only the rules that were BROKEN and the rules the fix touched.
- **Every verdict cites a rule.** A finding is "rule `DS-07` is BROKEN at this location, for this failing input, fix it this way", not an opinion. A rule row is written as a whole testable rule with its numbers and exceptions, so a reviewer judges it from the row alone.
- **Agents cannot skip reading or verifying.** HELD must cite where the artifact satisfies the rule. A runtime rule is BROKEN only with a concrete failing input or reachable state, and a runtime rule supported only by documentation is UNVERIFIED, never HELD. A third-party tool is judged from its pinned source clone, not from its README.
- **Decisions and bugs use the same rules.** A design decision judges every option against the catalog and recommends one with no BROKEN rule. A bug record names the catalog rules the defect broke. Rule ids tie reviews, decisions and bugs together, and a rule id that keeps returning in bug records points at a design issue.
- **Repeat work is cheap.** A review is keyed by artifact blob sha, catalog version, overlay sha, packs and scope. The same key returns the recorded verdict without loading the catalog. A changed artifact or catalog re-runs only the affected rules.

## Salient features

- Ready-made base catalog: 332 rules in 16 domains (lifecycle, hand-offs, reliability, identity and secrets, supply chain, observability, performance, concurrency, configuration, native owners and least code, platform reconciliation, data safety, documents, plans, process), and 67 generic scenarios that each name the rules that decide them.
- Opt-in technology packs: `gcp`, `opentofu`, `nats-jetstream`, `kubernetes-flux`, `react`, `postgresql`, `systemd`, `salt`, `agent-jobs` (63 rules).
- Project overlay: your own rules, and rows that tighten a base or pack rule.
- Incremental re-review: only BROKEN rules, touched anchors and changed catalog ids are re-run.
- Preview and actual cost lines (`Plan:` and `Actual:`) on every review, and inline review when under about 100 rules are in scope; larger scopes are split across at most five reviewers.
- Literal-follower dry run for implementation plans: a low-cost model follows the plan as written and every point where it had to guess is a BROKEN plan-format rule.
- Independent catalog weakness audit by a fresh agent.
- Stable rule ids (a changed rule keeps its id; a removed id is never reused), and `catalog/CHANGES.md` lists each added or changed id per version, so overlays can see drift.
- "Possible missing rules": a requirement the reviewer infers but no row states is reported for the catalog owner, never as a design finding.
- Bundled evals for skill triggering, accuracy against ground truth, and review cost.

## Install

For Claude Code, from a shell:

```
claude plugin marketplace add KrishnaPG/agent-compliance
claude plugin install agent-compliance@agent-compliance
```

Pin a release by adding a tag to the marketplace source: `claude plugin marketplace add KrishnaPG/agent-compliance#v1.5.0`.

For a team, put this in the project's `.claude/settings.json` so everyone gets the same pinned version:

```json
{
  "extraKnownMarketplaces": {
    "agent-compliance": {
      "source": { "source": "github", "repo": "KrishnaPG/agent-compliance", "ref": "v1.5.0" }
    }
  },
  "enabledPlugins": { "agent-compliance@agent-compliance": true }
}
```

In a running session, run `/reload-plugins` to load the plugin.

The plugin ships executables in `bin/` (the harness tools), so it installs in Claude Code only; claude.ai and Cowork do not install a plugin with a `bin/` directory.

## Quick start

1. **Build the project overlay once** (skip it to review against the base catalog alone). In Claude Code:

   > Build our compliance overlay from AGENTS.md, docs/coding-standards.md and the ADRs in docs/adr. We use the kubernetes-flux and postgresql packs.

   The `compliance-catalog` skill reads those sources, adds only rows the base catalog does not already state (or that tighten a base rule), covers the scenarios, has a fresh agent audit the result, and writes `docs/agents/design-compliance.md`.

2. **Bindings.** Step 1 also writes the bindings file from `templates/compliance-bindings.md` (at the path your AGENTS.md or CLAUDE.md names, else `docs/agents/compliance-bindings.md`): tracker, where decisions and vettings are posted, bug ledger and close commands, evidence environment, and the escalation categories only the project owner rules on. Without step 1, ask: `Write our compliance bindings from templates/compliance-bindings.md`. The decision, vetting and bug skills read it; without it they put results in the reply, say they are unrecorded and give that prompt.

3. **Run a first review:**

   > Review docs/design/export-cleanup.md for compliance against our catalog before I send it for approval.

   You get a key line, the scope, a PASS or FAIL verdict, and a table with one row per in-scope rule. Fix the BROKEN rows, then ask:

   > I fixed the BROKEN rules. Re-review it.

   Only the rules that failed and the rules the fix touched are re-run. Skills load by their descriptions; you can also name the skill in the prompt.

## Which skill when

| Skill | Use it for | Do not use it for | Produces |
|---|---|---|---|
| `compliance-review` | Reviewing a design, spec, ADR, plan or diff; re-review after fixes; checking a plan can be followed without decisions | Hunting bugs in code or a PR; choosing between options (`vetted-decision`); building a catalog (`compliance-catalog`) | A verdict table, one HELD/BROKEN/NA row per rule, PASS or FAIL, possible missing rules, catalog drift |
| `compliance-catalog` | No overlay yet; the project's own rules changed; a "possible missing rule" was accepted; an industry standard changed | Reviewing an artifact (a review never rebuilds the catalog) | A project overlay (or an updated base catalog) that passed a fresh-agent weakness audit |
| `vetted-decision` | Choosing or recommending a design: adopt, replace, move or delete a mechanism; X or Y; who owns X; a path that failed twice | Which work to do next; a mechanical edit of a settled design; explaining code; running checks; picking a third-party tool (`vet-oss`) | A `Decision:` record: options, per-rule verdicts, attack on the leading option, a falsifying call, one recommendation with no BROKEN rule |
| `vet-oss` | Before suggesting, comparing or adopting an OSS tool, operator, chart, library, image or SaaS, or replacing project code with one | Upgrading an already adopted tool; how-to questions about an adopted tool | A `Vetted:` record judged from the pinned source clone: passes, or "no OSS meets the rules" with the broken rule ids |
| `bug-analysis` | Any defect of any size, with or without a failing test; before any `fix` commit | New features, redesigns, prose edits that change no meaning | A bug record (class, cause, broken rule ids, siblings, test, falsifying call, where), a `fix(#N):` commit, closure only when the test passes |
| `harness` | Running the build harness: report spec gaps in the project's own documents, plan, build, measure and harvest its build-order items | Reviewing a design or plan (`compliance-review`); choosing between options (`vetted-decision`); fixing one bug (`bug-analysis`) | `.brick-harness/` state: gap report with file:line evidence, items and targets, a scoreboard written only by the measurer, merged code |

### compliance-review

Scopes the domains from the catalog index, loads only the in-scope files, and returns one verdict per rule. HELD cites where, BROKEN cites the location, the failing input and the fix, NA says why. Verdicts go in a verdict record (default `docs/reviews/compliance/<artifact-name>.md`), never inside the reviewed document. For plans it also runs the literal-follower dry run.

> Could a junior engineer follow docs/plans/migrate-queue.md step by step without having to guess anything? Verify that before we hand it over.

### compliance-catalog

Builds the project overlay: skips what the base already states, adds tightening rows that name the base id, lists scenarios with no deciding rule under "Gaps" and disagreeing sources under "Source conflicts", then runs the weakness audit. It can also update the base catalog (project-independent rules only, with a version bump and a `CHANGES.md` entry).

> Our coding standards changed. Update the compliance overlay.

### vetted-decision

Traces each value and record hop by hop for every option (keep, native to the owner, delete, and vetted tools), judges each option against the catalog, attacks the leading option, and requires one real falsifying call. Searches for an earlier `Decision:` on the same question first and reuses it if its inputs did not change.

> Should we replace our custom retry service with the queue's native redelivery, or keep it?

### vet-oss

Reads the candidate's API types, delete and recovery paths, install manifest (RBAC, image digest), open issues and release pipeline from a pinned clone. A star count or README sentence proves nothing. Tools that run only in the development toolchain are judged on maintenance, pinned install, fitness, blast radius and observability.

> Find an OSS tool for scheduled backups of our PostgreSQL cluster and vet it before we pick one.

### bug-analysis

Records the bug in the turn it is found and before the first edit of a fix. A cause is never rewritten: a changed cause is a new `Analysis:` comment. Records form a ledger that can be grouped by rule id. The fix commit is `fix(#N): ...` with no closing keyword; the bug closes only when the record's `Test:` passes on the fixed product.

> The export job writes the wrong totals on retry. Analyze it and record the bug.

### harness

Reports spec gaps in the project's own documents (never decides them) and executes its build order: each item is built in its own git worktree, and a deterministic measurer alone decides what met its targets. The catalog's checks (`checks/`) run with every measurement by default, from this plugin, with nothing to configure; a project opts a rule out only in its overlay. Its tools (`bh-*`) are on `PATH` while the plugin is enabled; its entry is `bh` (`bh run`, or `bh gaps`, `plan`, `build`, `measure`, `harvest`), a program that runs every mechanical step itself and starts a headless agent job (`agents/harness-*.md`) only for judgement work. Reference: [`harness/README.md`](harness/README.md).

> Run the harness on this repo, dry run first.

## The catalog

```
catalog/
  index.md         version, loading order, readings, terms, domain and pack lists, scenario index
  base/<DOMAIN>.md one file per domain
  packs/<pack>/<DOMAIN>.md  technology packs a project opts into
  scenarios.md     generic scenarios with the base and pack rules that decide each
  CHANGES.md       one line per added or changed rule id, per base version
checks/
  index.json       every static check: rule id, pack, ecosystem, tool, file, project binds
  base/<RULE>.<ecosystem>.yml  ast-grep rules that find a base rule's breach in code
  tests/           ast-grep rule tests (valid and invalid cases) and their snapshots
```

**Checks** (`checks/README.md`) are static checks that give code evidence for some rules (no polling, publish only after commit, verify once at entry). The harness runs them by default; a project opts a rule out only in its overlay, with a reason.

**A rule row** has four columns: `ID | Rule | Provenance | Test question`. The rule is a full testable statement (must or never, its numbers, its exceptions, the case it governs). Provenance names the project file or external standard it comes from; it is not something a reviewer needs to open. The test question tells the reviewer what to look for. Pack rule ids carry the pack prefix (for example `KF-04`, `TF-02`, `PG-01`).

**Loading order.** A review reads `index.md`, then `base/<DOMAIN>.md` only for domains in scope, `base/HS.md` whenever HO is in scope, the pack files for the packs the overlay names, and `scenarios.md` when scoping by scenario. DC, PN and PR (documents, plans, process) apply to every design and plan.

**Readings.** HELD cites the location. BROKEN gives the rule id, location, failing input and fix; for DC, PN and PR the location that breaks the text is enough. NA gives one sentence. An absence is BROKEN only when the rule requires the artifact to state it. The artifact passes when no in-scope rule is BROKEN. A verdict is a review record and never gates a commit or release by itself.

**Overlay.** The overlay is your project's rules, by default `docs/agents/design-compliance.md` (another path can be named in AGENTS.md or CLAUDE.md). Its header names the base version it was built against, the packs it uses, the date, the commit of the sources read, and where verdicts are recorded (`Verdicts:`). An overlay row that names a base or pack id under "Tightens" decides in place of that rule. Where the project's version of a rule is stricter, or adds a number, write a tightening row; do not copy rules the base already states. A check the project opts out of is one line under `## Check opt-outs`: `- <RULE-ID> not-applicable: <reason>`; a line without a reason opts nothing out.

**Versioning and pinning.** The base catalog has a version in `catalog/index.md` (`Version:`) and in the plugin manifest. If an overlay was built against an older base version, a review still runs and lists the base rules added or changed since under "Catalog drift", using `catalog/CHANGES.md`. Pin the plugin to a release tag (see Install) to hold the catalog still, and move the tag when you are ready to take new rules.

## Templates

`templates/` holds the briefs and forms the skills use: `review-brief.md` (what a reviewer subagent is given), `catalog-audit.md` (the fresh-agent weakness audit of a catalog), `plan-dry-run.md` (the literal-follower dry run of a plan), `bug-record.md` (the bug record lines) and `compliance-bindings.md` (the project bindings file).

## Evals and contributing

`evals/` is the plugin's own test suite for `claude plugin eval`. Each case is a `prompt.md` (or `case.yaml`) plus `graders/*.md`:

| Group | Checks |
|---|---|
| `trigger-*` | The right skill fires for review, catalog, decision, OSS and bug prompts, and the others stay silent |
| `disambiguation` | Close pairs go to the right skill (design review or decision, tool adoption or decision, bug or plan check) |
| `no-trigger` | Ordinary requests (rename a variable, explain a function, fix a typo) fire no skill |
| `skills` | Bug records carry rule lines, decisions are reused, OSS verdicts cite rule ids |
| `accuracy` | Reviews of small sample projects find the BROKEN rules recorded in `truth.json` and locate them |
| `cost` | Reviews with an unchanged key, a changed rule or an edited section are measured against a full review |

Run it from the repository root:

```
claude plugin eval .
claude plugin eval . --case full-review
```

Results are written to `evals/results/` (git-ignored). `evals/_gen/*.py` regenerate the trigger, accuracy, cost and skill cases; run the matching script after changing a prompt in it. Run `claude plugin eval --help` for options such as `--concurrency`. An eval runs on your machine under your own credential, so evaluate only plugins you trust.

To change the catalog, follow `compliance-catalog` "Updating the base catalog": project-independent rules only, a stable id, a testable row with provenance, a version bump and a `CHANGES.md` line per id. Run the evals before sending a change.
