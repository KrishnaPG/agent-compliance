# Lean harness: what the host and OSS do, what the harness keeps

Branch `harness-lean`. Baseline before any change: `cd harness && python3 -m pytest -q` → 333 passed, 3 skipped.

## Rules for every change

1. **The harness runs no shell itself.** Workflow scripts only orchestrate; every command is run by a host agent (cheapest model) and every reading or judging job is done by a host agent (Explore to locate, general-purpose to judge), using the user's plugins where present (codegraph, context-mode). Deterministic code stays only where determinism is the point: the measurer, merge, the scoreboard, status derivation and citation checks (a cited file:line exists and holds the quoted text).
2. **No delete-and-forget.** Every capability removed from harness code names the host feature or OSS tool (pinned version, vetted with `vet-oss`) that now provides it, and the safeguard entry (`safeguards.json`) is rewritten in place to name that mechanism and the test that proves it. Only dead code (no caller, no capability) is deleted without a replacement.
3. **No gates.** Facts are reported, never turned into refusals. Existing refusals stay as they are until the owner rules (findings H-2, H-3).
4. **Owner-requested capabilities are thinned, never removed:** the configurable any-tracker interface (Beads and GitHub first; decision 0001), learning from answers (SG-16), value order and finish-before-start (SG-17), the work packet (SG-18), the safeguard register (SG-01 to SG-19).
5. **Big output never crosses an agent.** A CLI writes its full result to a file under `.brick-harness/out/` and prints a small JSON summary (ids, counts, the file path). Agents read the file themselves. This replaces checksums, sliced re-reads and paging; a workflow test proves a 1,000-item state passes through a file intact before the checksum code goes.
6. Commits on `harness-lean`; tests green after each wave; no `rm` (use `mv` to a `trash/` outside the repo, then `git add -A`).
7. **Done** = a toy project completes a full harness run (gaps, plan, build, measure, harvest) from this branch, not only a green pytest.

## Map: capability → owner after the change

| Capability (where) | SG | Owner after the change | Wave |
|---|---|---|---|
| Copy-pasted workflow prelude, ~170 lines × 6 (`workflows/*.js`) | 07 | One ~25-line helper per workflow: `run(cmd, schema)` = a host agent (haiku) runs one CLI and returns its schema-validated summary | 1b |
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

## Waves

- **1a** (parallel, separate git worktrees): core (`bhcore.py` and every `bin/` wrapper except the tracker ones, one agent); tracker (`bhtracker.py`, adapters, tracker CLIs, decision 0001, one agent). Stable boundary: `bhtracker` keeps `gap_facts`, `parent_is_feature`, `show_resolver`; `bhcore` keeps the Python `state(cfg)` dict, `value_queue` and the names `bhtracker` imports.
- **1b**: workflows and `SKILL.md`, on top of 1a's CLI summaries.
- **2**: OSS replacements, each vetted with `vet-oss` at a pinned version, one small agent each.
- **Then**: toy full run from the branch; the approved steps 1–9 are planned on the lean base.
