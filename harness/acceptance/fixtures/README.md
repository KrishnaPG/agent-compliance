The catalog is frozen: new work adds one small plain pytest file per task under harness/tests, never a new key.

# Fixture format

One directory per given key. A row names a fixture; its file is found by the rule below. A missing or malformed fixture is an error in the run (not a red test). Fixtures need no network, CI, bot account or paid model call. All JSON files may be written as YAML.

Field names follow the owner's d0 map: `acceptance[*]` (each with `id`), `verifier.targets[*]`, `verifier.rules[*]`, `verifier.acceptance_paths`, `constraints.declared_paths`, `paved_road.test_paths`, `jobs[*].kind` (`agent` or `program_step`), `jobs[*].role` (agents) or `jobs[*].step` (program steps), `jobs[*].tokens`, `schema_version` and `command` on every result JSON, id-keyed collections as arrays of objects with `id`. The keyword library reads every other assumed name from `../keywords/contract.json`.

A fixture is never edited to change a row's outcome; a keyword bug is reported to the engine owner.

## repo: `repo/<name>/<state>/`

`<name>` is `toy`, `node_toy` or `project` (`plugin` is the tree under test; no fixture). `repo/<name>/base/` is the full tree of the base state. Any other state is an overlay: its files are copied over `base`, and a file `.atdd-delete` lists paths (one per line) to remove. The result is committed on branch `main` and tagged `base`.
An optional `meta.json` in a state dir (not copied into the repo): `{"remote": true}` adds an `origin` remote (a local bare repo).
`plugin` states: `candidate` is the tree itself; any other value must be a git ref of the tree (its files are used).

## planted: `planted/<plant>/` (or `planted/<plant>@<repo name>/` when it differs per repo)

An overlay in the same format as a repo state (files copied over the repo; `.atdd-delete`). `where` decides how it is applied: `candidate_commit` (default) commits it on branch `candidate` on top of `base` and checks that branch out; `working_tree` leaves it uncommitted; `plan_commit` commits it on `main`, moves tag `base` to it and rebases `candidate`. `main_commit` commits it on `main` after the candidate branched and leaves tag `base` and `candidate` alone, so main and the candidate diverge (give the candidate plant first). A plant of the plugin repo is applied to a copy of the tree, never to the tree.
Tests a plant adds may use `$ATDD_OUTSIDE` (a directory outside the checkout, with a file the suite digests) in their environment.

## recorded_model: `recorded_model/<fixture>.json`

```json
{"replies": [ {"events": [ {...stream-json object...}, ... ], "exit": 0},
              {"stdout": "raw text instead of events", "files": {"src/a.py": "text"}, "exit": 0} ]}
```
The stub `claude` (first on PATH) answers the Nth launch with reply N and logs every launch (`argv`, `cwd`, `stdin`) to `$ATDD_MODEL_LOG`. A launch past the last reply exits 3 with a teaching message. With no recorded_model given, every launch exits 3. `files` (paths relative to the launch's cwd, the builder's clone) is what the agent's Write tool would leave: the builder's change the program then commits. Stream-json events use Claude Code's shapes (`system` init, `assistant`, `result` with `usage.input_tokens` and `output_tokens`).

## recorded_api: `recorded_api/<service>/<fixture>.flows`

`<service>` is `github`, `scorecard`, `deps_dev` or `osv`. A fixture is one mitmproxy flow file: the requests the program makes and the responses to replay, recorded from the real service.

Recording: `ATDD_REDACT=1 mitmdump -s keywords/mitm_addon.py -w <fixture>.flows`, then run the program once with `HTTPS_PROXY=http://127.0.0.1:8080` and `SSL_CERT_FILE=~/.mitmproxy/mitmproxy-ca-cert.pem`. The addon replaces `Authorization` and cookies before the flow is saved. To name the call for `api_call`, add the response header `X-Recorded-Operation: createIssue`; the proxy removes it before the program sees the response.

Replay: mitmproxy (pinned in `harness/run_tests.py`) answers from the flow files with `--server-replay`, `connection_strategy=lazy`, `upstream_cert=false` and `keepserving=true` (mitmdump otherwise exits once the recordings are replayed); the addon refuses every upstream connection (`server_connect`), because mitmproxy's own `server_replay_extra=kill` forwards again once the last recording is spent. Each recorded response answers one request whose method, URL and body equal the recorded request; a repeated request takes the next recording of it. A request with no recording is never forwarded: the proxy answers 502 and it is logged with operation `unmatched`. Every request is logged; `api_call` counts by `operation`. The program is unchanged: it reaches the real hosts through the proxy variables (`HTTP(S)_PROXY`) and trusts the proxy's CA through the variables in `contract.json`, `env.ca_bundles`. One proxy serves all services of a row.

## hook_input: `hook_input/<event>.<tool>.<agent_type>.<packet>.<target>.<touch>.json`

The five enum values from the row, then `touch` (`first` when the row omits it), joined by dots, for example `PreToolUse.Edit.builder.registered.outside_packet_paths.first.json`. The file is the exact hook-input JSON Claude Code sends on stdin. For `touch: repeat` the hook is run twice with it and the second run is read.

## Running the rows

`harness/acceptance/run.sh <tree> [pytest args]`. The builder launch probe refuses an account in the docker group (R10). On a host whose account is in it, `run.sh` re-runs itself as the same account with its supplementary groups dropped (`sudo -n setpriv --clear-groups`, environment kept); without passwordless sudo, run the rows from an account outside that group.

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

## snapshot: `snapshots/<slice>/<row id>[<name>].txt`

The approved output a `snapshot` row compares with, kept by syrupy (pinned in `harness/run_tests.py`). A missing file makes the row red; nothing is recorded unless a person runs the rows with `--snapshot-update` and commits the reviewed file.

## Names outside the field list

Field names are fixed in `docs/atdd/fields.yaml`; fixtures use only those. Everything else the keywords assume (where files are written, the `bh` and step command lines, hook selection, the program's git identity) is one line each in `../keywords/contract.json`. Fixtures that depend on it: `hook_input` files (the hook command names), builder settings (the launch's own `.brick-harness/launch/<clone>.settings.json`: a `builder_action` first launches the builder for the row's packet through `bh step launch_builder` and acts in that launch's clone; Claude Code settings shape with `permissions.allow|deny`, `sandbox.filesystem.allowWrite|denyWrite` and an optional `messages.<Tool>` denial text), `host` file stubs such as the run lock, and `packet` variants whose declaration the packet schema does not name (`config_change` is written as `pyproject.toml` in `constraints.declared_paths`).
