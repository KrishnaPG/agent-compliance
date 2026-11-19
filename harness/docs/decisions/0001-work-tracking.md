# 0001 Work hierarchy and tracking (SG-15, SG-16)

Decided 2026-11-19. The vetting of trackers, the survey of planning methods and the full judgment (options, rule rows, attack, falsifying runs) are kept with the project that ran them (its `tools/harness-evidence/0001/`).

## Decision

- **Hierarchy:** goal → feature → item. Only items are measured; feature and goal progress is a roll-up computed when read. Item kinds: `brick`, `system`, `change`.
- **Split:** child items own disjoint paths. The parent keeps its targets and depends on every child, so it is measured after them; a child that misses part of the parent shows up as an unmet parent. The harness never splits a package on its own; it reports that for the owner.
- **Idempotent pick-up:** the key is (item id, targets digest, tree of its paths at HEAD) plus the measured scoreboard. An item's id is derived from its tracker ref, so taking an item twice does nothing.
- **Bounded tokens:** agents get a capped decision part (not-met items in build order, counts, a `more` count and paging), never every item.
- **What git keeps:** what to build and how it is measured: `bricks.json`, `targets.json`, the scoreboard. Status comes only from the scoreboard at the git sha.
- **What the tracker keeps:** intent, order, claims and history. The tracker is configured, never hard-coded.
- **Tracker interface:** nine operations, each mapped in config to a command that prints JSON in the shapes of `schema/tracker.schema.json`:
  - `ready` (limit, parent, type), `show`, `create` (parent, deps, labels, metadata), `link`, `claim`, `close`, `reopen`, `defer`, `list`.
  - Each adapter declares its capabilities: `atomic_claim`, `hierarchy`, `defer`, `compaction`, `ready_filter`.
  - Measure, build and merge never call the tracker.
- **Adapters** are data files in `adapters/`; the config names one and may override any command.
  - **Beads 1.3.4**, pinned by sha256:
    - the tarball is checked against the release's `checksums.txt`;
    - the `bd` binary's sha256 is checked at run time;
    - goal, feature and item map to epic, feature and task.
  - **GitHub Issues** through gh 2.94.0 or later (sub-issues, issue types, blocked-by).
  - **Files** (`.brick-harness/work/`, one committed file per entry), only when no tracker is configured.
- **Fallbacks** for a missing capability:
  - **No atomic claim:** the harness pushes a commit of its own (naming the item and actor) to the item's branch `bh/<item>` on origin, create-only (`--force-with-lease=<ref>:`); git lets exactly one claimant win. The ref stays while the item is in the plan.
  - **No ready filter:** ready is computed from `list` (open, not deferred, item type, no open dependency, no open child, not claimed).
  - **No hierarchy, no defer:** labels.
  - **No compaction:** reads stay bounded by limits and paging.
- **Done only from measurement:** `bh-reconcile`, the only caller of `close` and `reopen`, runs after the scoreboard commit at HEAD and before admission.
  - It closes an entry whose item is measured met at HEAD, acting as the claim holder.
  - It reopens an entry that was closed while its item is not met.
  - It touches only entries mapped to admitted items, deletes nothing, and lists every mismatch as a fact.
- **Admission (rolling wave, WIP):** at most `horizon.items` admitted items not met. `ready` is asked for the room left; each entry is claimed before it is written to the plan, with an id derived from its ref.
- **Findings:** `bh-file` creates ranked findings from the committed `gaps.json` with `discovered-from` links. It looks each one up by key through `list` before it creates.
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
- Any project keeps its own tracker, with no second list: the files adapter exists only when there is no tracker.
- Claims use native compare-and-swap: Beads' claim, or git's create-only ref update. There are no marker files, and no lease timers.
- Beads gives hierarchy, typed dependencies, `ready -n`, atomic claim, defer and metadata out of the box, and its churn is contained by the sha256 pin. GitHub covers projects that live there.
- Re-asked owner questions waste the owner's time. Recorded decisions make an answer settle a kind of question, not just one instance of it.

## Built

- SG-15: the capped decision part, trimmed NEED lists, `change`/`refs`/`split_from`, roll-up and facts, the tracker interface with its adapters and fallbacks, reconcile, admission, filing, INVEST and flow facts, split kinds.
- SG-16 (decision records, `bh-answer`, answered-by, overlay candidates, per-cycle counts), SG-17 and SG-18 (see `safeguards.json`).
- Beads 1.3.4 (pinned `bd`, one clone) and the create-only claim race (two clones, bare origin) ran on the experiments VM: every operation, admission, reconcile and filing through real Beads, exactly one winner per round.

## Unverified

- **Beads claim across clones** that do not share one store: such clones must declare `atomic_claim` false, and Beads server mode has not been run.
- **GitHub adapter:**
  - no run with gh 2.94.0 or later;
  - whether `blockedBy` carries its state in `list`;
  - issue types on repositories owned by a user;
  - search lag for the filing key.
- **Create-only push against a hosted origin.** Verified only against a bare repository.
- **Token and CPU bound** of `bh-state --part decision` at 10, 100 and 1,000 items.
- **Duplicate filing** from two clones at once.
