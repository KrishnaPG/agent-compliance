---
name: harness
description: Run the build harness on a project: report spec gaps in its own documents, then build its pending build order with isolated builders and a deterministic measurer that alone decides what is met. Load when asked to run the harness, report spec gaps, plan, build, measure or harvest build-order items, or set up `.brick-harness/`.
---

The harness reports gaps in the project's own documents and executes its build order; it invents no architecture. Its entry is one command, `bh` (and the `bh-*` tools it composes), on `PATH` while the plugin is enabled; the reference is `${CLAUDE_PLUGIN_ROOT}/harness/README.md`. `bh` is a program: it runs every mechanical step itself (git, measuring, merging, committing, ordering) and starts an agent job only for judgement work (gaps, plan, one item's build, duplicate helpers, the review of a feature that became sellable). The rules of each job live in the plugin's `agents/harness-*.md`; you do not start those agents and you do not do their work.

## Run it

1. No harness config yet (`.brick-harness/`): run `bh-init` with the project's documents (`bh-init --help`), commit the result, and read the gaps it reports for its placeholders. The rule catalog and its checks are this plugin's own; set `standards.catalog` to a path only to use another catalog.
2. Run `bh run` from the project root (`bh --dry-run run` first lists the agent jobs it would start and changes nothing). One phase instead: `bh gaps`, `bh plan`, `bh build`, `bh measure`, `bh harvest`. It picks its own auth mode (API key or `apiKeyHelper`: bare jobs; otherwise login mode) and runs the jobs headless with the host's `claude` CLI; do not ask the owner about either. A restart continues by itself: a job that finished is not run again.
3. Report the result as `bh` prints it, product view first: what is sellable at HEAD, the current slice, what is next and why; then what was met, what is stuck and why, and the gaps; then the auth mode and the cost per job. The full result is the JSON file named on its last line; the gap report is the markdown file in `.brick-harness/`.
4. Ask the owner the questions the result lists under `owner_questions` (one `AskUserQuestion` batch, each question with its evidence and `resolve_with`). Record each answer with `bh-answer` (`bh-answer --help`), then run `bh` again; an answered question is never asked twice.
