# agent-compliance v2: work plan

Status: plan, 2026-11-25. Tracking issue #7; slices a-h are #8-#15. Requirements are `docs/spec/quality-by-construction.md` (QBC-n), decisions `docs/adr/0001-quality-by-construction.md`, evidence `docs/design/evidence/`.

This plan lists work only. It does not restate the design: each task cites the QBC ids it satisfies, and acceptance tests (ATDD) are written from each task's "done when" by an agent that does not build it.

Finding ids are prefixed by source, because the reviews reuse the same numbers:
- IR-: `evidence/independent-review.md`;
- RH-: `evidence/review-harness.md`;
- RS-: `evidence/review-skills.md`;
- SP-: `evidence/spike-order-engine.md`.

Sizes: S is under a day, M is 1-3 days, L is more (as in RH section 7). "Spike" marks a task whose mechanism comes from the spike. The spike is done, so these tasks are not blocked; its four mechanism changes wait only for the owner's confirmation (Q5).

## 1. Rulings applied

These bind every task and are not re-argued:
- **No agent in the mechanical path.** The `bh` program runs git, tests, measuring, ordering, staging and merging. Agents launch as `claude -p` jobs only for judgement (QBC-78, SP section 5).
- **Standards, OSS and reuse first.** Every limit is a default with an override in the plugin's project-local folder, `.brick-harness/config.json`, reusing the keys the config schema already has (`concurrency`, `max_rounds`, `models`, `sizing`, `limits`, `budgets`). The file is optional: absent means defaults, and nothing generates it (no init step, QBC-60, QBC-63).
- **Ownership** is read from CODEOWNERS, OpenAPI tags and the database catalog.
- **No pass/fail quality gates.** Only refusals for order, and every rejection teaches.
- **The Known issues list is a bounded backlog**, with its limit set as policy.
- **The packet sits in a protected path** that only the orchestrator or planner writes; a builder writing its own packet is refused.

## 2. Independent-review findings: disposition

Each finding gets exactly one disposition: a task id, "settled" with its reason, or an owner question (Q).

| Finding | Disposition |
|---|---|
| IR-C1 builder controls what the measurer runs | b4 (measure with all tests, test and lint config, recipes and ratchet files from the trusted plan commit); c4 (ratchets compared against the merge base); b5 (suppression, skip, ratchet-growth and dropped-test facts); b4 (a declared config change is written by a non-builder into the plan commit) |
| IR-C2 orchestrator grades itself; tier rules contradict | d3 (tier computed by the program from declared paths, then from the actual diff, with automatic re-queue and a "tier X from paths Y" fact line); d2 (prompt assembled mechanically from packet fields). "Planner writes every packet": settled by ruling (orchestrator or planner). The pins contradiction is Q2 |
| IR-C3 how plugin checks reach the human's build | c3 (presets written into the project's standard config files and `.pre-commit-config.yaml`; the measurer runs only the project's entry points); e6 (red CI on a human push files a defect). Moving CI ahead of rollout step 5 is Q3 |
| IR-M1 H0 does not hold | d2 and b2 (order is structural: a builder clone exists only from a packet, kept by digest outside the clone); d7 (H0 predicate, Bash route through the sandbox and PostToolUse, orchestrator channel). That H0 refuses is settled by ruling and QBC-46 |
| IR-M2 held-out cases; red by error | d4 (held-out cases written by the test author, unseen by the builder); b6 (JUnit error vs failure recorded) |
| IR-M3 design-affecting tier has no design step | Settled by QBC-41 (the planner's packet is the design output at L2) and QBC-69 (a fresh judge). Built in d5 |
| IR-M4 bug fixes graded by their builder | d4 (finder or test author writes the regression test; fails at parent, passes at fix) |
| IR-M5 L1's counter rests on what it replaces | f1 (proposer plus fresh judge; falsifying calls become measurer targets). Ordering before the pilot's first epic is in the rollout note (section 5) |
| IR-M6 "gate" undefined | Settled by QBC-11 and QBC-51: build checks are declared targets returned for retry, not gates. Built in b10 ("stuck" fact at the round limit) and d9 (Critical and Major review findings become failing protected tests) |
| IR-M7 facts have no readers | b10 (fact, reader, action, channel table). The rollout condition "Criticals plus RH-M1, M12, M14" is met because b9 and b10 are in slice b |
| IR-M8 declared data has no standard source | Sources settled by ruling (CODEOWNERS, OpenAPI tags, database catalog). c7 reaches the database through the standard libpq environment. c8 adds the "not checked" fact for unsupported stacks and keeps project-only checks as project tests |
| IR-M9 limits have no override place | Settled by ruling (`.brick-harness/config.json`). d8 holds the full list, with QBC-13's units kept |
| IR-M10 teach() helper home and claim | b9 (one helper in the plugin's own code, with a test over every refusal path); c6 (right-way text as data keyed by rule code; an unmapped rule is a fact). Project tests never import plugin code (c3, c8 run as standalone tools) |
| IR-M11 runtime state has no home | Settled by ruling plus SP section 5. Packets, held-out cases and facts live in the orchestrator's `.brick-harness/`, outside every builder clone (b2, d2) |
| IR-M12 v2 contents not derivable | This plan (section 4) is the single table. The spike answers its open branch (SP section 5) |
| IR-M13 agents act as the owner on GitHub | e7, waiting on Q1 (a bot identity) |
| IR-M14 intake mechanics | e2 (atomic parent through GraphQL `createIssue(parentIssueId)`, which the API accepts; the Action links form parents first; a standing maintenance parent per owner); e5 (idle report at events, no timer); e3 (Known issues found by label) |
| IR-M15 success measure and cost case | h1 and h3 (a per-slice metric from measurer and job records). The target and stop-rule defaults are Q4. d11 adds one planted test per gaming row |
| IR-E1 H1 duplicates the packet | Settled: H1 is a MUST (QBC-49). Per SP it is the packet delivered at SessionStart (d2), so there is no second copy |
| IR-E2 H2's record duplicates SG-02 | d7: H2 writes through the same scope-fact writer, so there is one record |
| IR-E3 brief and packet are two schemas | d1: one packet schema with tier and environment fields |
| IR-E4 history inside the design | Q6 (a spec edit) |
| IR-E5 unbacked token numbers | b14 and h1 measure them; the spec text follows measurement (Q6) |
| IR-m1 rules file in packet vs never repeated | d1: the packet cites rule lines by id, never their text |
| IR-m2 two trigger lists | d3: one trigger list, and each trigger flags whether it needs a fresh stack |
| IR-m3 "cover most of them" overstates | c5: the parity report states the real coverage |
| IR-m4 Major count | Evidence correction only (11 Major); no task |
| IR-m5 review trigger needs a detector | d9 |
| IR-m6 PostToolUse linter on the changed file | Not planned. Measure first: h1 records measurer rounds lost to lint misses, and a hook is added only if they are material (QBC-14) |
| IR-m7 pgTAP question | c8: vet pgTAP before writing a catalog diff |
| IR-m8 published-part declarations exist | c7, c8: infer from package.json `exports`, PEP 8 `__all__` and workspace members |

### Other review findings

The same rule applies: each finding maps to one task or a stated reason.

- **RH-K1 to RH-K8:**
  - K1: b2;
  - K2 and K4: c5;
  - K3: b8;
  - K5: b4 and b5;
  - K6 and K7: b6;
  - K8: b7.
- **RH-M1 to RH-M14:**
  - M1 and M12: b9;
  - M2: d4;
  - M3: d3;
  - M4: e4;
  - M5: c1;
  - M6: b1;
  - M7, M8 and M9: b12;
  - M10: d1 and b14;
  - M11: b11;
  - M13: b7;
  - M14: b10.
- **RH-m1 to RH-m13:**
  - m1, m2 and m3: b13;
  - m4: c5;
  - m5: a5;
  - m6: e4;
  - m7: a2;
  - m8: c1;
  - m9, m10, m11 and m13: b6;
  - m12: a5.
  - RH section 5 duplications: b13.
- **RS-F1 to RS-F13:**
  - F1 and F13: a1;
  - F2 and F4: f1;
  - F3: a3 and g1;
  - F5: a4;
  - F6: f1;
  - F7: g1 and g2;
  - F8: c5;
  - F9: c3;
  - F10: e4;
  - F11: f3;
  - F12: h1 and h2.
- **RS minors:**
  - 1: h2;
  - 2: settled (v2 is built on `main`);
  - 3: f2.

## 3. Slice order and dependencies

```
a (Prune) ----------------------------.
g (Standards) --> f (Decisions) ------+--> h (Evals, measured alongside)
b (Harness core) --> c (Convention) --+
                 \-> d (Flow) --> e (Intake)
```

- **a and g** start now and run in parallel.
- **b** needs nothing else. The spike is done, and Q5 confirms its four mechanism changes.
- **c and d** need b. d7 needs c7 for the owner line H2 shows.
- **e** needs d (d6's approvals, d8's limits). e6 waits on Q3, e7 on Q1.
- **f** needs g. f3 also needs e1, d4 and c3.
- **h** runs alongside: h2 can follow a; h1 needs b14's toy run; h3 waits on Q4.
- **Coupling g to b and d (QBC-85):**
  - the packet's rule list (d1) and the measurer read g1's data;
  - g3 must not drop the rule ids `checks/index.json` uses before c5 retires those checks after parity (QBC-8).

## 4. Tasks per slice

Each task lists the QBC ids it satisfies, the files it touches, "done when" (the source of its acceptance tests) and its size.

### a. Prune (#8), mechanical, no dependencies

- [ ] **a1. Move the shared lookup and judging method, then delete compliance-review and compliance-catalog** (RS-F1, RS-F13).
  - QBC: 79, 77, 64.
  - Files: `skills/compliance-review/`, `skills/compliance-catalog/`, `skills/{vetted-decision,vet-oss,bug-analysis,harness}/SKILL.md`, `evals/trigger-review/`, `evals/trigger-catalog/`.
  - Done when:
    - both skill directories and their eval directories are gone;
    - a grep for either name over `skills/ agents/ templates/ harness/ README.md` is empty;
    - the harness skill sends `overlay_candidates` to no skill;
    - every file a kept skill references exists.
  - Size: M.
- [ ] **a2. Delete the 9 unused `bh-*` CLIs and the dead functions** (RH section 5, RH-m7).
  - QBC: 79, 76.
  - Files: `bin/bh-{admit,branch,brief,commit,gaps,merge,rank,reconcile,state}`, `harness/tests/`, `harness/lib/bhcore.py`.
  - Done when:
    - `bin/` holds only `bh`, `bh-answer`, `bh-measure` and `bh-init` (removed in c1);
    - the library functions `bhorch` calls are kept, packet assembly included;
    - `_write_gaps_doc` and `_committed_finding_ids` are gone;
    - the tests that called the CLIs call the functions and pass;
    - a grep for the nine names over the docs and skills is empty.
  - Size: S.
- [ ] **a3. Templates** (RS-F3).
  - QBC: 79.
  - Files: `templates/`.
  - Done when:
    - `templates/` holds `plan-dry-run.md` and `bug-record.md` (removed in e1);
    - `catalog-audit.md`, `compliance-bindings.md` and `review-brief.md` are gone and nothing references them;
    - `plan-dry-run.md` reports guesses as a count, with no BROKEN or PASS/FAIL label.
  - Size: S.
- [ ] **a4. Trim skill descriptions** (RS-F5).
  - QBC: 79, 71.
  - Files: `skills/*/SKILL.md` frontmatter.
  - Done when:
    - each kept description names one trigger and one "do not use" line;
    - no skill loads another skill's file;
    - description token counts before and after are recorded in the commit;
    - the existing `evals/no-trigger` cases load no skill.
  - Size: M.
- [ ] **a5. README, manifest and harness docs claims** (RH section 7 docs rows, RH-m5, RH-m12).
  - QBC: 79, 76.
  - Files: `README.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `catalog/CHANGES.md`, `harness/README.md`, `harness/docs/`.
  - Done when:
    - a grep finds none of the "industry-standard", "converge", PASS/FAIL, "every scoring bypass" or "up to three commands" claims;
    - one version appears in plugin.json, marketplace.json and the changelog;
    - `harness/docs/lean-plan.md` is deleted, because this plan replaces it;
    - each open entry in `harness/docs/findings.json` is filed as an issue under #7, and the file is deleted;
    - `harness/docs/decisions/0001-work-tracking.md` has a current caller list and no evidence outside the repo.
  - Size: S.

### b. Harness core (#9), design-affecting, depends on the spike (done)

- [ ] **b1. Dependencies through PEP 723 and uv; jsonschema replaces the hand-written validator** (RH-M6).
  - QBC: 76, 80, 13.
  - Files: `harness/lib/bhcore.py`, `bin/*`, `harness/schema/`.
  - Done when:
    - `validate()` and the `GAP_KINDS` literal are gone; the kinds are read from `gaps.schema.json`;
    - a schema keyword the old validator ignored now rejects bad input in a test;
    - the suite passes under `uv run --script`.
  - Size: M.
- [ ] **b2. Builder isolation** (RH-K1; SP C2 and C5). Spike.
  - QBC: 65, 15, 48, 80, 100.
  - Files: `harness/lib/bhorch.py` (launch), `agents/harness-builder.md`, the generated builder settings.
  - Done when:
    - the builder works in a `git clone --no-local --single-branch` outside the repo with `origin` removed, never a worktree;
    - the jobs dir and the plugin root are not passed as `--add-dir`;
    - allow rules are scoped (`Edit(*)`, `Write(*)`, `Bash`), with `permissions.blockReadsOutsideWorkingDirectories: true`;
    - the sandbox has `allowUnsandboxedCommands: false`; `denyRead` on the orchestrator dir and the repo; `denyWrite` on the clone's protected tests, the orchestrator dir, the repo, the plugin root and any orchestrator state under a temp dir;
    - no deny rule sits on a path whose refusal must teach;
    - packet and held-out cases live only in the orchestrator dir, kept by digest;
    - the program, not the builder, stages and commits the clone;
    - the spike's 10 planted attempts (C2 and C5 tables), rerun as tests on the toy, each end stopped or with no effect, judged by file digests and refs, not by the agent's reply.
  - Size: L.
- [ ] **b3. Sandbox self-test and host caveat** (SP host finding 1, SP section 5). Spike.
  - QBC: 12, 13, 11, 80.
  - Files: `harness/lib/bhorch.py`, `harness/README.md`.
  - Done when:
    - before launching, the program runs one sandboxed probe;
    - on failure it records a fact, withholds the held-out cases for that run, and prints a teaching message naming the fix: `network.allowAllUnixSockets: true` where the AppArmor profile `bwrap-userns-restrict` applies (as on Ubuntu 26.04), with the builder account outside socket-granting groups such as `docker`, or a fixed AppArmor profile;
    - the run starts anyway: no `failIfUnavailable`, which would be a gate by environment;
    - membership of a socket-granting group is recorded as a fact;
    - `allowAllUnixSockets` is a default with an override.
  - Size: M.
- [ ] **b4. Measure from the trusted base** (IR-C1, RH-K5; SP G1-G3). Spike.
  - QBC: 15, 31, 35, 51, 65, 80.
  - Files: `harness/lib/bhcore.py` (`measure_item`, `overlay_plan`, `_protected`), `bin/bh-measure`.
  - Done when:
    - the measurer uses its own checkout per (ref, mode);
    - from the plan commit it overlays all tests (not only the item's), the test and lint config (`conftest.py`, `pytest.ini`, `pyproject.toml` `[tool.*]`, `tsconfig*.json`, `.sqlfluff`, ESLint and oxlint config), the entry-point recipe files and the ratchet files;
    - builder-added test config is set aside;
    - held-out cases are copied in only at measure time;
    - the test command runs in `bwrap` (read-only `/`; tmpfs over `/tmp`, the orchestrator state and the builder clones; only the checkout writable; no network), with a canary that must fail (`tampered` fact);
    - `protected` defaults to these paths, and an empty list is a gap;
    - a config change the packet declares is measured from the plan commit, where a non-builder wrote it;
    - planted cases measure as follows:
      - G1, a gutted test: `met:false` with a fact;
      - G2, a forging `conftest.py`: `met:false`, fact `A conftest.py`;
      - G3, report patching plus a leak: `met:false`, `tampered`, no leak file;
      - an edited test recipe: measured with the base recipe;
      - an honest commit: `met`.
  - Size: L.
- [ ] **b5. Diff facts against the base, without pattern lists** (IR-C1.3, RH-K5).
  - QBC: 8, 11, 15.
  - Files: `harness/lib/bhcore.py` (facts).
  - Done when each planted commit yields exactly its fact, never a refusal, and a shrink yields none:
    - JUnit test ids present at base and missing at the candidate;
    - a grown JUnit skipped or xfail count;
    - a grown count of suppressed findings, measured by running the project's linters with inline suppressions ignored (`ruff --ignore-noqa`, `eslint --no-inline-config`) against a normal run, at base and at the candidate;
    - a grown ratchet list (files from c4).
  - Size: M.
- [ ] **b6. Measurer correctness** (RH-K6, RH-K7, IR-M2, RH-m9, m10, m11, m13).
  - QBC: 66, 34.
  - Files: `harness/lib/bhcore.py`.
  - Done when:
    - each run writes to `out/<item>/<sha12>-<slot>`, with pairs deduped;
    - every crash path gives unmet plus a teaching fact, never an exception;
    - a JUnit `<error>` and a `<failure>` are recorded apart, as red by error or red by failure;
    - non-finite samples fail closed;
    - `tree_key` includes plan files and held-out cases;
    - a test leaving a child that holds stdout is not recorded as a timeout;
    - each planted input (missing or malformed JUnit, a NaN in CSV, two refs at once, a lingering child) gives the stated result.
  - Size: M.
- [ ] **b7. Merge guard tested, and an atomic merge** (RH-K8, RH-M13).
  - QBC: 66.
  - Files: `harness/lib/bhcore.py` (`merge_unmerged`, `_restore_guarded`), `harness/tests/test_toy.py`.
  - Done when:
    - a test on a met item asserts `unmerged == []`;
    - an unmet candidate never reaches HEAD, and removing the guard turns that test red;
    - a merge is one commit;
    - a conflict names the right item;
    - `merge_unmerged` no longer builds the whole `state()`.
  - Size: M.
- [ ] **b8. Generated safeguard register** (RH-K3, lean-plan W15).
  - QBC: 67, 58.
  - Files: `harness/safeguards.json`, `harness/tests/test_safeguards.py`.
  - Done when:
    - each entry's status comes from pytest markers and JUnit results;
    - the review's fake entry, and an entry citing a test that did not run or failed, are reported;
    - no hand-kept status field remains.
  - Size: S.
- [ ] **b9. One teach() helper; gates become facts** (RH section 3, RH-M1, RH-M12, IR-M10).
  - QBC: 11, 12, 53, 54, 55, 56, 68.
  - Files: `harness/lib/*.py`, `bin/*`.
  - Done when:
    - one `teach(rule, wrong, right, ref)` exists with all arguments required; repeats are grouped (first N, default 10, then a count); the cap defaults to 300 characters;
    - five former gates become facts with teaching, and the item stays ready: the commit gate on targets, the `env_setup` block, the tracker sha-pin refusal, the catalogue-schema merge refusal and the platform gate (in c5);
    - each order refusal in RH section 3 that lacked one now names the next step;
    - a test enumerates every refusal and non-zero exit path in `harness/` and `bin/` and asserts the shape `[rule] wrong -> right . ref` with a non-empty right part.
  - Size: M.
- [ ] **b10. Facts reach the orchestrator** (RH-M14, IR-M7, IR-M6).
  - QBC: 30, 35, 51.
  - Files: `harness/lib/bhorch.py`, `harness/README.md`.
  - Done when:
    - a table (fact, reader, action, channel) covers scope, flaky, red on main (by failure or by error), tampered, sandbox unavailable, suppression or ratchet growth, dropped tests, H0 bypass, not checked, inferred and stuck;
    - the channel is `bh run`'s result JSON plus one line per item in the run report;
    - at the round limit an item becomes "stuck", reported to the owner for a re-plan;
    - each fact, planted on the toy, appears in the run report with its action.
  - Size: M.
- [ ] **b11. Run lock and background run** (RH-M11).
  - QBC: 80.
  - Files: `harness/lib/bhorch.py`, `skills/harness/SKILL.md`.
  - Done when:
    - `bh run` holds a `flock` on the measure output;
    - a second concurrent run gets a teaching refusal (an order refusal);
    - the skill says to start `bh run` in the background and act on its exit notification, with no polling.
  - Size: S.
- [ ] **b12. Gaps, findings and value order** (RH-M7, RH-M8, RH-M9, gaps.md row).
  - QBC: 80.
  - Files: `harness/lib/bhcore.py` (gap checks, rank, `value_queue`), `templates/` or deletion.
  - Done when:
    - a re-review that omits a gap leaves it open;
    - findings are verified like gaps, and claimed impact does not set rank;
    - gap ids do not collide;
    - a missing `est_loc` is a gap, not 1;
    - `gaps.md` comes from a template, and a pipe in a summary renders;
    - links are checked by lychee, with no hand-written link checker.
  - Size: M.
- [ ] **b13. Orchestrator minors and duplicates** (RH-m1, m2, m3; RH section 5).
  - QBC: 80, 76.
  - Files: `harness/lib/bhorch.py`, `harness/lib/bhcore.py`.
  - Done when:
    - one builder's git failure gives a stuck report, not an aborted run;
    - each launch carries `--max-budget-usd`, so a round cannot overshoot `run_usd`;
    - job cache keys hold content digests of the skill and the standards data;
    - each of these has a test;
    - `item_key`, `bhorch.git`, `bhorch.fill`, the restated targets and `_waves` (replaced by `graphlib`) have one home each.
  - Size: S.
- [ ] **b14. Toy run as proof** (RH-M10).
  - QBC: 9, 10, 80.
  - Files: `docs/design/evidence/` (new run record).
  - Done when a paid end-to-end `bh run` on the toy is committed as evidence: per-job tokens and USD from the job records, and every item met, or stuck with its facts.
  - Size: M.

### c. Convention over configuration (#10), design-affecting, depends on b

- [ ] **c1. Inference replaces `bh-init`** (RH-M5, RH-m8, RS-F10).
  - QBC: 2, 60, 61, 63, 98.
  - Files: `harness/lib/bhcore.py` (Config), `bin/bh-init` (deleted), `harness/schema/harness.config.schema.json`.
  - Done when:
    - the test and verify entry points are read from justfile, Makefile, package.json scripts or pyproject;
    - languages come from `git ls-files` and the linter's own language mapping, with no hand list;
    - lockfiles and owners (CODEOWNERS, OpenAPI tags) are read too;
    - each inferred value is a fact naming its source file;
    - `bh run` works on the toy and on a second fixture in another ecosystem with no `.brick-harness/config.json`;
    - `bh-init` is gone.
  - Size: L.
- [ ] **c2. Ask once, into a standard file** (S option D).
  - QBC: 61, 63.
  - Files: `harness/lib/bhcore.py`, `skills/harness/SKILL.md`.
  - Done when, on a fixture without CODEOWNERS:
    - the plugin asks one question;
    - with approval it writes CODEOWNERS (or an OpenAPI tag, or a recipe line), never a plugin file;
    - a rerun asks nothing.
  - Size: M.
- [ ] **c3. Presets into the project's standard config files and pre-commit** (IR-C3, RS-F9).
  - QBC: 4, 5, 16, 17, 19, 57, 62, 81.
  - Files: new `presets/`, `.pre-commit-hooks.yaml`.
  - Done when:
    - the plugin ships preset fragments:
      - ruff DTZ, S105-S108, PLR2004, and TID251 banned-api with `msg`;
      - ESLint or oxlint `no-restricted-*` with `message`;
      - sqlfluff AM04 plus a small set;
      - tsconfig `strict`;
    - with approval, the fragments are written into the project's `pyproject.toml`, ESLint config, `.sqlfluff` and `tsconfig`, plus a `.pre-commit-config.yaml` pinned to a plugin release;
    - the project's test entry point runs them;
    - with Claude Code absent, `pre-commit run --all-files` and the project's test recipe both report a planted naive datetime;
    - the measurer runs only commands that are project recipes.
  - Size: L.
- [ ] **c4. Ratchets against the base** (IR-C1.2).
  - QBC: 8, 19.
  - Files: `harness/lib/bhcore.py`, `presets/`.
  - Done when:
    - baselines are generated at adoption: per-file-ignores, `.sqlfluffignore`, the generated `ignore_imports`, the strict-tsconfig include list and pinned gate-test hashes;
    - each is compared against the merge base, never the working tree;
    - a planted growth of each kind yields b5's fact (for the include list, a shrink);
    - the opposite direction yields none.
  - Size: M.
- [ ] **c5. Parity, then retire the ast-grep checks** (RS-F8, RH-K2, RH-K4, RH-m4, IR-m3).
  - QBC: 8, 23, 73, 81.
  - Files: `checks/`, `harness/checkers.json`, `harness/lib/bhrules.py`, `harness/tests/test_no_waiting.py`, `harness/tests/test_no_project_terms.py`.
  - Done when:
    - a parity report runs old and new on the existing planted snapshots (HO-02, ID-15, RL-08, Python and TypeScript) and states the real coverage;
    - only rules that pass parity are retired; a rule that fails (for example TID251 against `.fetch(`) keeps its old check, recorded;
    - no download code and no `rules.violations` target remain;
    - `test_no_waiting.py` is replaced by ruff TID251 over `harness/`, and the project-terms grep becomes a lint.
  - Size: M.
- [ ] **c6. Right-way text for fixed-message rules** (IR-M10).
  - QBC: 12, 57.
  - Files: `presets/` (data keyed by rule code), `harness/lib/bhcore.py`.
  - Done when:
    - a PLR2004 miss the measurer relays carries its right-way line;
    - the text is overridable in `.brick-harness/`;
    - an enabled rule code with no entry is a fact.
  - Size: S.
- [ ] **c7. Owners lookup in the plugin** (IR-M8, IR-m8).
  - QBC: 62, 13.
  - Files: `bin/bh` (`owners` subcommand), `harness/lib/`.
  - Done when:
    - `bh owners <path|topic>` returns owner, package, database roles and operations on a fixture;
    - it reads CODEOWNERS, OpenAPI tags, the database catalog (through the libpq `PG*` or `DATABASE_URL` environment), package.json `exports`, PEP 8 `__all__` and workspace members;
    - a missing source gives a "not declared" fact naming the standard file to add.
  - Size: M.
- [ ] **c8. Generic fitness functions as a standalone CLI** (IR-M8, IR-m7).
  - QBC: 18, 19, 62.
  - Files: new `fitness/` CLI, `presets/` (recipe line).
  - Done when:
    - pgTAP is vetted first for owner and grant assertions;
    - the project's test recipe runs four checks: one owner per object, each database object's owner equals its declared owner, grants match the declared roles, and import boundaries from published parts (generated import-linter or dependency-cruiser config, its ignore list a ratchet);
    - a planted wrong owner, grant and import are each reported with teaching;
    - a stack with no database, or an unsupported one, gives "not checked", never met;
    - project-only checks (a policy registry, unit lists) stay project tests.
  - Size: L.
- [ ] **c9. Wiring facts.**
  - QBC: 20, 21, 22.
  - Files: `harness/lib/bhcore.py`.
  - Done when a fixture with a linter config or check that no recipe runs gives a fact naming it.
  - Size: S.

### d. Flow (#11), design-affecting, depends on b

- [ ] **d1. One packet schema** (IR-E3, RH-M10, IR-m1).
  - QBC: 24, 33, 37, 38, 39, 40, 42.
  - Files: `harness/schema/` (packet), `harness/lib/bhcore.py` (packet assembly).
  - Done when:
    - the schema has these fields: goal, tier, tier reason, constraints, owners touched with their published interfaces, declared paths, acceptance (protected test paths and targets), environment and declared config changes;
    - constraints are cited decision and rule lines, by id, never their text;
    - the schema rejects a design field;
    - a mechanical packet may name the exact edit;
    - the cap is `sizing.packet_tokens` (default 1,600 tokens, documented as bytes/4);
    - an over-cap packet is not launched, and the planner gets a teaching message.
  - Size: M.
- [ ] **d2. Packet custody and delivery** (SP section 5, IR-C2.4, IR-E1). Spike.
  - QBC: 24, 46, 48, 49.
  - Files: `harness/lib/bhorch.py`, `hooks/hooks.json`.
  - Done when:
    - the packet is kept by digest in the orchestrator's `.brick-harness/`;
    - the builder's prompt is assembled from packet fields alone;
    - the packet and owner rows arrive at SessionStart `additionalContext` (H1, at most 2,000 characters by default) for a program-launched builder;
    - SubagentStart is used only for Agent-tool subagents;
    - a packet edited inside the clone changes nothing the program reads.
  - Size: M.
- [ ] **d3. Tier computed by the program** (IR-C2, IR-m2).
  - QBC: 25, 27, 30.
  - Files: `harness/lib/bhorch.py`, a plugin defaults table.
  - Done when:
    - one trigger list is data, with an override in `.brick-harness/config.json`;
    - triggers are path sets resolved from standard files (OpenAPI files, migrations, compose files, lockfiles and pins, role files, the budgets file), each with a fresh-stack flag;
    - the tier is set from declared paths at launch and recomputed from the diff after the build;
    - a diff hit re-queues the item at the higher tier, with the fact line "tier X from paths Y";
    - the pins default follows Q2;
    - a packet declaring docs only, whose diff touches compose, is re-queued.
  - Size: M.
- [ ] **d4. Test-author step (L3)** (RH-M2, IR-M2, IR-M4). Spike for the holdout path.
  - QBC: 31, 34, 41, 82.
  - Files: new `agents/harness-test-author.md`, `harness/lib/bhorch.py`.
  - Done when:
    - the program launches the test author before the builder, as another job;
    - the test author writes acceptance tests into protected paths in the plan commit, and held-out cases into the orchestrator's holdout;
    - red on main is recorded by failure or by error;
    - a test that is red by error only goes back to the test author;
    - for a defect, the finder or the test author writes the regression test, and "fails at the parent, passes at the fix" is recorded;
    - on the toy, an item runs test author, then builder, then measurer.
  - Size: L.
- [ ] **d5. Design step for design-affecting items** (IR-M3).
  - QBC: 41, 69, 26.
  - Files: `agents/harness-planner.md`, `harness/lib/bhorch.py`.
  - Done when:
    - the planner writes the contract, schema or role delta as a declared file in the plan commit;
    - a fresh judge job (f1's judge) reads it before the test author starts;
    - the job record shows planner, then judge, then test author, then builder, each a distinct job.
  - Size: M.
- [ ] **d6. Approvals recorded.**
  - QBC: 26.
  - Files: `harness/lib/bhorch.py`, `bin/bh-answer`.
  - Done when:
    - each approval is a fact (approver, packet digest);
    - an unapproved design-affecting packet or epic record is not launched;
    - the message names the missing approval;
    - the identity check follows in e7.
  - Size: S.
- [ ] **d7. Hooks in `hooks/hooks.json`** (IR-M1, IR-E2; SP sections 4 and 5). Spike.
  - QBC: 29, 43, 44, 45, 46, 47, 48, 50.
  - Files: new `hooks/hooks.json`, `hooks/*.py`.
  - Done when:
    - every guard has `onFailure: block`;
    - H0 (PreToolUse, Edit/Write/Read) refuses a builder or test-author agent type with no registered packet, with QBC-47's text;
    - the orchestrator learns of it through the agent's final report and a b10 fact;
    - file tools on the orchestrator dir are refused with teaching and no deny rule;
    - H2 (PreToolUse) shows one owner line (from c7) on the first touch outside the packet's paths, at most 200 characters, once per path, written through the SG-02 scope-fact writer, never blocking;
    - Bash notes come from PostToolUse or PostToolUseFailure, keyed on the sandbox's own read-only error and the packet's protected paths;
    - the main session and human sessions are never refused;
    - the hooks fire under `claude -p --plugin-dir`.
  - Size: M.
- [ ] **d8. Limits table** (IR-M9).
  - QBC: 13, 27, 33, 55, 90.
  - Files: one plugin defaults table, `harness/schema/harness.config.schema.json`.
  - Done when:
    - every limit is read from one table, with overrides in `.brick-harness/config.json` under the existing keys;
    - the table holds: work in progress 5, packet 1,600 tokens, message 300 characters, H1 2,000 characters, H2 200 characters, findings shown 10, decision record 2 pages, the round limit, Known issues 100, the model per role, the tier triggers and the review triggers;
    - an override changes behaviour in a test;
    - with 6 ready items at most 5 agents run;
    - ruff PLR2004 is clean over `harness/`.
  - Size: M.
- [ ] **d9. Review on the whole diff** (IR-m5, IR-M6).
  - QBC: 31, 36, 91.
  - Files: `harness/lib/bhorch.py` (`AUTH_RE`), `agents/harness-reviewer.md`.
  - Done when:
    - review triggers come from declared data (OpenAPI `securitySchemes`, role and grant files, money types, key paths), with a data list as override, and `AUTH_RE` is gone;
    - triggers are judged on the item's whole diff across rounds;
    - design-affecting items get a duplication check;
    - a Critical or Major finding becomes a failing protected test by the test author;
    - a planted split diff still triggers review.
  - Size: M.
- [ ] **d10. Harness skill.**
  - QBC: 82, 59.
  - Files: `skills/harness/SKILL.md`.
  - Done when:
    - the skill describes the tiers, the test-author step and the packet as the only brief;
    - it references no deleted skill;
    - it is no longer than the 1.5.2 skill.
  - Size: S.
- [ ] **d11. Planted gaming suite** (IR-M15).
  - QBC: 31, 58, 15.
  - Files: `harness/tests/`.
  - Done when one planted test per gaming row of the levels and mechanisms tables passes on the toy, and each row cites its test id. The rows: under-tiering, vacuous tests, test edits, a self-written packet, hidden reads, Bash-path edits, suppression and ratchet growth, a split diff, endless retries and a hand launch.
  - Size: M.

### e. Intake (#12), design-affecting, depends on d

- [ ] **e1. Issue forms.**
  - QBC: 83, 87, 88.
  - Files: `templates/.github/ISSUE_TEMPLATE/{decision,slice,defect}.yml` and `config.yml`; `templates/bug-record.md` (deleted).
  - Done when:
    - the three forms validate, each requiring parent, goal and acceptance;
    - blank issues are off;
    - with approval, the forms are written once into the project's `.github/`;
    - `bug-record.md` is gone.
  - Size: M.
- [ ] **e2. Atomic parent and parent check** (IR-M14).
  - QBC: 88, 89.
  - Files: `harness/lib/bhtracker.py`, `templates/.github/workflows/parent-check.yml`.
  - Done when:
    - the plugin's filing path uses GraphQL `createIssue(parentIssueId)`, so an agent-filed issue has a native parent at creation and gets no comment;
    - the Action, on `opened`, first links a form's parent field as a sub-issue, then comments QBC-88's message once if the issue is still parentless;
    - for a defect in code with no tracking issue, the message names the owner's standing maintenance tracking issue (from CODEOWNERS), created on first need.
  - Size: M.
- [ ] **e3. Known issues as a bounded backlog** (IR-M14).
  - QBC: 90.
  - Files: `harness/lib/bhtracker.py`.
  - Done when:
    - the list is found by label;
    - each line names its parent;
    - at the d8 limit (default 100) a new line is refused with teaching: fix and remove first;
    - a second labelled list is a fact.
  - Size: S.
- [ ] **e4. Intake keeps the body; tracker from the git remote** (RH-M4, RS-F10, RH-m6).
  - QBC: 75, 83.
  - Files: `harness/lib/bhtracker.py`, `harness/adapters/`.
  - Done when:
    - an admitted issue's full body appears in its packet's goal source;
    - the repo is read from `gh repo view`, and no bindings file is needed;
    - an issue a human closed is not reopened;
    - `list` filters before its limit;
    - one bad claim does not abort the admission;
    - `room` is read under the lock.
  - Size: M.
- [ ] **e5. Tracking-issue lifecycle and review findings** (IR-M14).
  - QBC: 91, 92, 93.
  - Files: `harness/lib/bhtracker.py`.
  - Done when:
    - a review finding reopens the slice's checklist line rather than opening an issue;
    - closing the last sub-issue closes the tracking issue;
    - an idle tracking issue appears as a fact in the next `bh run` report or on a sub-issue close, with no timer.
  - Size: S.
- [ ] **e6. Red CI on a human push** (IR-C3). Waits on Q3.
  - QBC: 17, 52, 92.
  - Files: `templates/.github/workflows/`.
  - Done when a failed run of the project's entry points on push files a defect, through e2, under the slice whose paths it touches, or else the owner's maintenance issue.
  - Size: S.
- [ ] **e7. Agent identity on GitHub** (IR-M13). Waits on Q1.
  - QBC: 26, 11.
  - Files: `harness/lib/bhtracker.py`, `harness/lib/bhorch.py`.
  - Done when:
    - agents' `gh` calls run under the bot identity;
    - an approval counts only from the owner's login;
    - an approval made by the bot is not counted.
  - Size: M.
- [ ] **e8. Hierarchy setup.**
  - QBC: 87, 94.
  - Files: `bin/bh` (`intake` subcommand).
  - Done when, on a test repo, one approved run creates the milestone, the Projects board and the type labels (labels stand in for issue types in a personal repository), and a rerun changes nothing.
  - Size: S.

### f. Decisions and vetting (#13), design-affecting, depends on g

- [ ] **f1. Slimmer vetted-decision with a fresh judge** (RS-F2, RS-F4, RS-F6, IR-M5).
  - QBC: 32, 69, 70, 84.
  - Files: `skills/vetted-decision/SKILL.md`, `harness/lib/bhorch.py` (judge job).
  - Done when:
    - the job record shows a proposer job and a separate judge job; the judge sees the record and evidence only;
    - options are scored against the project's architecture targets and g1's ids;
    - an unverified rule reads "unknown", not fail, so in a fixture an OSS option is no longer beaten by existing code by default;
    - falsifying calls become measurer targets;
    - the skill cites rules by id and never restates them;
    - its load tokens before and after are recorded.
  - Size: L.
- [ ] **f2. vet-oss replaced by OpenSSF Scorecard, deps.dev and OSV-Scanner** (RS minor 3).
  - QBC: 84.
  - Files: `bin/bh` (`vet` subcommand), `skills/vet-oss/` (deleted).
  - Done when:
    - `bh vet <ecosystem> <package@version>` records the three tools' outputs as facts, with no model verdict;
    - the vet-oss skill is gone.
  - Size: M.
- [ ] **f3. Narrower bug-analysis, plus commitlint** (RS-F11). Needs e1, d4, c3.
  - QBC: 84.
  - Files: `skills/bug-analysis/SKILL.md`, `presets/commitlint`.
  - Done when:
    - the skill triggers only on recording a defect, not on any failing test;
    - per-typo issues, sibling sweeps, the termination block and the vetted-decision chain are gone;
    - the record is the e1 defect form;
    - with the commitlint preset written into the project's config and the pre-commit `commit-msg` stage, a local `fix:` commit without an issue ref is reported with teaching.
  - Size: M.

### g. Standards in place of the catalog (#14), design-affecting, no dependencies

- [ ] **g1. Standards data and a short house-rule list** (RS-F7, RS-F3).
  - QBC: 13, 18, 72, 85.
  - Files: new `standards/` data plus schema.
  - Done when:
    - each entry has standard, pinned version, control id and URL (OWASP ASVS, NIST SSDF SP 800-218, SP 800-53, SLSA, Well-Architected);
    - each house rule names its ladder rung and enforcing mechanism, or "judgement";
    - the data validates against its schema;
    - no entry cites only "Convention";
    - no rule prescribes a pass/fail gate.
  - Size: M.
- [ ] **g2. Map the old catalog** (RS-F7).
  - QBC: 72, 85, 8.
  - Files: `standards/mapping` data.
  - Done when every one of the 332 base and pack rule ids appears exactly once, checked by a script, mapped to:
    - a standard control id;
    - a house rule;
    - or "dropped", with a one-line reason.
  - Size: L.
- [ ] **g3. Readers switch to the new data; the old catalog goes.**
  - QBC: 85.
  - Files: `harness/lib/bhcore.py` (`standards`, `limits.packet_rules`), `agents/harness-reviewer.md`, `checks/index.json`, `catalog/` (deleted).
  - Done when:
    - a toy item's packet lists standard or house-rule ids;
    - no code reads `catalog/`, and `catalog/` is deleted;
    - `checks/index.json` points at house-rule ids and still runs until c5.
  - Size: M.

### h. Evals (#15), measured alongside a-g

- [ ] **h1. Outcome and cost evals** (RS-F12, IR-M15).
  - QBC: 3, 9, 28, 86.
  - Files: `evals/` (rebuilt).
  - Done when:
    - one toy item set runs in two arms, with the plugin and without, same model and prompts;
    - each item records met, measurer rounds, tokens and USD from the job records, and post-merge defects traced to it;
    - runs repeat (default 3, with an override), and the report shows both arms with their spread.
  - Size: L.
- [ ] **h2. Retire the wording graders** (RS-F12, RS minor 1).
  - QBC: 74.
  - Files: `evals/_gen/`, `evals/*`.
  - Done when:
    - no wording or read-count grader remains, and no stale results;
    - no prompt holds an absolute path;
    - the `tool_used` trigger checks pass for a4's descriptions.
  - Size: M.
- [ ] **h3. Per-slice metric and stop rule** (IR-M15). Waits on Q4.
  - QBC: 3, 28.
  - Files: `harness/lib/bhcore.py`, defaults table.
  - Done when:
    - the measurer records, per slice, rounds, tokens and post-merge defects;
    - the target and the stop rule are defaults with an override.
  - Size: S.

Task counts: a 5, b 14, c 9, d 11, e 8, f 3, g 3, h 3 (56).

## 5. Owner questions

- **Q1. Bot identity** (IR-M13). Create a GitHub App or machine account for agents, with per-role scopes, so that owner approvals are recorded under a login agents do not hold. This is an owner action. e7 waits on it.
- **Q2. Pin bumps** (IR-C2). They are "Mechanical" in the tier table but "pins" are a design-affecting trigger (QBC-25, QBC-27). Which list wins? A program cannot compute a tier from two conflicting lists. d3's default waits on it.
- **Q3. Minimal CI ahead of rollout step 5?** (IR-C3.4). Until then only agents are held, and e6 has nothing to react to. Moving it ahead changes QBC-95's order.
- **Q4. Default target and stop rule for the per-slice metric** (IR-M15.2). These are policy values. h3 waits on them.
- **Q5. The spike changes P3's Plane 2 mechanisms** (SP section 5). Confirm the four changes: b2, b4, d2 and d7 are built on them.
  1. H1 moves to SessionStart, or into the prompt, for program-launched builders. SubagentStart stays only for subagents (QBC-49).
  2. Builders get a `git clone`, not a worktree.
  3. A path whose refusal must teach gets no permission deny rule, because deny rules run before hooks and silence them.
  4. Notes for Bash come from PostToolUse or PostToolUseFailure, keyed on the sandbox's own error.
- **Q6. Spec text** (IR-E4, IR-E5). Move section 12 (design history) out of the spec into evidence. Replace the unbacked token figures (QBC-9, the tier table column) with b14 and h1's measured ones once they exist.

Residual spike risks, carried as facts rather than tasks:
- report forging that spares the canary (counter: the review trigger, d9);
- hooks under `--bare`, not tested (keep bare mode off);
- the hook-versus-deny ordering, now documented in SP section 3.

## 6. How ATDD follows

- A test author who is not the task's builder writes the acceptance tests for each task from its "done when", before the build, into protected paths. Each test names its task id and the QBC ids it covers, for example `test_b4_g2_forging_conftest_unmet  # QBC-65, QBC-15`.
- A task is done when the measurer says met for its tests. Its checkbox is crossed then, and not before.
- QBC ids not covered by a task are principles or records that tasks carry out, not testable on their own:
  - 1, 6, 7, 10, 11 and 14 are principles;
  - 64, 76 and 77 are covered by the plan's sections 2 and 4;
  - 78 and 97 are the order engine, carried by every b task;
  - 95 is the rollout order;
  - 96, 99, 100, 101 and 102 are decision records;
  - 2, 12 and 13 appear on tasks too.
- Rollout steps 4-6 (adoption in the pilot, the CI runner, generators) are outside slices a-h. Before step 4, f1 must ship (IR-M5).
