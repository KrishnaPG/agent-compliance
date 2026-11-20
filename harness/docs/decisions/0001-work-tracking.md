# 0001 Work hierarchy and tracking (SG-15, SG-16)

Decided 2026-11-19. The vetting of trackers, the survey of planning methods and the full judgment (options, rule rows, attack, falsifying runs) are kept with the project that ran them (its `tools/harness-evidence/0001/`).

## Decision

- **Hierarchy:** goal → feature → item. Only items are measured; feature and goal progress is a roll-up computed when read. Item kinds: `brick`, `system`, `change`.
- **Split:** child items own disjoint paths. The parent keeps its targets and depends on every child, so it is measured after them; a child that misses part of the parent shows up as an unmet parent. The harness never splits a package on its own; it reports that for the owner.
- **Idempotent pick-up:** the key is (item id, targets digest, tree of its paths at HEAD) plus the measured scoreboard. An item's id is derived from its tracker ref, so taking an item twice does nothing.
- **Bounded tokens:** the full state goes to a file (`bh-state` writes `state.json` and prints a small summary); the orchestrator reads `bhcore.state(cfg)` directly and no agent receives every item.
- **What git keeps:** what to build and how it is measured: `bricks.json`, `targets.json`, the scoreboard. Status comes only from the scoreboard at the git sha.
- **What the tracker keeps:** intent, order, claims and history. The tracker is configured, never hard-coded.
- **Tracker interface:** six operations, the ones the harness calls, each mapped in config to a command that prints JSON in the shapes of `schema/tracker.schema.json`:
  - `ready` (limit, parent, type) and `show` are required; `list`, `claim`, `close` and `reopen` are used when the adapter has them;
  - `ready` is the tracker's own filter (`bd ready`, a `gh issue list --search` query), never computed by the harness;
  - callers: `bh-admit` (ready, list, claim), `bh-gaps` (show), `bh-reconcile` (show, close, reopen);
  - not kept, because nothing calls them: `create`, `link`, `defer`, and the adapters' capability flags with their fallbacks;
  - measure, build and merge never call the tracker.
- **Adapters** are data files in `adapters/` (command templates, the field paths of the entry, the state and type names); the config names one, may override any command, or points at an adapter file of its own, so any tracker with a CLI that prints JSON works.
  - **Beads 1.3.4**, pinned by sha256 (the `bd` binary is checked at run time; a mismatch is not run and the tracker is unreachable for that run); goal, feature and item map to epic, feature and task.
  - **GitHub Issues** through gh 2.94.0 or later (sub-issues, issue types, blocked-by).
- **No tracker configured:** the work list is `bricks.json` in build and value order (`bh-state`); `bh-admit` and `bh-reconcile` do nothing. There is no files tracker.
- **Claims:** the adapter's own claim command where it has one (`bd update --claim` is atomic; a gh assignee is soft, and the ready query skips assigned entries). Builders work on isolated worktree branches `bh/<item>`, which git will not check out twice, so no item is built twice in a run. There is no claim of the harness's own.
- **Done only from measurement:** `bh-reconcile`, the only caller of `close` and `reopen`, runs after the scoreboard commit at HEAD and before admission.
  - It closes an entry whose item is measured met at HEAD (reason: the sha), acting as the claim holder.
  - It reopens an entry that was closed while its item is not met.
  - It touches only entries mapped to admitted items, deletes nothing, and lists every mismatch as a fact.
- **Admission (rolling wave, WIP):** at most `horizon.items` admitted items not met. `ready` is asked for the room left; each entry is claimed before it is written to the plan, with an id derived from its ref; an entry claimed by this actor but not yet written is adopted.
- **Findings** live in `.brick-harness/gaps.json`. Nothing files them to a tracker automatically (no workflow called `bh-file`, so it is gone); when the owner wants them there, the tracker's own CLI (`bd create`, `gh issue create`) is run from the gaps report.
- **No gates:**
  - every mechanism is structure, fact, order or limit;
  - an item with an open owner question is blocked by that gap;
  - pin mismatches, stale claims, claims held elsewhere and missing refs are facts.
- **Methods:**

  | Method | Enters as |
  |---|---|
  | WBS | parent measured after its children (structure) |
  | Rolling wave | horizon K (limit) |
  | Agile hierarchy | tracker types mapped by the adapter to goal, feature and item |
  | INVEST | Independent = cycles, Valuable = feature link, Estimable = `est_loc`, Small = SG-14, Testable = blocked by gap (facts and fields) |
  | SPIDR | a split names its kind (spike, path, interface, data, rules) in `split_kind` |
  | DoD | targets met |
  | Kanban | horizon as the WIP limit; pull by ready plus claim; cycle time and throughput as facts from scoreboard timestamps |
  | HTN | only leaves run; a split parent is only measured |
  | Package principles | sizing facts (SG-14) |
  | Retrospective | SG-16 |

- **SG-16, learning from the owner's answers:**
  - An answered blocking question becomes a decision record D-n naming the kinds and areas it covers.
  - Gap and plan agents get the records as settled inputs (SG-03).
  - A new gap of a covered kind and area cites D-n. The tool checks that D-n exists and covers the gap, and lists the gap as "answered by D-n" instead of blocking.
  - Repeated answers in one area move into the project's rule overlay: the report lists the area as a candidate and the plan phase hands it to the project's overlay build.
  - The report counts, per cycle, the owner's questions opened, answered and re-asked after a covering decision existed.

## Why

- Measurement stays the only source of done. The tracker's open or closed state is a projection with one writer in the harness, so a close by a person or a merge keyword is corrected and reported, never trusted.
- Any project keeps its own tracker, with no second list: with none configured, `bricks.json` is the list and nothing else is kept.
- The tracker CLIs already do what the harness once re-implemented: `bd ready` and a gh search query filter ready work, `bd update --claim` is an atomic claim, `bd create` and `gh issue create` file issues. The harness keeps only the mapping of their output (data) and the one rule they cannot know: close and reopen follow measurement.
- Trade-off of dropping the claim of our own: without a tracker that has an atomic claim (Beads), two clones on different machines can admit and build the same entry; git prevents it only inside one clone and run. A project that works from several machines uses Beads, or gives each machine its own goal.
- Beads gives hierarchy, typed dependencies, `ready -n`, atomic claim and defer out of the box, and its churn is contained by the sha256 pin. GitHub covers projects that live there.
- Re-asked owner questions waste the owner's time. Recorded decisions make an answer settle a kind of question, not just one instance of it.

## Built

- SG-15: the state file with a small printed summary, `change`/`refs`/`split_from`, roll-up and facts, the tracker interface with its two adapters (`lib/bhtracker.py`), reconcile, admission, INVEST and flow facts, split kinds.
- SG-16 (decision records, `bh-answer`, answered-by, overlay candidates, per-cycle counts), SG-17 and SG-18 (see `safeguards.json`).
- Tests prove it against a stateful stand-in tracker (`tests/fake_tracker.py`), fixture `bd` and `gh` commands, and real Beads when the pinned `bd` is on PATH.

## Unverified

- **Real Beads** with this thinned adapter has not been run since the change (the tests skip without the pinned `bd`); the earlier run covered the same `ready`, `show`, `claim`, `close`, `reopen` and `list` commands.
- **Beads claim across clones** that do not share one store; Beads server mode has not been run.
- **GitHub adapter:**
  - no run with gh 2.94.0 or later (the ready query `no:assignee -is:blocked type:Task` was accepted by gh 2.46 against a public repository, the JSON fields `issueType`, `parent` and `blockedBy` were not);
  - whether `blockedBy` carries its state in `list`;
  - issue types on repositories owned by a user;
  - the goal (`tracker.goal`) is not applied to the stock gh ready query; set `tracker.commands.ready` to add a parent qualifier.
- **Token and CPU bound** of `bh-state` at 10, 100 and 1,000 items.
