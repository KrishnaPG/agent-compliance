# d0 field-name proposal

For the plugin owner to confirm. Names come from acceptance rows that guessed them. Row ids: `d0-AC2..4` = AC2 to AC4; `-` = no row uses the field. Generated from criteria at the commit that adds this file.

## 1. Fields

| schema | field or path | JSON type | meaning | rows |
|---|---|---|---|---|
| packet | `id` | string | item id; names the packet | b9-AC13, d0-AC2 |
| packet | `parent_issue` | integer | tracker issue number of the parent | d0-AC2 |
| packet | `tier` | string enum | design-affecting or mechanical (d5 derives) | d0-AC3, d5-AC7 |
| packet | `goal` | string | intent and why, no design | d0-AC3, d1-AC2, e4-AC1 |
| packet | `applies[*]` | array of string | G, P, R item ids and their QBC ids | d0-AC4, d0-AC15, d2-AC5 |
| packet | `constraints` | object | cited decisions, owners, interfaces, paths, limits | d0-AC5, d1-AC1, d7-AC1 |
| packet | `constraints.declared_paths` | array of string | paths the builder may touch | d7-AC1, d8-AC2..4, d8-AC7..9, d8-AC11..12, d9-AC5 |
| packet | `acceptance[*].id` | string | criterion id, e.g. d0-AC1 or falsify-1 | b9-AC13, d0-AC6, d2-AC3, f1-AC13 |
| packet | `acceptance[*].traces_to` | array of string | G, P, R or QBC ids proved | d0-AC6 |
| packet | `acceptance[*].verification` | string enum | test, lint, fitness or measure (ISO 29148) | d0-AC6, d0-AC13 |
| packet | `verifier` | object | exact checks the measurer and bh check run | d0-AC5, d2-AC1, d2-AC3..4, d2-AC11 |
| packet | `verifier.rules[*].id` | string | rule id from g1 data, with teaching text | g2-AC3 |
| packet | `verifier.targets[*]` | object | targets.schema.json item plus id; numeric threshold | f1-AC4 |
| packet | `verifier.acceptance_paths` | array of string | visible acceptance test paths, protected | d6-AC2 |
| packet | `paved_road` | object | test_paths, dependency_command, check_command | d0-AC5, d2-AC1, d2-AC6..7, d2-AC11 |
| packet | `definition_of_done` | string | every criterion met by the measurer | d0-AC5 |
| result | `packet_sha256` | string | sha256 of the packet measured | b1-AC22, b2-AC12, b2-AC15..16 |
| result | `items[*].id` | string | item id (e4-AC6 used it as a map key) | e4-AC6 |
| result | `items[*].status` | string enum | met, unmet, stuck or not_checked | b14-AC1, e4-AC6 |
| result | `items[*].tier` | string enum | tier the item was run at | d5-AC3..4 |
| result | `items[*].tokens` | integer | tokens spent on the item (sum of jobs) | b14-AC3 |
| result | `items[*].out` | string | output dir out/<ref>/<12-hex>-<mode> | b2-AC1 |
| result | `facts[*].kind` | string enum | one of the catalog then.fact kinds | every fact row (136) |
| result | `facts[*].detail` | string | text naming the file, key or value | every fact row |
| result | `facts[*].count` | integer | occurrences of the fact | every fact row |
| result | `jobs[*]` | array of job record | one entry per agent or program job | b14-AC2, d2-AC1, d6-AC1, d6-AC4, d7-AC2, d7-AC4..5, d11-AC1..3, e5-AC2, f1-AC1, f1-AC5, f2-AC1 |
| result | `gaps[*].id` | string | gap id, unique in the run | b12-AC3 |
| result | `unmerged` | array of string | items left unmerged (bh merge output) | b3-AC1 |
| result | `admitted_total` | integer | items admitted by bh intake | e4-AC7 |
| result | `options[*].targets, .rules` | array | scored targets and rules per option (bh decide) | f1-AC2 |
| result | `options[*].rules.<id>.verdict` | string enum | pass, fail or unknown per rule | f1-AC3 |
| result | `recommended` | string | option id the judge recommends | f1-AC3 |
| jobs | `jobs[*].id` | string | job id, unique in the run | - |
| jobs | `jobs[*].role` | string enum | planner, judge, test_author, builder, reviewer, proposer | b14-AC2, d2-AC1, d6-AC1, d6-AC4, d7-AC2, d7-AC4..5, d11-AC1..3, e5-AC2, f1-AC1, f1-AC5, f2-AC1 |
| jobs | `jobs[*].kind` | string enum | agent, state, measure, merge, commit, ordering | b14-AC2, d2-AC1, d11-AC2, f1-AC5, f2-AC1 |
| jobs | `jobs[*].cached` | boolean | true when the cached job result was reused | b13-AC4..5 |
| jobs | `jobs[*].tokens` | integer | input plus output tokens of the job | b14-AC3, h3-AC5 |
| jobs | `jobs[*].packet_sha256` | string | sha256 of the packet the job read | d0-AC16 |
| jobs | `jobs[*].objections` | array of string | judge objections | d7-AC2 |
| jobs | `jobs[*].falsifying_calls` | array of string | judge calls that would falsify the design | d7-AC2 |
| jobs | `jobs[*].rounds` | integer | rounds the job took | h1-AC3 |
| config | `paved_road.test_paths` | array of string | where the builder puts its tests | c1-AC8..9 |
| config | `paved_road.dependency_command` | string | how a builder adds a dependency | c1-AC6..7 |
| config | `protected` | array of string | paths the measurer restores from the plan commit | b1-AC12..13 |
| config | `tiers.triggers` | array of object | path patterns forcing design-affecting | d5-AC1..2, d9-AC4 |
| config | `tiers.triggers[*].fresh_stack` | boolean | trigger requires a fresh-stack run | d5-AC1 |
| config | `review.triggers` | array of string | path patterns that start a review job | d11-AC5 |
| config | `concurrency` | integer | agents running at once | d9-AC2, d9-AC6 |
| config | `max_rounds` | integer | builder rounds before stuck | b7-AC4, d9-AC3 |
| config | `models` | object | model per role | d9-AC4 |
| config | `commands.timeout_s` | number | seconds before a command is killed | d9-AC3 |
| config | `sizing.packet_tokens` | integer | cap on planner-written packet tokens | d1-AC3..4, d9-AC2 |
| config | `budgets.job_usd` | number | spend cap per job | b13-AC2 |
| config | `budgets.run_usd` | number | spend cap per run | b13-AC3 |
| config | `evals.runs` | integer | runs per eval arm | d9-AC4, h1-AC1 |
| config | `sandbox.allow_all_unix_sockets` | boolean | allow unix sockets in the builder sandbox | d9-AC4 |
| config | `right_way.PLR2004` | string | project teaching text per rule code (key = code) | c6-AC2 |
| config | `limits.findings_shown` | integer | findings printed before "and N more" | b6-AC2, d9-AC1..2 |
| config | `limits.message_chars` | integer | longest teaching message | b6-AC3, d9-AC1..2 |
| config | `limits.h2_chars` | integer | longest H2 hook line | d9-AC2, d9-AC5 |
| config | `limits.record_chars` | integer | longest decision record | d9-AC3, f1-AC5 |
| config | `limits.known_issues` | integer | open known-issue cap | d9-AC3, e3-AC5 |
| config | `limits.idle_days` | integer | idle days before the idle_tracking fact | d9-AC3, e5-AC8..9 |
| config | `limits.flaky_reruns` | integer | reruns of a failing test | d9-AC3 |
| config | `limits.measure_overhead_s` | number | measurer overhead on the toy | b1-AC20, d9-AC4 |
| config | `limits.socket_groups` | array of string | groups whose members refuse the launch | b10-AC3, d9-AC4 |

Packet schema: `harness/schema/packet.schema.json` (d0). Result: `harness/schema/result.schema.json` (b2-AC12; items, facts, jobs). Jobs: a `jobs[*]` entry of the result, one definition `$defs/job_record` in `result.schema.json`. Config: extends `harness/schema/harness.config.schema.json`, which is closed (`additionalProperties: false`) and already holds `protected`, `concurrency`, `max_rounds`, `models`, `commands.timeout_s`, `budgets.*`, `sizing.packet_tokens`.

## 2. Conflicts

| concept | names in use (rows) | proposed name | basis |
|---|---|---|---|
| measurer target | packet `targets` (f1-AC4) vs plan `verifier` thresholds | `verifier.targets[*]` | `targets.schema.json` item {item, metric, op, value, unit} plus `id` |
| rule list | packet `rules[*]` (g2-AC3) vs `verifier` rules vs `applies` | `verifier.rules[*].id`; `applies` = G/P/R/QBC ids only | plan d0 field list |
| criteria | `criteria` (f1-AC13 note) vs `acceptance` | `acceptance[*]` | ISO/IEC/IEEE 29148 criterion; Gherkin scenario |
| result items | array `items[*]` (b2, b14, d5) vs map `items.claim-a` (e4-AC6), `options[oss]` (f1-AC3) | arrays of objects with `id` | SARIF 2.1.0 `results`, JUnit `testcase`: lists, never id-keyed maps |
| job record | list `jobs[*].cached` (b13-AC4) vs one record `objections` at root (d7-AC2, d0-AC16, h1-AC3) | one record = one `jobs[*]` entry; row paths drop the root form | catalog term: result JSON holds `jobs` |
| job class | `role` values (d2-AC1, d6-AC1) vs program kinds (b14-AC2) both under `none_of_kind` | `role` for agents; `kind` = agent or program step | catalog `jobs` key |
| role vs phase | config `models.<phase>` (gaps, plan, build, harvest, review) vs `jobs[*].role` | `models.<role>` | one vocabulary for who ran |
| test paths | `acceptance_paths` placeholder (visible tests, protected) vs `builder_test_paths` (builder own tests) | `verifier.acceptance_paths` and `paved_road.test_paths` | two concepts, two names (PC-M7) |
| paved road | config `builder_test_paths`, `dependency_command` vs packet `paved_road` | same names in both: `paved_road.test_paths`, `paved_road.dependency_command` | copy from config to packet, no mapping |
| tokens | `items[*].tokens`, run_report `tokens`, `jobs[*].tokens` | `jobs[*].tokens` is the source; item = sum | Claude CLI `usage` input_tokens + output_tokens |
| sockets | config `sandbox.allow_all_unix_sockets` vs builder settings `sandbox.network.allowAllUnixSockets` | keep both; generator maps config to Claude Code key | Claude Code settings schema |
| result source | `result_json` read for run, measure, check, intake (e4-AC7), merge (b3-AC1), decide (f1), gaps (b12-AC3) | `command` field plus one `$defs` per command in `result.schema.json` | catalog term lists only run, measure, check |

## 3. Gaps

| schema | field the spec or plan requires | source | rows |
|---|---|---|---|
| packet | `acceptance[*].scenario`, `.given`, `.when`, `.then` (Gherkin text) | plan d0 | none |
| packet | `constraints.decisions`, `.owners`, `.interfaces`, `.limits` | plan d0, IR-m1 | none (only presence asserted, d0-AC5) |
| packet | `verifier.checks`, `verifier.baselines`; `verifier.rules[*].message` (teaching) | plan d0 | none |
| packet | `$schema` / `schema_version` | JSON Schema 2020-12 | none |
| result | per-criterion verdict `items[*].criteria[*]` {id, status} | spec L5 "per-criterion verdict" | none |
| result | `items[*].facts` link (item of each fact) | spec L5 | none |
| result | `schema_version`, `command` | b2-AC12, this proposal | none |
| jobs | `jobs[*].id`, `.item`, `.started_at`, `.exit_code` | b1, run report | none |
| config | `review.triggers` default, `tiers.triggers[*].paths` and `.tier`, `budgets.*` defaults | plan d5, d11, b13 | none |

## 4. Defaults assumed by rows

| config key (overrides) | default | rows | override used |
|---|---|---|---|
| `limits.findings_shown` | 10 | b6-AC2, d9-AC1..2 |  |
| `limits.message_chars` | 300 | b6-AC3, d9-AC1..2 | 120 |
| `limits.h2_chars` | 200 | d9-AC2, d9-AC5 | 60 |
| `limits.record_chars` | 6000 | d9-AC3, f1-AC5 | 500 |
| `limits.known_issues` | 100 | d9-AC3, e3-AC5 | 3 |
| `limits.idle_days` | 14 | d9-AC3, e5-AC8..9 | 14 (equals default: row cannot tell) |
| `limits.flaky_reruns` | 0 | d9-AC3 |  |
| `limits.measure_overhead_s` | 2 | b1-AC20, d9-AC4 |  |
| `limits.socket_groups` | contains docker | b10-AC3, d9-AC4 |  |
| `sandbox.allow_all_unix_sockets` | false | d9-AC4 |  |
| `commands.timeout_s` | 600 | d9-AC3 |  |
| `max_rounds` | 3 | b7-AC4, d9-AC3 |  |
| `concurrency` | 5 | d9-AC2, d9-AC6 |  |
| `sizing.packet_tokens` | 1600 | d1-AC3..4, d9-AC2 | 400 |
| `evals.runs` | 3 | d9-AC4, h1-AC1 | 3 (equals default) |
| `protected` | contains conftest.py and tests/ | b1-AC12..13 | [] (empty is a gap) |
| `tiers.triggers` | non-empty list, `[*].fresh_stack` present | d5-AC1..2, d9-AC4 | [] |
| `models` | present (table per role) | d9-AC4 |  |
| `review.triggers` | unstated | d11-AC4..5 | ["docs/**"] |
| `budgets.job_usd / run_usd` | unstated | b13-AC2..3 | 0.5 / 1 |
| `right_way.PLR2004` | unstated | c6-AC2 | text |
