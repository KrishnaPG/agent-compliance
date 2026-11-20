# Lean harness: what the host and OSS do, what the harness keeps

Branch `harness-lean`. Baseline before any change: `cd harness && python3 -m pytest -q` → 333 passed, 3 skipped.

## Rules for every change

1. **No agent in the mechanical path.** Everything mechanical (git, tests, measuring, merging, ordering, citation checks, searches for a known pattern, file moves) runs as code: existing OSS CLIs and libraries first, installed at pinned versions by the harness's own setup; our own code only for a verified gap. An agent is started only for work no mechanical means can do (reading documents for meaning, deriving the plan and slices, judging gaps, building an item, finding duplicate helpers, review), or to hand the run's result back to the owner. Consequence: the orchestrator is a program, not a Workflow-tool script (a Workflow script cannot run a command without spawning an agent). It runs every mechanical step itself and starts each agent job headless with the host's own CLI (`claude -p --json-schema --model --max-budget-usd --plugin-dir`, Claude Code 2.1.329; or claude-agent-sdk 0.2.186, chosen by vet-oss), each with only the tools that job needs and a schema for its output. The main session's part in "run the harness" is one command and the report of its result, plus asking the owner the questions the result lists.
2. **No delete-and-forget.** Every capability removed from harness code names the host feature or OSS tool (pinned version, vetted with `vet-oss`) that now provides it, and the safeguard entry (`safeguards.json`) is rewritten in place to name that mechanism and the test that proves it. Only dead code (no caller, no capability) is deleted without a replacement.
3. **No gates.** Facts are reported, never turned into refusals. Existing refusals stay as they are until the owner rules (findings H-2, H-3).
4. **Owner-requested capabilities are thinned, never removed:** the configurable any-tracker interface (Beads and GitHub first; decision 0001), learning from answers (SG-16), value order and finish-before-start (SG-17), the work packet (SG-18), the safeguard register (SG-01 to SG-19).
5. **Big output never crosses an agent.** A CLI writes its full result to a file under `.brick-harness/out/` and prints a small JSON summary (ids, counts, the file path). Agents read the file themselves. This replaces checksums, sliced re-reads and paging; a workflow test proves a 1,000-item state passes through a file intact before the checksum code goes.
6. Commits on `harness-lean`; tests green after each wave; no `rm` (use `mv` to a `trash/` outside the repo, then `git add -A`).
7. **Done** = a toy project completes a full harness run (gaps, plan, build, measure, harvest) from this branch, not only a green pytest.

## Map: capability → owner after the change

| Capability (where) | SG | Owner after the change | Wave |
|---|---|---|---|
| Copy-pasted workflow prelude, ~170 lines × 6 (`workflows/*.js`) | 07 | Gone with the workflows: the orchestrator program runs commands itself (rule 1) | 1b |
| State checksums, FNV-1a `canon`/`checksum`, sliced re-reads, `--part/--value`, `pending_page`, `_decision`, `limits.decision_items` paging (`bhcore`, `bh-state`, `prelude.js`) | 07, 15 | Rule 5: state file + small summary; Workflow tool's schema-validated agent output | 1a/1b |
| Prompts pasting `JSON.stringify(state…)` and restating `RULES` | 07, 03 | Paths in prompts; rules live once in `skills/harness/SKILL.md` sections the agents load | 1b |
| Own worker `pool` and slot bookkeeping | 08 | Workflow `parallel()`/`pipeline()` (host queues concurrency); slot = index | 1b |
| Builder branch pass (`bh-branch` agent) and `git reset --hard` | 01 | Unchanged in wave 1 (a worktree builder cannot move branches); revisit after the toy run shows what `isolation:'worktree'` forks from | — |
| Regex keyword search over every `.md` for design areas (`checklist_mentions`, `design-checklist.json`), section finder, `_docs` | 03 | Gaps agent (host) reads the documents, cites file:line; `bh-gaps` verifies the citations | 1a |
| Markdown link/anchor check (`_link_target`) | — | lychee (pinned after vet-oss) run by a host agent; findings cited and verified like any gap | 2 |
| Hand-written JSON-schema subset validator | — | jsonschema 4.26.0 (already the tests' cross-check) | 2 |
| JUnit parsing, bench value extraction | 06 | junitparser / jq through the configured extractor command, after vet-oss; zero-tests and finite-number checks stay | 2 |
| Bench repeat runs, median, noise | 06 | The bench tool's own repeats and spread (pytest-benchmark, hyperfine) read through the extractor; register entry rewritten | 2 |
| Flaky detection by tree key | 05 | Thin: key = `git rev-parse <ref>:<path>` (git); fact kept | 1a |
| Met-to-unmet history file, `oscillating` | 04 | Thin: history = the committed scoreboard's `git log`; detection kept as a small function over it | 1a |
| Scope facts (paths outside the item, unlisted public names) | 02 | Thin: `git diff --name-only` against owned paths; public names via the pinned ast-grep already used for SG-19 | 1a |
| Lockfile readers (six formats), dependency facts | 09 | Each ecosystem's own CLI or syft, after vet-oss; fact kept | 2 |
| Sizing notes, INVEST and flow rollups | 14 | Plan agent judges against `config.sizing`; measured new lines from `git diff --numstat`; fact kept | 1a |
| Ranking (`bh-rank`), re-review input | 11–13 | Thin: rank key stays (a sort); re-review input is `git diff <since>` read by the reviewer agent | 1a |
| Gaps and scoreboard markdown renderers | 11 | Workflow result leads with the product view (approved); `gaps.md` written from `gaps.json` by a thin template | 1a |
| Decision records, `bh-answer`, learning, overlay candidates | 16 | Thin: owner is asked by the main session (AskUserQuestion) between workflows; `bh-answer` records D-n; matching kept as a citation check | 1a |
| Value order (`value_queue`, fractions) | 17 | Kept; simplified when step 4 (value order from the confirmed plan) is built | later |
| Work packet (`bh-brief`, passage digests, staleness) | 18 | Kept; staleness from `git diff <plan sha>`; simplified in its step | later |
| Tracker layer (`bhtracker.py` 1,290 lines, adapters, `bh-work`/`bh-file`/`bh-admit`/`bh-reconcile`) | 15 | Thin interface: adapters stay data (command templates for `bd` 1.3.4 and `gh`), run by host agents; the files tracker → `bricks.json` order when no tracker is configured; the git-claim fallback → isolated worktree branches plus the tracker's own claim; decision 0001 rewritten in place | 1a |
| `ast-grep` downloader and sha check (`bhrules`, `checkers.json`) | 19 | ast-grep from a pinned package after vet-oss | 2 |
| `bh-init` | — | Onboarding inside the harness run (approved step 1) | later |
| `in_place` measuring, `read_scoreboard`, `_in_head`, scoreboard self-digest | — | Dead or self-protection of our own file: deleted (git history protects the scoreboard) | 1a |

## Waste removed with the orchestrator (wave 1b unless marked)

Tokens:

- **W1 Minimal agent context.** Every agent job starts `claude -p --bare` with only `--plugin-dir`, its agent, its allowed tools and `--json-schema`; no user CLAUDE.md, memory, other plugins, MCP servers or hooks.
- **W2 Plan once.** The confirmed plan is stored; re-planning starts only when a cited document's content changed (git digests of the cited files), never per run.
- **W3 Incremental gaps.** Only documents changed since the last gaps commit (`git diff`) are reviewed; earlier verdicts are reused by key, as the catalog's review cache does.
- **W4 Model per job by the host, not by code.** The plugin ships agent definitions (`agents/*.md`: planner, gaps reader, builder, harvester, each with model, effort and tools in frontmatter); a job is `claude -p --agent <name>`; host built-ins (Explore) are used where they fit. Each job carries `--max-budget-usd`.
- **W5 Cache-friendly prompts.** Jobs of one kind share an identical prefix (agent definition, rules, schema); the item's packet comes last.
- **W6 Stop on no progress.** A round that moved no measured number ends the run (scoreboard comparison), before `max_rounds`.

Time:

- **W7 Measure only what changed.** A result is keyed by the item's tree sha and target digest; an unchanged key reuses the recorded result without running tests (the flaky key of SG-05 becomes the cache key).
- **W8 Run only affected tests.** The command gets the item's paths and its dependents' (`affected()`), not the whole suite.
- **W9 Warm environments.** One environment per slot for the whole run; an item's commands go to a remote host in one batch.
- **W10 Overlap.** Setup (tool install, test-runner item) runs alongside the gaps and plan agent jobs.

Owner effort:

- **W11 One ranked batch of questions per run**, asked between runs, recorded, never re-asked.
- **W12 No commands for the owner** (self-onboarding, approved).

Code (wave 1a/2):

- **W13 One `bh` command with subcommands** instead of 14 `bh-*` scripts with their own argument boilerplate.
- **W14 One set of JSON Schemas** serves data validation (jsonschema), agent output (`--json-schema`) and tests.
- **W15 Safeguard proofs from the tests.** Tests carry a pytest marker with their SG id; the register's test list is generated, so it cannot drift.

## Waves

- **1a** (parallel, separate git worktrees): core (`bhcore.py` and every `bin/` wrapper except the tracker ones, one agent); tracker (`bhtracker.py`, adapters, tracker CLIs, decision 0001, one agent). Stable boundary: `bhtracker` keeps `gap_facts`, `parent_is_feature`, `show_resolver`; `bhcore` keeps the Python `state(cfg)` dict, `value_queue` and the names `bhtracker` imports.
- **1b**: the orchestrator program replaces `harness/workflows/*.js` and `lib/prelude.js` (vet-oss first: existing OSS orchestrators for headless coding agents, the `claude -p` CLI vs claude-agent-sdk); one command per phase plus `run`; agent jobs only per rule 1; `SKILL.md` shrinks to "run the command, report the result, ask the listed questions".
  - Vetted (2026-11-20, base catalog 1.3.0): **stdlib `asyncio` driving the host's `claude` CLI** (2.1.329): `create_subprocess_exec` per job, `Semaphore(N)`, `wait_for` deadline, wait on process exit, result file keyed by tree sha + schema digest so a restart skips finished jobs. claude-agent-sdk 0.2.186 wraps the same CLI and adds dependencies (fallback only). Rejected: ComposioHQ agent-orchestrator 0.15.3 (daemon, second state owner), vibe-kanban 0.1.46 (server), chipping-orchestrator 0.15.0 and openai/symphony 0.0.3 (polling), claude-squad 1.0.20 (interactive tmux, AGPL), Snakemake 9.27.2 (second state owner), Prefect 3.9.4 / DBOS 3.6.0 (database).
  - `--bare` authenticates only by `ANTHROPIC_API_KEY` or `apiKeyHelper` (no OAuth): with a key, jobs run bare (W1); without one, jobs run with `--setting-sources "" --strict-mcp-config --disable-slash-commands` (CLAUDE.md and memory still load). Not every user has a key, so both are first-class and the choice is mechanical, never asked: the orchestrator picks bare mode when `ANTHROPIC_API_KEY` is set or an `apiKeyHelper` is configured, else login mode; if a bare job exits with an authentication error it re-runs that job once in login mode and records the switch. The run result names the mode used and the tokens per job, so the cost of login mode is visible, not guessed. The toy run proves the result JSON (`structured_output`, cost), budget overrun behaviour and plugin agents under `--bare`.
- **Setup**: one harness setup step installs every pinned tool it uses (Python deps via uv lock; ast-grep, lychee, jq and the tracker CLIs via their package managers or release checksums), run inside onboarding, never by a human.
- **2**: OSS replacements, each vetted with `vet-oss` at a pinned version, one small agent each.
- **Then**: toy full run from the branch; the approved steps 1–9 are planned on the lean base.
