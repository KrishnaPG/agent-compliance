# Fixture format

One directory per given key. A row names a fixture; its file is found by the rule below. A missing or malformed fixture is an error in the run (not a red test). Fixtures need no network, CI, bot account or paid model call. All JSON files may be written as YAML.

Field names follow the owner's d0 map: `acceptance[*]` (each with `id`), `verifier.targets[*]`, `verifier.rules[*]`, `verifier.acceptance_paths`, `constraints.declared_paths`, `paved_road.test_paths`, `jobs[*].kind` (`agent` or `program_step`), `jobs[*].role` (agents) or `jobs[*].step` (program steps), `jobs[*].tokens`, `schema_version` and `command` on every result JSON, id-keyed collections as arrays of objects with `id`. The keyword library reads every other assumed name from `../keywords/contract.json`.

A fixture is never edited to change a row's outcome; a keyword bug is reported to the engine owner.

## repo: `repo/<name>/<state>/`

`<name>` is `toy`, `node_toy` or `project` (`plugin` is the tree under test; no fixture). `repo/<name>/base/` is the full tree of the base state. Any other state is an overlay: its files are copied over `base`, and a file `.atdd-delete` lists paths (one per line) to remove. The result is committed on branch `main` and tagged `base`.
An optional `meta.json` in a state dir (not copied into the repo): `{"remote": true}` adds an `origin` remote (a local bare repo).
`plugin` states: `candidate` is the tree itself; any other value must be a git ref of the tree (its files are used).

## planted: `planted/<plant>/` (or `planted/<plant>@<repo name>/` when it differs per repo)

An overlay in the same format as a repo state (files copied over the repo; `.atdd-delete`). `where` decides how it is applied: `candidate_commit` (default) commits it on branch `candidate` on top of `base` and checks that branch out; `working_tree` leaves it uncommitted; `plan_commit` commits it on `main`, moves tag `base` to it and rebases `candidate`. A plant of the plugin repo is applied to a copy of the tree, never to the tree.
Tests a plant adds may use `$ATDD_OUTSIDE` (a directory outside the checkout, with a file the suite digests) in their environment.

## recorded_model: `recorded_model/<fixture>.json`

```json
{"replies": [ {"events": [ {...stream-json object...}, ... ], "exit": 0},
              {"stdout": "raw text instead of events", "exit": 0} ]}
```
The stub `claude` (first on PATH) answers the Nth launch with reply N and logs every launch (`argv`, `cwd`, `stdin`) to `$ATDD_MODEL_LOG`. A launch past the last reply exits 3 with a teaching message. With no recorded_model given, every launch exits 3. Stream-json events use Claude Code's shapes (`system` init, `assistant`, `result` with `usage.input_tokens` and `output_tokens`).

## recorded_api: `recorded_api/<service>/<fixture>.json`

`<service>` is `github`, `scorecard`, `deps_dev` or `osv`.
```json
{"exchanges": [ {"operation": "createIssue", "method": "POST", "path": "/repos/o/r/issues",
                 "match_body": "optional substring of the request body",
                 "status": 201, "body": {...response JSON...}} ]}
```
A local server answers each request with the first unused exchange whose `method`, `path` prefix and `match_body` fit; no match returns 404 and logs operation `unmatched`. Every request is logged; `api_call` counts by `operation`. The program is pointed at the server through the service's URL environment variables (see `contract.json`, `env.api_urls`); real hosts are unreachable (dead proxy).

## hook_input: `hook_input/<event>.<tool>.<agent_type>.<packet>.<target>.<touch>.json`

The five enum values from the row, then `touch` (`first` when the row omits it), joined by dots, for example `PreToolUse.Edit.builder.registered.outside_packet_paths.first.json`. The file is the exact hook-input JSON Claude Code sends on stdin. For `touch: repeat` the hook is run twice with it and the second run is read.

## packet: `packet/<fixture>/<variant>.json`

A schema-valid (or deliberately invalid, per `variant`) packet with the d0 fields: `id`, `parent_issue`, `tier`, `goal`, `applies[*]`, `constraints.declared_paths`, `acceptance[*].{id,traces_to,verification}`, `verifier.{rules,targets,acceptance_paths}`, `paved_road.{test_paths,dependency_command,check_command}`, `definition_of_done`. Its `id` names it. The file is copied to `.brick-harness/packets/<id>.json` in the repo (unless that path is already tracked, so a plant can supply an edited one) and to the orchestrator's authoritative copy outside the repo. `$packet_sha256`, `$acceptance_ids` and `$packet.<path>` (the value at that packet path, for example `$packet.verifier.acceptance_paths`; a list matches when any element does) are read from it.

## config: no fixture file

`absent` removes `.brick-harness/config.json`; `override` writes it holding only `key` (dotted) = `value`.

## host: `host/<condition>.json`

```json
{"env": {"NAME": "value"},
 "stubs": {"docker": {"exit": 0, "stdout": "text", "stderr": "text"}},
 "hide": ["claude"],
 "files": {"relative/path": "file text written into the repo"}}
```
All keys optional. `env` is set for the program; `stubs` create executables first on PATH; `hide` creates a shim that exits 127 "command not found"; `files` are written (uncommitted) into the repo. One file per condition; a condition with nothing to stub still needs `{}`.

## recorded_answer: `recorded_answer/<question>.<answer>.json`

Any JSON object (extra fields allowed, `{}` is valid). The harness writes `{ "<question>": {"answer": "approve|decline", ...file fields} }` to `$BH_ANSWERS_FILE`; the program reads its answers there and appends one JSON line per prompt it puts to the owner to `$BH_PROMPT_LOG` (`questions_asked` counts those lines).

## history: `history/<fixture>/<period>/`

`period` is `pre_v2` or `v2` (`both` uses both, in that order). Files are copied to `.brick-harness/history/<period>/`. A file `commits.json` there is replayed (then removed): `[{"message": "...", "date": "2026-01-01T00:00:00+00:00", "files": {"path": "text"}}]` makes one commit each with that author and committer date. Issue and sub-issue events, and job records, are plain files in the directory (`issues.json`, `jobs.json`) that the program reads offline.

## Other fixture directories

- `snapshots/<name>.txt`: an approved golden output for `snapshot`. A missing snapshot fails the test; snapshots are written by a person, never by the suite.
- `schemas/<id>.json`: a pinned public schema named by a row (for example `sarif-2.1.0`), vendored once.

## Assumed names that d0 has not fixed

See `../keywords/contract.json` (result and file locations, the `bh` and step command lines, hook selection, the program's git identity, the packet's config-change declaration). A fixture that depends on one of them: the packet variants (`config_change`: expressed as `pyproject.toml` in `constraints.declared_paths`), `hook_input` files (hook command names), `host` file stubs for the run lock, builder settings (`.brick-harness/builder-settings.json`, Claude Code settings shape with `permissions.allow|deny`, `sandbox.filesystem.allowWrite|denyWrite` and an optional `messages.<Tool>` denial text).
