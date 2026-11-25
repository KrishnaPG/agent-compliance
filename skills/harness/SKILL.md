---
name: harness
description: Run the build harness on a project: report spec gaps in its own documents, then build its pending build order with isolated builders and a deterministic measurer that alone decides what is met. Load when asked to run the harness, report spec gaps, plan, build, measure or harvest build-order items, or set up `.brick-harness/`.
---

The harness reports gaps in the project's own documents and executes its build order; it invents no architecture. Its entry is `bh` (plus `bh-init`, `bh-answer`, `bh-measure`), on `PATH` while the plugin is enabled; the reference is `${CLAUDE_PLUGIN_ROOT}/harness/README.md`. `bh` is a program: it runs every mechanical step itself (git, measuring, merging, committing, ordering) and starts an agent job only for judgement work. The rules of each job are in `agents/harness-*.md`; you do not start those agents or do their work.

## One item

1. The planner derives the item, targets and work packet; the program sets the tier from the declared paths: `mechanical` or `design-affecting`.
2. The test-author job writes the acceptance tests in the project's own framework, before any build; the program records them red on main.
3. The program writes the packet (acceptance, targets, rules with teaching messages, paved road incl. the self-check `bh check`) into the builder's clone, read-only.
4. The builder builds in its sealed clone; the program commits and merges.
5. `bh-measure` alone decides met. `bh step <name> --item ID` runs one program step with no agent (`bh step --help`).

## Run it

1. No `.brick-harness/` yet: run `bh-init` (it infers the build order, ecosystem and test command from the project's files; `bh-init --help`), commit the result.
2. Run `bh run` from the project root (`bh --dry-run run` first lists the agent jobs and changes nothing). One phase instead: `bh gaps`, `bh plan`, `bh measure`, `bh harvest`. A restart continues by itself.
3. Report the result as `bh` prints it: what is sellable at HEAD and what is next; then met, stuck and gaps. The full result is the JSON file named on its last line.
4. Ask the owner the questions listed under `owner_questions` (one batch, each with its evidence and `resolve_with`). Record each answer with `bh-answer` (`bh-answer --help`), then run `bh` again; an answered question is never asked twice.
