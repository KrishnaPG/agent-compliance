# agent-compliance

A Claude Code plugin for building software with agents: a build harness (`bh`) that runs the mechanical steps as a program and starts an agent only for judgement, plus three skills for design decisions, third-party package facts and defect records. Rules are maintained standards cited by reference plus a short list of house rules (`catalog/rules.toml`); your project adds its own in an overlay.

## Why use it

- **A program, not an agent, runs the steps.** `bh` clones, tests, measures, orders and merges; only measured targets move work on.
- **Nobody grades their own work.** Acceptance tests are written before the build by another agent; a design's options are scored by a fresh judge job that never sees the proposer's pick.
- **Facts, not verdicts, for packages.** `bh vet` keeps the deps.dev, OpenSSF Scorecard and OSV answers unchanged and prints them as facts.
- **Rules from maintained standards.** OWASP ASVS, NIST SSDF and SP 800-53, SLSA and Well-Architected are cited by id and read at their source; the house rules are the few no standard states.

## Install

For Claude Code, from a shell:

```
claude plugin marketplace add KrishnaPG/agent-compliance
claude plugin install agent-compliance@agent-compliance
```

Pin a release by adding a tag to the marketplace source: `claude plugin marketplace add KrishnaPG/agent-compliance#v1.5.2`.

For a team, put this in the project's `.claude/settings.json` so everyone gets the same pinned version:

```json
{
  "extraKnownMarketplaces": {
    "agent-compliance": {
      "source": { "source": "github", "repo": "KrishnaPG/agent-compliance", "ref": "v1.5.2" }
    }
  },
  "enabledPlugins": { "agent-compliance@agent-compliance": true }
}
```

In a running session, run `/reload-plugins` to load the plugin.

The plugin ships executables in `bin/` (the harness tools), so it installs in Claude Code only; claude.ai and Cowork do not install a plugin with a `bin/` directory.

## Quick start

1. **Optional: your own rules.** Write them as rows `| ID | Rule | Provenance | Test question |` in `docs/agents/design-compliance.md` (another path can be named in AGENTS.md or CLAUDE.md). A check the project opts out of is one line there under `## Check opt-outs`: `- <RULE-ID> not-applicable: <reason>`.

2. **Ask for a decision, a vetting or a bug record:**

   > Should we replace our custom retry service with the queue's native redelivery, or keep it?

   Skills load by their descriptions; you can also name the skill in the prompt.

## Which skill when

| Skill | Use it for | Do not use it for | Produces |
|---|---|---|---|
| `vetted-decision` | Adopt, replace, move or delete a mechanism; X or Y; who owns X | What to do next; edits of a settled design; picking a package | A MADR 4.0 record whose options a fresh `bh decide` judge scored, with objections and falsifying calls |
| `vet-oss` | Before suggesting, comparing or adopting a library, tool or image | Upgrading or using an adopted tool | `bh vet` facts per candidate from deps.dev, OpenSSF Scorecard and OSV, compared without a grade |
| `bug-analysis` | A reported defect in merged work; before a `fix` commit | A test failing in your own unmerged work; features; redesigns | A defect issue (class, cause, rule ids, siblings, regression test, falsifying call) and a `fix(#N):` commit |
| `harness` | Running the build harness: spec gaps, plan, test author, build, measure, harvest | Choosing between options; fixing one bug | `.brick-harness/` state, a scoreboard written only by the measurer, merged code |

### vetted-decision

Writes the options as a MADR 4.0 record (current design, the owner's native mechanism, delete, and vetted packages), each traced hop by hop, with no outcome. `bh decide <record>` hands a copy without its Decision Outcome section to a fresh `claude -p` judge job, which scores every option per driver and rule (`pass`, `fail`, `unknown`) and recommends one. The skill records the judge's recommendation, objections and falsifying calls as the outcome.

> Should we replace our custom retry service with the queue's native redelivery, or keep it?

### vet-oss

Runs `bh vet <system> <package> [<version>]`: the deps.dev version record (licenses, publish date, advisories, source repository), the source repository's published OpenSSF Scorecard result and the OSV vulnerabilities of that version, kept unchanged as `api_results[*]` and printed as facts. No account or key is needed; nothing is scored.

> Find a library for scheduled PostgreSQL backups and vet the candidates before we pick one.

### bug-analysis

Records a defect someone saw in merged work before the first edit of its fix: the design element at fault, the rule ids it breaks, the sibling search and a regression test that is red on the main branch. A cause is never rewritten; the fix commit is `fix(#N): ...` and the issue closes only when the test passes.

> The export job writes the wrong totals on retry since yesterday's release. Analyze it and record the bug.

### harness

Reports spec gaps in the project's own documents (never decides them) and executes its build order: a test author writes the acceptance tests first, each item is built in its own `git clone --shared`, and a deterministic measurer alone decides what met its targets. The checks in `checks/` run with every measurement. Its entry is `bh` (`bh run`, or `bh gaps`, `plan`, `measure`, `harvest`, `check`, `decide`, `vet`, `metrics`). Reference: [`harness/README.md`](harness/README.md).

> Run the harness on this repo, dry run first.

## Rules

```
catalog/
  rules.toml       maintained standards (title, version, URL) and the house rules (id, text, citations)
checks/
  index.json       every static check: house rule id, pack, ecosystem, tool, file, project binds
  base/<RULE>.<ecosystem>.yml  ast-grep rules that find a house rule's breach in code
  tests/           ast-grep rule tests (valid and invalid cases) and their snapshots
```

A rule id is a house rule id (`RL-08`) or `<standard>:<section>` (`NIST-SP-800-53:SI-7`); the standard's own text is the rule and is read at its URL, never copied. The overlay's rows add the project's own rules or tighten one. **Checks** (`checks/README.md`) give code evidence for the house rules (no polling, publish only after commit, verify once at entry); the harness runs them by default.

## Templates

`templates/` holds `plan-dry-run.md` (the literal-follower dry run of a plan), `bug-record.md` (the defect record lines) and the issue forms the harness installs.

## Evals

`evals/` is the plugin's own suite for `claude plugin eval`: each case is a `prompt.md` plus `graders/*.md` that grade an outcome, which skill loads (`tool_used`), never wording.

| Group | Checks |
|---|---|
| `trigger-*` | The right skill loads for decision, package and bug prompts, and the others stay silent |
| `disambiguation` | Close pairs go to the right skill (package or decision, decision or bug) |
| `no-trigger` | Ordinary requests, and a test failing in unmerged work, load no skill |

```
claude plugin eval .
```

The harness's outcome and cost come from `bh metrics`: change-failure rate, lead time, tokens per met slice and measurer rounds, the last two summed from the run results' `jobs[*]`. Results are written to `evals/results/` (git-ignored); `evals/_gen/triggers.py` regenerates the cases.
