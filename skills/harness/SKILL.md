---
name: harness
description: Run the build harness on a project - report spec gaps in its own documents, then build its pending build order with isolated builders and a deterministic measurer that alone decides what is met. Load when asked to run the harness, report spec gaps, plan, build, measure or harvest the build-order items, or set up `.brick-harness/`. Do NOT use to review a design or plan (compliance-review), to choose between options (vetted-decision) or to fix one bug (bug-analysis).
---

The harness reports gaps in the project's own documents and executes its build order; it invents no architecture. Its tools (`bh-*`) are on `PATH` while the plugin is enabled; the reference is `${CLAUDE_PLUGIN_ROOT}/harness/README.md`.

## Run it

1. No `.brick-harness/config.json` yet: run `bh-init` with the project's documents (`bh-init --help`), commit the result, and read the gaps it reports for its placeholders. The rule catalog and its checks are this plugin's own; set `standards.catalog` to a path only to use another catalog.
2. Start the workflow the request names, with the config path as its argument (try `{"configPath": ".brick-harness/config.json", "dryRun": true}` first):
   - `agent-compliance:harness-gaps`: report spec gaps, with file:line evidence.
   - `agent-compliance:harness-plan`: items, targets and contracts from the build order.
   - `agent-compliance:harness-build`, then `agent-compliance:harness-measure`: one round of building and measuring.
   - `agent-compliance:harness-harvest`: report duplicated helpers.
   - `agent-compliance:harness-run`: all of the above, with build and measure rounds while items still advance.
3. Start each run fresh; never resume a recorded run. Report the workflow's result as it returns it: what was met, what is stuck and why, and the gaps for the owner (`.brick-harness/gaps.md`).

The sections below are for the workflow's phase agents. A phase agent follows only the section its prompt names and starts no workflow.

## Plan

1. Read the build order (its configured section), the status file, features, acceptance and existing contracts. The work list comes from them; the harness invents no item, number or interface.
2. Items file: one entry per build-order item not yet tracked (`id`, `job`, `kind` brick or system, `depends_on`, `path` if stated, `contract`, `source` = file:line in the build order). Items marked done in the status file are still listed; the measurer decides whether they are met.
3. Targets file: only numbers and checks stated in a project document, each with `source` = file:line of the line that states the number (the gaps phase checks the number is on that line). Every item gets at least `tests.failed == 0` and `tests.passed >= 1`, which need no source (that the item has tests is not a design choice).
4. Contracts: one file per item whose input and output a document states; cite the source in the file.
5. Never change or remove existing entries; never change a target of an item whose status is met.
6. Everything you cannot derive (no numeric target, no interface, unclear dependency) goes in `not_derivable` as a gap with file:line evidence and a tag.
7. Work packet: give each new item `context`, a list of `{path, lines: "a-b"}` citing the exact passages of the project documents a builder needs, and `rules`, the catalog rule ids that apply (pick them by the scoping of `agent-compliance:compliance-review`, by reference; copy none of its steps). Write citations, never copied text: `bh-brief ITEM` extracts the passages (with their sha256) and the builder gets only that packet.
8. Slice and value of a feature (`.brick-harness/features.json`) are the owner's data with a cited source: never estimate them. A feature without them is reported as unvalued and ranks last.

## Build

1. Reset your worktree to the commit named in your prompt. On a retry, merge the previous commit named there and read the numbers it missed (actual vs required) and the measurer's errors; a "conflicts with HEAD" error means resolve against HEAD.
2. Your first command is `bh-brief ITEM` (named in your prompt). Its work packet is all you need: job, contract, targets, commands, the cited spec passages, the contracts of the items you depend on, your owned paths, the stack pins and the rules. Do not read other documents (the catalogue is the one file you may add to). Anything you need that the packet does not hold, return in `missing_context` (one line each; the harness records it as a finding of kind missing-context); do not look it up elsewhere.
3. Set up your environment slot with the command in your prompt; use only your slot's ports and work dir.
4. Helper jobs: use the catalogue's library. For a job it lacks, follow the OSS rule in your prompt, add the entry (job, ecosystem, library, used_by, why) to the catalogue and the dependency to the ecosystem's manifest so the lockfile records the version.
5. Write the item so the configured test command passes. The protected paths in your prompt (acceptance tests, bench programs, runner scripts) are fixed: the measurer ignores your edits to them (it lays the plan's own over your checkout) and lists them. Add your own unit tests only outside them.
6. Run the test command yourself while working. You do not decide whether the item passes: the measurer runs your commit in a clean checkout.
7. Do not edit targets, the item list, contracts, the config, the scoreboard or the project's own documents; do not run the measurer.
8. Commit everything, do not create or move any branch (the harness points bh/<item> at your commit), and return the full commit sha (the one you reset from if you made no commit) and the catalogue entries you added.
9. A review finding is not your work unless a failing test or target shows it: fix what the measurer reports unmet; report anything else with severity, evidence and impact instead of changing code for it.

## Harvest: find

- Start from the state's catalogue duplicates (one job, several libraries) and from items' own helper code doing the same job.
- For each, give file:line evidence and the items involved. Name a `pick` only when the catalogue names exactly one library for the job and ecosystem; the workflow checks that against the catalogue, and everything else is reported as a gap for the owner. Skip a duplicate that is two lines long.

## Harvest: apply

- Reset your worktree to the commit in your prompt; change the affected items to the catalogue's pick; record them in its `used_by`.
- Leave the protected paths alone; the measurer ignores edits there and re-checks every item the commit touches, and their dependents, against unchanged targets.
- Commit; return the sha.
