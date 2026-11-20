# harness

The build harness of the agent-compliance plugin (skill `/agent-compliance:harness`). It does two things and invents no architecture. The project owner
decides architecture and standards in the project's own documents; the harness reads them.

- **A. Report spec gaps, never decide them.** Features without acceptance checks or numeric
  targets, targets without a cited source line or a measuring command, items without a
  contract, duplicate items, contradictions, dangling references, untracked open items,
  helper jobs with no library, and design areas no document settles (the gaps agent reads the
  documents and cites file:line; the CLI verifies the citations). Output:
  `.brick-harness/gaps.json` and `gaps.md`, each gap with file:line evidence, tagged
  `owner-decides` or `fixable`.
- **B. Execute the project's own build order.** Each builder works in its own git worktree
  and environment slot on branch `bh/<item>`. Only the deterministic measurer scores; an
  item advances only on measured targets; a retry gets its previous commit and the numbers
  it missed. Harvest reports duplicated helpers. State lives in `.brick-harness/`,
  committed with the code.

## The orchestrator (`bh`)

`bin/bh` is the one entry: `bh run`, or one phase (`bh gaps`, `bh plan`, `bh build`, `bh measure`,
`bh harvest`); `--config` and `--dry-run` (list the agent jobs, write nothing, spend nothing)
come before or after the subcommand. `lib/bhorch.py` is a Python program, not a script for a
host tool: it runs **every mechanical step itself** (git worktrees and branches, state,
`bh-measure` per item as a process, merging, committing, tracker reconcile and admission, gap
merging, ordering, stopping) through `bhcore`/`bhtracker` or the CLIs, and starts an **agent
job only for judgement work**.

| Phase | Mechanical (code) | Agent job (agent file) |
|---|---|---|
| gaps | mechanical checks, `bh-gaps` merge (a finding whose file:line or quote does not resolve is rejected), commit | `gaps`: `harness-gaps-reader`, read only. A re-review is given only the documents' diff since the last review and the open findings (`bhcore.review_input`); decisions and the owner's answers are settled inputs |
| plan | tracker reconcile and admit, gap merge, commit | `plan`: `harness-planner` derives items, targets (each citing the line that states its number), contracts and work packets; adds only what is missing |
| build | commit plan, measure unmeasured ready items at HEAD (code may already exist), worktree per item from HEAD, work packet written from `bhcore.work_packet`, retry merge of the previous commit, `bh/<item>` branch set from the worktree's HEAD, measure, merge what the scoreboard lists as met, re-measure merged items and dependents at HEAD | `build`: `harness-builder`, one per item still unmet, in its own worktree and environment slot |
| harvest | settled-pick check against the catalogue, gap merge, commit, measure the applied refs | `harvest_find`: `harness-harvester` (duplicated helpers); `harvest_apply`: `harness-builder` applies a pick the catalogue already settles |
| review | the brief of a feature that became sellable (`bhrules.feature_review`), finding recorded by `bh-rank` | `review`: `harness-reviewer`, read only (git's read-only commands), a fresh reader that did not build it |

`run` = gaps, plan, rounds of build+measure (stop at `max_rounds`, at a budget, or when a round
moved no measured number: the scoreboard's numbers are compared before and after), the review of
each feature that became sellable, `bh-gaps --source cycle` (every item not met is `stuck` with
its reason: `build-failed`, `no-change`, `unmet`, `not-attempted`, `budget`, `oscillating`),
harvest, measure.

**The run result** (`<measure_out>/run-result.json`, and a short text print) leads with the
product view: `product` (sellable at HEAD with slices, what became sellable this run, the
current slice, the next feature and why: earliest slice, then value per remaining cost),
then `status` (met, stuck, gap counts), `owner_questions` (the owner-decides gaps no decision
answers: the main session asks them and records each with `bh-answer`), `auth` (mode at start
and end, fallbacks), `jobs` (agent, mode, ok, skipped, cost, tokens, duration, error per job)
and `totals`.

**Agent jobs.** Each job is the host's CLI, headless, one process:

    claude -p --agent agent-compliance:<agent> --json-schema <schema> --output-format json \
      --max-budget-usd <budgets.job_usd> --no-session-persistence --permission-mode dontAsk \
      --allowedTools <the agent file's tools> --add-dir <jobs dir> <plugin root> <auth flags>

with `cwd` the item's worktree for builders. The prompt (stdin) is a short instruction plus
file paths; the job's input is a JSON file under `<measure_out>/jobs/` it reads itself, and big
state never passes through a prompt. The agent files (`agents/harness-*.md`: model, effort,
tools in the frontmatter; the rules, stable text first so jobs of one kind share a prefix) hold
each job's rules; `models` and `efforts` in the config override the model and effort per phase
(`gaps`, `plan`, `build`, `harvest`, `review`). Outputs are checked against `schema/jobs.schema.json`
(one schema per job, `$ref`s inlined for the CLI) with `bhcore.validate`. At most
`concurrency` jobs and measurements run at once (an `asyncio.Semaphore`; the slot number of
a builder is its environment slot); a job has a deadline (`budgets.job_timeout_s`, default
1800 s: terminate, then kill) and a spend cap; every wait is on a process exit, there is no
sleep, poll or retry loop.

**Auth modes**, chosen mechanically and never asked: `ANTHROPIC_API_KEY` set, or an
`apiKeyHelper` in `~/.claude/settings.json` (or `CLAUDE_CONFIG_DIR`), the project's
`.claude/settings.json` or `settings.local.json` -> **bare**: `--bare --plugin-dir <plugin>`
(with `--settings <that file>` for a helper): no hooks, memory, CLAUDE.md, other plugins or
MCP servers. Otherwise **login**: `--setting-sources "" --strict-mcp-config
--disable-slash-commands --plugin-dir <plugin>` (CLAUDE.md and memory still load). A bare job
that fails with an authentication error is re-run once in login mode and every later job runs
in login mode; the result records the switch, the mode and the cost and tokens of every job
(from the CLI's JSON result), so the cost of login mode is visible.

**Restarts.** A job's result is saved as `<measure_out>/jobs/<key>.json`, key = digest of the
job, its agent file, its schema and its input core (for a builder the HEAD tree and the
feedback of the previous attempt; for gaps and plan the content of the project documents, the
owner's answers and the overlay, so unchanged documents are not read again). A restart finds
the file and skips the job; a failed job leaves `<key>.error.json` and runs again.

**Tests without a model.** `tests/fake_bin/claude` is a small executable put first on `PATH`
by `tests/test_bhorch.py`: it reads its arguments and stdin, answers per agent name from a
spec file, commits a builder's files in its worktree, and can fail authentication in bare
mode, overrun the budget or fail. A paid toy run still has to prove what it cannot: that plugin
agents load under `--bare` and `--disable-slash-commands`, the real result JSON
(`structured_output`, `total_cost_usd`, `usage`) and the budget-overrun result.

**Skills reused, not copied.** Jobs get this plugin's skills by file path in their input (a headless
job may have skills disabled): `compliance-review` is the method of the gaps and review jobs (read only; it
returns findings and writes no verdict record), `vet-oss` is the OSS rule builders follow; `vetted-decision`
is named on `owner-decides` gaps and `bug-analysis` on `unmet-after-rounds` gaps, reported, never run.

## The measurer and its tools

`bin/` is on `PATH` while the plugin is enabled. Workflow scripts have no shell, so a cheap
agent runs each tool and returns its JSON.

- `bh-measure --item ID@REF --slot N`: checks the ref out in a clean worktree, runs the
  item's env_setup, test (JUnit XML) and bench (JSON or CSV extractor), and compares raw
  numbers with `targets.json` from the invoking checkout. It fails closed on: no targets, a
  pending command, a non-zero exit, a timeout, zero tests, an unreadable or odd result and a
  missing or non-finite metric. No gates: a ref's edits never refuse or fail it. Before
  measuring, the plan commit's (HEAD's) plan and `protected` paths and the held-out ref
  `refs/brick-harness/holdout` are laid over the ref's checkout (a guarded file the ref added
  is deleted), so edits there have no effect; they are listed under the item as
  `ignored_edits`. Facts recorded on each result in `scoreboard.json`, never changing a
  status: `scope` (paths outside the item's `path`/`paths`; public Python names the
  contract's optional `exports` list lacks), `dependencies` (lockfile packages added or
  changed since the ref's fork, not named in `standards.stack`, or with a new major
  version), `flaky` (the same tree, keyed by git blob shas of the item's files, the guarded
  files, the held-out cases and the targets, both passed and failed; last 6 runs of the
  last 300 trees kept), `noise` (a bench target's `runs` repeats the bench; the median is
  the value; min/max recorded; `within_noise` lists targets whose value lies inside that
  spread) and `environment` (a system item's test runs through
  `environments.<name>.run`, `{cmd}` being the quoted command, when `commands.test.environment`
  names it; else `local`). `notes` say when a ref lacks the plan commit. Each result is
  written as it lands: at HEAD it is *current*; at any other ref it is a *candidate*, which
  never replaces a met current result. An unreadable scoreboard is never
  overwritten.
- `bh-merge`: merges every met candidate not yet in HEAD, in build order, with
  `git merge --no-ff`. A catalogue-only conflict is resolved by a schema-checked JSON union;
  any other conflict is aborted and recorded, so the item is rebuilt with "conflicts with
  HEAD at <paths>". After each merge the plan and protected paths are restored to their
  pre-merge state in a follow-up commit. It prints the items to re-measure at HEAD.
- `bh-branch --item ID --ref SHA`: builders run in isolated worktrees and cannot move
  branches, so they return their commit and this sets `bh/<ID>` to it from the main checkout:
  the commit must exist and be new; created or fast-forwarded, otherwise refused. What it
  holds under plan or protected paths is not judged here.
- `bh-state [--affected REF]`: the whole state, derived from files, written atomically to
  `<measure_out>/state.json` (git-ignored); the CLI prints a small summary (`file`, `head`,
  `plan_head`, `all_met`, `counts` per status, `ready`, `ready_system`, `unmet`, each id list
  capped at 25 with a `*_more` count, `gaps`, `problems`) and agents read
  the file themselves (the orchestrator calls `bhcore.state` directly).
  Item status is `met` only when the result's ref is in HEAD and the item's paths (with its
  dependencies' and the protected paths) are unchanged since; otherwise `stale`,
  `met-unmerged`, `conflict`, `unmet`, `unmeasured`, or `blocked` (with the gap ids that
  stop it: no targets, a pending command, a failing env_setup). `features` and `merged`
  are the parts plan and harvest read.
- `bh-commit`: commits only harness files, under a lock; refuses during a merge and when
  a target in HEAD was dropped or changed (the owner commits that).
- `bh-gaps`: recomputes the mechanical gaps and merges findings; an empty list clears a
  source's earlier findings.
- `bh-rank`: orders findings (or gaps) by one fixed key and drops nothing: impact ids (more
  first), severity S1 to S4, evidence `reproduced`, `trigger`, `theoretical`, then id; a
  missing field ranks last (`schema/finding.schema.json`). `--add FILE|-` records findings by
  id in `.brick-harness/gaps.json` as entries with `source: "finding"` (only with `--write`;
  gaps.json is the one place findings live; the owner or an agent files them with the tracker's
  own CLI, `bd create` or `gh issue create`, when wanted); the gaps report lists them in their own section, and they are not
  counted as spec gaps. Bare `bh-rank` ranks them; `--open` lists the open ones with the
  review gaps; `--review-input` prints what a re-review gets (document diff since
  `reviewed_head`, capped at 20000 characters, plus open findings). `bh-gaps --source review
  --write` records the review's head in gaps.json. A finding is never work by
  itself: a build round works only on items the measurer reports not met (an unmeasured ready
  item is measured at HEAD first; stale, conflict and met-uncommitted items are redone), so a
  finding becomes work only as a failing test or target.
- `bh-init`: writes `.brick-harness/config.json` with placeholders and never overwrites;
  `--missing features` opts in to starter documents.

**Time limits.** One `bh-measure` call runs up to three commands, each bounded by
`commands.timeout_s`, so keep 3 x `timeout_s` under an agent's shell limit (about 10
minutes), or the agent starts it as a background task and waits for its completion.
Nothing in the harness sleeps or polls. Tests or benches can run elsewhere (a VM, a GPU
box): point the command at the project's own script that leaves results under `{out}`
(the toy's `remote_test.sh` stands in for one); `"pending": "<why>"` marks one not
written yet.

## Safeguards

Gaps are listed in rank order. Per measurement the measurer notes each target met or not in `out/history.json`; a target of one item that went met to unmet after another item went met, twice, is reported `oscillating` (both named) and never changes a status.

No gates: gates invite gaming. An item moves on only when its targets are measured met. `safeguards.json` registers the pitfalls the harness guards against and how, each by structure (gaming is impossible by construction), fact (recorded and reported, never scored), order (ranks work, never filters it) or limit (caps cost, lists what is left), with the catalog rules it serves, its status and the tests that prove it. `tests/test_safeguards.py` fails when an entry claims more than its tests show, or when a gate is anything but a mechanism being removed.

Work hierarchy (decision `docs/decisions/0001-work-tracking.md`): goal, feature, item; only
items are measured. Item `kind` is `brick`, `system` or `change`; `refs` names tracker refs
an item resolves; `split_from` marks a child of a split, and the parent depends on each child
(added when read) so it is measured after them. The gaps report carries, derived when read,
`facts` (shared path; the per-feature met/total is the state's `features` part). `bh-gaps --source cycle` lists every
item not met as stuck (the run passes only what it attempted; an oscillating target is named),
capped in its printed report with `stuck_more`; the full list is in `gaps.json`.

Tracker (SG-15 M5 to M12, `lib/bhtracker.py`, decision 0001): the project's tracker is
configured (`tracker.adapter` in the config), never hard-coded. Six operations (ready, show,
list, claim, close, reopen), each a shell command of an adapter (`adapters/beads.json`,
`github.json`, or a file the config names; any command can be overridden in the config) that
prints JSON; the adapter's `fields` say where each entry field is in it, and the output is
checked against `schema/tracker.schema.json`. `ready` is the tracker's own filter (`bd ready`,
a `gh issue list --search` query). Beads 1.3.4 is pinned by sha256: a `bd` that does not match
is not run and the tracker is unreachable for that run. With no `tracker.adapter` there is no
tracker: `bricks.json` in build and value order is the work list and `bh-admit` and
`bh-reconcile` do nothing. A claim is the adapter's own (`bd update --claim` is atomic; a gh
assignee is soft); builders work on isolated branches `bh/<item>`, which git will not check out
twice. Measure, build and merge never call the tracker.
`bh-admit [--write]` takes ready entries of `tracker.goal` into `bricks.json` as items of kind
`change` (id derived from the ref) within `horizon.items` minus the items not met, claiming
each first, in `value_queue` order for entries that are items already and the tracker's order
for the rest. `bh-reconcile [--write]` is the only caller of close and reopen: after the
scoreboard commit, an open entry of an item measured met at HEAD is closed (acting as its
claim holder) and a closed entry of an item not met is reopened; it never deletes. The gaps report adds facts: tracker mismatches; the plan agent judges
INVEST and size against `config.sizing` (no heuristic code); a split parent is measured but
never built.
Claim leases of Beads (`lease_expires_at`) are Beads' own; the harness never reclaims.

Value order (SG-17): `.brick-harness/features.json` holds the owner's slice and value per
feature, each with a cited source (`schema/features.schema.json`). `bhcore.value_queue(cfg,
state) -> list[str]` orders the items not met: earliest slice, then value per remaining cost
(`est_loc`, 1 when absent) over the acceptance item's dependency closure; features without
slice, value or a resolving source rank last and are listed as unvalued. While a started
feature has a ready item, later features' items are not ready (`held_by`). The gaps report and
run result carry sellable at HEAD, if-stopped-today, cost to the next sellable feature.

Work packet (SG-18): items carry `context` (`{path, lines: "a-b"}` citations) and `rules`;
`bh-brief ITEM` assembles the packet from the plan commit (passages with sha256, dependency
contracts, pins, rules via `packet_rules`) and the builder reads nothing else; what it lacks is
a `missing-context` finding. Packet tokens over `sizing.packet_tokens` (1600) and passages
changed since the plan commit (`stale-context`) are facts in the report.

Rule checks (SG-19, `lib/bhrules.py`): the catalog is this plugin's own (`catalog/`, `checks/`)
unless `standards.catalog` is a path to another; when it ships `checks/index.json` (`{rule, pack, ecosystem, tool, file, binds}`), every
measurement runs the checks and `rules.violations == 0` is one more target of every item,
counted over the item's owned paths and the files its ref changed. Base checks always run;
ecosystem and pack checks when the stack is detected (pyproject.toml or `*.py`: python;
package.json or tsconfig.json: typescript; `*.sql` or a migrations directory: sql and the
postgresql pack). `checkers.json` pins ast-grep by version and release sha256; the harness
downloads it once to `~/.cache/brick-harness/bin/` and a sha mismatch means it is not run;
without a checker the metric is absent and the target unmet, with the reason in `errors`. No
project config is needed: a project opts a rule out only in its overlay, in the catalog's form
(`- RULE-ID not-applicable: reason` under `## Check opt-outs`; no reason opts nothing out; listed as a fact); a bound project fact is the check's one allowed place and the check scans every module except those: `entry_modules` (inferred
from `APIRouter`, `FastAPI(`, `Router(`) and `outbox_modules` (files with SQL `INTO`/`FROM`/`UPDATE`/`TABLE`/`EXISTS` followed by a table name holding `outbox`, a `class ...Outbox...`, `__tablename__ = "...outbox..."`, or `Table(`/`pgTable(`/`sqliteTable(`/`mysqlTable(` with such a name); a fact the code does not show skips that check and is an
owner-decides gap. Suppression markers a ref adds are a fact per item. The packet's rules are
the item's own `rules` then judgment rules (not enforced, not `embodies` of a brick it uses)
chosen by its tags, ranked by findings, at most `limits.packet_rules` (8). A feature that
becomes sellable in a run gets one review of its diff by a fresh agent (`bh-brief --feature`,
`compliance-review`), findings recorded by `bh-rank`. The report lists class shares
(enforced, embodied by a brick's `embodies`, judgment) and check candidates (judgment rules
broken in two or more findings). Tests use `checks.checker` (a fake command) and a fixture catalog.

Learning (SG-16): `bh-answer` writes the owner's answer as `.brick-harness/decisions/D-n.json`
(kinds, areas, source). A gap of a covered kind and area cites it (`answered_by`) and is listed
as answered; a bad cite is a fact; a covered gap citing nothing is listed as re-asked; neither
blocks. Areas with `learning.overlay_after` (3) decisions are overlay candidates, handed to the
overlay build by the plan; an overlay line `RULE-ID ... covers: AREA` covers like a decision. The
report counts questions opened, answered and re-asked per cycle.

## Layout and config

```
.brick-harness/
  config.json  .gitignore (out/)
  targets.json  bricks.json  contracts/  catalogue.json   # plan, committed
  scoreboard.json                                        # measurer only, committed
  gaps.json  gaps.md                                      # bh-gaps and bh-rank, committed
  out/  (history.json: per measurement, each target met or not)  # raw output, ignored
```

Paths resolve from the project root (`root` in the config, else the parent of
`.brick-harness/`, else the config's directory); every path the tools print is relative to
it. Config (`schema/harness.config.schema.json`):

- `paths`: the project's documents (read only) and the harness files; `sections` names a
  heading inside one.
- `standards`: `catalog` (optional: a path to another catalog; unset is this plugin's), `base_version`, `packs`; the overlay is found as the skills find it (bindings file, then `docs/agents/design-compliance.md`); placeholders are gaps.
- `commands`: `test`, `bench`, `env_setup`, `timeout_s`, and how agents call the tools;
  placeholders `{item} {brick_path} {out} {slot} {port_base} {workdir} {root} {ref}`. An item
  can override `test`, `bench`, `env_setup`. The commands are part of what a result was
  scored against: changing them makes results stale.
- `protected`: paths the measurer takes from the plan commit whatever a ref holds there
  (acceptance tests, bench, runner scripts).
- `environments`: name -> `{run}` template for `commands.test.environment`; `standards.stack`:
  the stack record (package names, optionally `==version`).
- `catalogue_jobs`
  (default `["testing"]`) and `na` (area or job id -> why it does not apply). Rule content
  belongs to the project, not to the plugin.
- `standards.decisions`: paths of recorded decisions, settled inputs for the gaps and plan
  agents; a gap that would reopen one sets `reopens`, and the gaps report lists it in its own
  section for the owner (nothing is accepted or rejected).
- `budgets`: `run_tokens` and `run_usd` (what the run may spend, summed from each job's result; the
  run ends before a round when one is reached and what is left is listed in `stuck` with
  reason `budget`), `job_usd` (each job's `--max-budget-usd`: a number, or an object keyed by
  phase with a `default`; 2 when absent) and `job_timeout_s` (a job's deadline, 1800 s when
  absent). `max_rounds` stays the round limit.
- `sizing`: `min_loc` (default 150) and `max_loc` (2000), against an item's `est_loc` or
  measured lines (min only for a met item). Items may also carry `purpose`, `hides`,
  `interface`, `consumers`, `oss_checked`; the gaps report lists sizing notes (a size outside
  the thresholds, a purpose that may join two jobs, one consumer, an OSS tool that fits) for
  the owner, as facts that change no status.
- `slots`, `concurrency`, `max_rounds`, `models` and `efforts` per phase, `ecosystems`.

Targets cite `source` as file:line of the line stating the number; `tests.failed == 0`,
`tests.errors == 0` and `tests.passed >= 1` need none. Items may list `paths` beside `path`.

## Install and try it

```
claude plugin marketplace add KrishnaPG/agent-compliance
claude plugin install agent-compliance@agent-compliance
```

For one session, `claude --plugin-dir <plugin root>` works too. `examples/toy` is a CSV-to-JSON CLI whose
`json-writer` has a contract, targets and tests but no code, so a run must build it. Run `/agent-compliance:harness` from the toy
and run `bh gaps`, then `bh run` (`bh --dry-run run` first lists the agent jobs).

## Develop

Layout: `bin/` sits at the plugin root, the one place a plugin's executables are put on `PATH`;
everything else of the harness is under `harness/`; the agents are at the plugin root (`agents/`).
`python3 -m pytest` in `harness/` (stdlib plus pytest and jsonschema) covers the measurer and its fail-closed cases, every scoring bypass, the
status table, the toy end to end through the bin tools (build on `bh/json-writer`, measure,
merge, re-measure, commit, `all_met`), a project in a repo subdirectory, the gap checks,
schemas, the orchestrator against a fake `claude`, a grep that bans sleep/poll loops, and project-term
neutrality. Project terms are read from `BH_DENY_TERMS` (a file of regexes) or
`~/.config/brick-harness/deny-terms.txt`; that check is skipped when neither exists. The

## OSS checked

SG-19 checker (looked up 2026-11-19): ast-grep 0.51.3 (MIT, active, release asset digests
published) runs one rule file with `scan --rule FILE --json PATHS` and needs no project config;
its linux x86_64 asset is pinned by sha256 in `checkers.json`. A per-language linter set
(ruff, eslint, sqlfluff) needs project config; Semgrep needs a rules registry or login.

Tracker interface (pinned): Beads 1.3.4 (tracker, by sha256; `bd ready`, `bd update --claim`), gh 2.94.0 or later (GitHub Issues; no atomic claim; ready is a search query), git 2.53.0 (worktree branches `bh/<item>`); jq and JSONPath libraries and tracker SDKs not used (one path syntax in stdlib, no tracker bound) (see `lib/bhtracker.py`).

Adopted: the host's `claude -p` CLI driven by stdlib asyncio (vetting in `docs/lean-plan.md`), `git worktree`, plugin agents, skills, plugin `bin/`; JUnit XML and the
JSON/CSV output of existing bench tools. Rejected for this loop, because each decides "done"
by a checklist, the agent's report or an LLM verdict, with no gap report with resolvable
evidence, numeric targets or harvest: Spec Kit v1.4.2, OpenSpec v2.1.0, cc-sdd v3.1.0,
BMAD v6.12.4, Task Master 0.43.1, ruflo v3.78.0, SuperClaude v4.3.0, CCPM,
compound-engineering v3.38.2, ralph-loop, ralph-orchestrator v2.12.0, Anthropic's
autonomous-coding quickstart, OpenHands, LangGraph, CrewAI, Temporal, DBOS. `lib/bhcore.py`
lists what was checked for its own code. Measurer safeguards (looked up 2026-11-19):
pytest-rerunfailures 16.7, flaky 3.8.1 and pytest-flakefinder 1.1.0 retry or repeat inside one
run (a retry loop, and no memory of the same tree across runs); hyperfine and pytest-benchmark
repeat one command but do not compare its median with project targets; deptry 0.25.1 checks
imports, not what a ref added to a lockfile. Stdlib covers the rest (`ast`, `statistics`,
`shlex`) and git itself (`checkout <rev> -- paths`, `ls-tree`) does the overlay.
For ranking, review input, target history and sizing
notes: stdlib sorting, `git diff`, one JSON file; no tracker, SARIF or metrics store (see
`lib/bhcore.py`) orders findings by impact on measured targets or reports a target going met
to unmet after another item's change without a server. For value order, decision records and
the packet (named, not version-pinned; none adopted): WSJF scoring, tracker rank fields, ADR
tools and repo packers each hold only part; stdlib `fractions`, `hashlib` and `git show` cover
the rest.
