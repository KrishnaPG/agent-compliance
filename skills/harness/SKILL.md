---
name: harness
description: Run the build harness on a project: report spec gaps in its own documents, then build its pending build order with isolated builders and a deterministic measurer that alone decides what is met. Load when asked to run the harness, report spec gaps, plan, build, measure or harvest build-order items, or set up `.brick-harness/`.
---

The harness reports gaps in the project's own documents and builds its build order; it invents no architecture. Its entry is `bh` (plus `bh-answer`, `bh-measure`) on `PATH`; reference: `${CLAUDE_PLUGIN_ROOT}/harness/README.md`. `bh` runs every mechanical step itself and starts agent jobs (`agents/harness-*.md`) only for judgement; never start them or do their work, and never edit code, tests or `.brick-harness/` by hand.

**Paved road, no fail-at-exit gates.** Rules bind every author. The paved road makes them easy to meet; it never makes them optional. Rules and acceptance tests come up front, the author self-checks while writing, and review teaches. Nothing fails finished work after the fact. Local hooks on a work branch only warn; they never block. Main (the release) is protected: every change enters through its entry check: its tests pass and its review has no open S1 or S2 finding. An owner override is logged (spec §0 P7).

## One item

Planner (item, packet, tier) -> test author (tests, red on main) -> builder (sealed clone, packet read-only, self-check `bh check`) -> `bh-measure` alone decides met -> main's entry check admits. `bh step <name> --item ID` runs one program step.

## Run it

1. No setup step: `bh run` infers everything from the project's own files and prints each source. Its one setup question (forms, presets, hooks, an unknown owner) is asked once; on yes rerun `bh run --approve`; owners via `bh run --owner PATTERN=OWNER`.
2. `bh run` from the project root (`bh --dry-run run` changes nothing). One phase: `bh gaps`, `bh plan`, `bh measure` or `bh harvest`. A restart continues.
3. Report the result as `bh` prints it: what is sellable at HEAD and what is next; then met, stuck and gaps. The full result is the JSON file named on its last line.
4. Ask the owner the questions listed under `owner_questions` (one batch, each with its evidence and `resolve_with`). Record each answer with `bh-answer` (`bh-answer --help`), then run `bh` again; an answered question is never asked twice.
