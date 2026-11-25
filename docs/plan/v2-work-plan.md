# agent-compliance v2: work plan

Status: plan, 2026-11-25, revised against spec §0 (6e18299). Tracking issue #7; slices a-h are #8-#15. Requirements: `docs/spec/quality-by-construction.md`. §0 (G1-G6, P1-P12, R1-R11) governs, then QBC-n. Decisions: `docs/adr/0001-quality-by-construction.md`. Evidence: `docs/design/evidence/`.

This plan lists work only. Each task:
- cites the §0 items it proves and the QBC ids it satisfies;
- names the files it touches;
- has a "done when" from which an agent that does not build it writes the acceptance tests;
- has a size: S is under a day, M is 1-3 days, L is more.

Finding ids are prefixed by source:
- IR- is `evidence/independent-review.md`;
- RH- is `evidence/review-harness.md`;
- RS- is `evidence/review-skills.md`;
- SP- is `evidence/spike-order-engine.md`;
- PC- is the plan check against §0 (C1, M1-M20, minors 1-13).

## 1. Rulings applied

These bind every task. They come from §0 and the owner, and are not re-argued.

- **The order engine is a program** (P3, R1). `bh` runs git, tests, measuring, ordering, staging and merging. Agents launch as `claude -p` jobs only for judgement. Measuring costs 0 tokens.
- **Paved road before restriction** (G3, P7, R5). Before any builder restriction ships, the program assembles the builder's packet with no agent, holding:
  - the visible acceptance tests (`verifier.acceptance_paths`), read-only, and the targets (`verifier.targets[*]`);
  - the rules with their teaching messages (`verifier.rules[*]`), and the ratchet baselines;
  - where the builder's own tests go (`paved_road.test_paths`), and how to add a dependency (`paved_road.dependency_command`);
  - one self-check command, `bh check`.
  
  Generators come later, once shapes recur (P10, QBC-95 step 6).
- **ATDD tests are visible** (R3). Integrity comes from measurement (R4):
  - the measurer lays the planner's tests and config over the build;
  - it runs the measured command in a `bwrap` jail with a canary, which is measurement protection (as a build runner isolates untrusted code in a container), not a builder restriction (PC-C1);
  - it records tampering as a fact.
  
  The only builder restrictions are the Bash sandbox and scoped Edit/Write. Each refusal teaches.
- **No quality gates** (P4). Refusals are for order only:
  - H0;
  - the launch preconditions: a failed sandbox self-test, or a builder account in a socket-granting group (R10);
  - an attempt to edit acceptance tests.
  
  Nothing refuses on size, and no git hook blocks a commit.
- **No hard-coding** (P8). Every limit is a default with an override in `.brick-harness/config.json`, under the config's existing keys. The file is optional: absent means defaults, and nothing generates it.
- **Nothing depends on CI or on accounts we cannot create** (P12). QBC-17 and QBC-52 are withdrawn.
- **Rules apply forward** (P11). Nothing is retrofitted: no sweeps, and no edits to old decision records.
- **Bootstrap.** b1 (the new measurer) and d6's test generator are built first and accepted by the plugin's plain pytest entry point. Every later task, including the rest of slices a and b, is measured by b1's measurer on tests the generator made from its rows, never by the 1.5.2 measurer (PC-M1).
- **Deterministic acceptance tests.** Model responses come from recorded fixtures, through a stub `claude` on PATH that replays recorded stream-json. Live, paid model runs happen only in slice h's evals (PC-M18).

Owner confirmation asked: the L2 packet format, d0 (the one contract for L3, L4 and L5). No other owner question is open.
- Q2 is answered by SemVer: patch and minor pin bumps are mechanical, major ones are design-affecting.
- Q4 is answered by DORA: change-failure rate and lead time, plus tokens per met slice.
- Q5 is accepted.
- Q6 is done in the spec (6e18299).
- Q1 and Q3 are dropped under P12.

## 2. Findings: disposition

### Plan check against §0 (PC)

| Finding | Resolution |
|---|---|
| PC-C1 the measure run executes builder code with the orchestrator's rights | b1: measured command in `bwrap` (only the checkout writable; tmpfs over orchestrator state and builder clones; no network) plus a canary. This protects measurement and is not a builder restriction |
| PC-M1 v2 tasks measured by the 1.5.2 measurer | Bootstrap: b1 first, accepted by plain pytest; everything after it is measured by b1 |
| PC-M2 no teaching refusal for Edit or Write on tests; b2's "or" | b9: a PreToolUse teaching refusal on Edit and Write of acceptance tests, with no deny rule on that path. b9 states one expected outcome per planted attempt |
| PC-M3 packet cannot fit its caps; size refusal; two copies | d0 and d1: only planner-written fields are capped; content over the cap is referenced by path; over the cap is a fact, never a refusal. d4: one channel, SessionStart |
| PC-M4 `bh check` cannot run in the sandbox | d3: runs inside the builder sandbox; tools pinned and installed at setup; no network at check time; no run lock; its temp and output paths are allowed; it states what it skips |
| PC-M5 paved road ships after restrictions | Order (section 3): b1, then d0-d3, then b9 |
| PC-M6 generators have no producer | Dropped from d2 (P10). c1 instead infers the test location and the dependency command |
| PC-M7 what the builder still guesses | d2: the packet names where its own tests go, how to add a dependency, how to ask for a config change, the rule and decision text it cites, and that the program commits. b1 overlays test and lint config sections, not dependency declarations |
| PC-M8 commit hooks refuse commits | c3 and f3: pre-commit and commitlint run in the test recipe and in `bh check`, and their results are facts with teaching. No blocking git hook is installed |
| PC-M9 d7's judge has no outcome | d7: the judge's `jobs[*]` entry carries `objections` and `falsifying_calls`. Calls become `verifier.targets[*]`; objections become facts for the approver. It never stops the item |
| PC-M10 hand-launched builder's Bash edits pass H0 | d8: a PostToolUse teaching note on Bash for the builder agent type with no packet, plus the H0-bypass fact. The measurer's scope fact also records it |
| PC-M11 measurer checkout unspecified | b1: a `git clone --shared` checkout. Its overhead target is stated on the toy repository as a default |
| PC-M12 docker group only a fact; `allowAllUnixSockets` default | b10: a builder account in a socket-granting group refuses the launch, with teaching to the orchestrator. `allowAllUnixSockets` defaults to false and is set only when the self-test needs it. Socket deny rules are not added (P10) |
| PC-M13 h1 rebuilds what the host has | h1 uses `claude plugin eval --ablation --runs --max-cost-usd` |
| PC-M14 h3 lacks DORA and a baseline | h3: change-failure rate, lead time and tokens per met slice, with a pre-v2 baseline computed from git and issue history |
| PC-M15 d5 still waits on Q2 | d5: SemVer, with a parsed lockfile and manifest diff and planted bumps |
| PC-M16 dependencies on things outside our control | Removed: the former e6 and e7 tasks, the approvals task, and e2's Action. The program runs the parent check at intake (e2) |
| PC-M17 g2 retrofit sweep | Removed. g2 maps only the ids that `checks/index.json`, skills and packets read; the rest are dropped in one line |
| PC-M18 paid, nondeterministic tests inside "met" | Recorded fixtures and a stub `claude` in every acceptance test. Paid runs only in h1 |
| PC-M19 approvals indistinguishable from agents | The approvals task is removed: it serves no G or R item, and P12 applies. Residual: no approval is identity-checked |
| PC-M20 Bash when the sandbox probe fails | b10: a failed self-test refuses the launch. b9: Bash is allowed only through `autoAllowBashIfSandboxed`, never pre-approved |
| PC excess: former e6 and e7, approvals, review trigger, g2 sweep, b8/d13 overlap, a5 filing, d7 judge | The former e6 and e7 and the approvals task are removed; the review trigger is kept as d11 (QBC-36, P6, NIST SSDF PW.7). g2 is cut down. b8 now holds the planted suite, so the two overlapping tasks are one. a5 files nothing. d7's judge has an outcome |
| PC minor 1 stale references | Fixed by this rewrite |
| PC minor 2 trigger for bringing back hidden tests | h3's change-failure rate (post-merge defects traced to a slice) is the named trigger |
| PC minor 3 ts-comment growth | b4: counted with `@typescript-eslint/ban-ts-comment` at base and candidate |
| PC minor 4 `gh repo view` network call | e4: `git remote get-url origin` |
| PC minor 5 missing limits; "2 pages" | d9 lists all of them with values; the record cap is in characters |
| PC minor 6 every-refusal test scope | b6: covers `harness/`, `bin/`, `hooks/`, `fitness/`, `presets/` |
| PC minor 7 approval message | Moot: the approvals task is removed |
| PC minor 8 forms' generic errors | e1: each required field's `description` carries the right way |
| PC minor 9 spec wording | Done in 6e18299 |
| PC minor 10 who reopens the checklist line | e5: the program, from the reviewer's structured output |
| PC minor 11 trigger paths in the packet | d2 |
| PC minor 12 "no Workflow" never asserted | b14: the builder's `--tools` list holds no Workflow |
| PC minor 13 a5 edits an old decision record | Removed from a5 (P11) |

### Independent review (IR)

| Finding | Resolution |
|---|---|
| IR-C1 builder controls what the measurer runs | b1 (overlay of tests, test and lint config, recipes and ratchet files from the plan commit; jail and canary); c4 (ratchets against the merge base); b4 (suppression, skip, ratchet-growth and dropped-test facts) |
| IR-C2 orchestrator grades itself; tier lists clash | d5 (tier from declared paths, then from the diff; SemVer for pins; re-queue; fact line); d4 (prompt from packet fields alone) |
| IR-C3 how plugin checks reach the human's build | c3 (presets in standard config files, run by the test recipe and pre-commit); the measurer runs only project recipes. The CI questions are withdrawn under P12 |
| IR-M1 H0 does not hold | b9 and d4 (a clone exists only from a packet, kept by digest outside the clone); d8 (H0 on Edit/Write, and a Bash note plus fact for hand launches) |
| IR-M2 held-out cases; red by error | Held-out cases dropped (R3), and back only if h3's change-failure rate shows the need. Red by error: b2 records it, d6 returns it to the test author |
| IR-M3 design-affecting tier has no design step | d7 (planner's delta, fresh judge with a defined outcome) |
| IR-M4 bug fixes graded by their builder | d6 (the finder or the test author writes the regression test; fails at the parent, passes at the fix) |
| IR-M5 L1 judged by its author | f1 |
| IR-M6 "gate" undefined | Settled by P4 and QBC-11/51. b7 ("stuck" at the round limit); e5 (Critical and Major review findings become defects with a failing test, d6) |
| IR-M7 facts have no readers | b7 |
| IR-M8 declared-data sources | Settled by ruling (CODEOWNERS, OpenAPI tags, database catalog). c7, c8 ("not checked" fact) |
| IR-M9 limits | d9 |
| IR-M10 teach() | b6 (plugin code); c6 (right-way data keyed by rule code) |
| IR-M11 runtime state | Packets and facts in the orchestrator's `.brick-harness/`, outside the clones (b9, d4) |
| IR-M12 v2 contents | This plan |
| IR-M13 agents act as the owner | Dropped under P12. Accepted residual |
| IR-M14 intake mechanics | e2 (atomic `createIssue(parentIssueId)`; the program checks parents at intake; a standing maintenance parent per owner); e5 (idle report at events); e3 (list found by label) |
| IR-M15 success measure | h3 (DORA plus tokens, against a pre-v2 baseline); b8 (planted test per gaming row) |
| IR-E1 to IR-E3 | H1 is the packet at SessionStart (d4); H2 writes through the scope-fact writer (d8); one packet schema (d0) |
| IR-E4, IR-E5 | Done in the spec (6e18299) |
| IR-m1 rules file in the packet | d0, d2: cited by id, with the cited lines in the packet file |
| IR-m2 two trigger lists | d5: one list, each trigger with a fresh-stack flag |
| IR-m3 coverage overstated | c5's parity report |
| IR-m4 Major count | Evidence correction only |
| IR-m5 review-trigger detector | d11 (paths inferred from standard files, overridable) |
| IR-m6 PostToolUse linter | Not planned: `bh check` (d3) is the paved road. Revisit only if h1 measures rounds lost to lint |
| IR-m7 pgTAP | c8 |
| IR-m8 published parts | c7, c8 |

### Earlier reviews (RH, RS), one task each

- **RH-K1 to RH-K8:**
  - K1: b9;
  - K2 and K4: c5;
  - K3: b8;
  - K5: b1 and b4;
  - K6 and K7: b2;
  - K8: b3.
- **RH-M1 to RH-M14:**
  - M1 and M12: b6;
  - M2: d6;
  - M3: d5;
  - M4: e4;
  - M5: c1;
  - M6: b5;
  - M7, M8 and M9: b12;
  - M10: d0 and d1;
  - M11: b11;
  - M13: b3;
  - M14: b7.
- **RH-m1 to RH-m13:**
  - m1, m2 and m3: b13;
  - m4: c5;
  - m5 and m12: a5;
  - m6: e4;
  - m7: a2;
  - m8: c1;
  - m9, m10, m11 and m13: b2.
  - RH section 5 duplications: b13.
- **RS-F1 to RS-F13:**
  - F1 and F13: a1;
  - F2, F4 and F6: f1;
  - F3: a3 and g1;
  - F5: a4;
  - F7: g1 and g2;
  - F8: c5;
  - F9: c3;
  - F10: e4;
  - F11: f3;
  - F12: h1 and h2.
- **RS minors:**
  - 1: h2;
  - 2: settled (built on `main`);
  - 3: f2.
- **SP residual risks:**
  - report forging that spares the canary is bounded by the jail (b1), and accepted as residual;
  - hooks under `--bare` are untested, so bare mode stays off.

## 3. Order and dependencies

1. **b1, the measurer, and d6's test generator.** Both are accepted by the plain pytest entry point; the generator turns every later task's rows into tests, and b1 measures them.
2. In parallel:
   - **a and g**;
   - **b2-b8 and b11-b14**;
   - **d0-d3, the packet format and the paved road.** These need only b1 (and b5 for d0), because d3 shares the measurer's code.
3. **b9 and b10, the builder restrictions and launch preconditions.** They come only after d0-d3 are met.
4. **c**, after b. c3, c4, c6 and c8 feed rule data into d2's packet as each lands.
5. **d4-d11**, after b9. d8 needs c7 for H2's owner line. d7 needs f1's judge.
6. **e**, after d (d9's limits, d6's test author).
7. **f**, after g. f3 also needs e1 and c3.
8. **h**, alongside:
   - h2 can start after a;
   - h1 needs b14;
   - h3 needs e (sub-issue history).

## 4. Tasks per slice

### a. Prune (#8), mechanical

- [ ] **a1. Move the shared lookup and judging method, then delete compliance-review and compliance-catalog** (RS-F1, RS-F13).
  - Proves: R9, G5. QBC: 64, 77, 79.
  - Files: `skills/compliance-review/`, `skills/compliance-catalog/`, `skills/{vetted-decision,vet-oss,bug-analysis,harness}/SKILL.md`, `evals/trigger-review/`, `evals/trigger-catalog/`.
  - Done when:
    - both skill directories and their eval directories are gone;
    - a grep for either name over `skills/ agents/ templates/ harness/ README.md` is empty;
    - the harness skill sends `overlay_candidates` to no skill;
    - every file a kept skill references exists.
  - Size: M.
- [ ] **a2. Delete the 9 unused `bh-*` CLIs and the dead functions** (RH section 5, RH-m7).
  - Proves: G5, P10. QBC: 76, 79.
  - Files: `bin/bh-{admit,branch,brief,commit,gaps,merge,rank,reconcile,state}`, `harness/tests/`, `harness/lib/bhcore.py`.
  - Done when:
    - `bin/` holds only `bh`, `bh-answer`, `bh-measure` and `bh-init` (removed in c1);
    - packet assembly and the other functions `bhorch` calls remain;
    - `_write_gaps_doc` and `_committed_finding_ids` are gone;
    - the tests that called the CLIs call the functions and pass;
    - a grep for the nine names over the skills and docs is empty.
  - Size: S.
- [ ] **a3. Templates** (RS-F3).
  - Proves: R9, P4. QBC: 79.
  - Files: `templates/`.
  - Done when:
    - `templates/` holds `plan-dry-run.md` and `bug-record.md` (removed in e1);
    - `catalog-audit.md`, `compliance-bindings.md` and `review-brief.md` are gone and nothing references them;
    - `plan-dry-run.md` asks for the guesses as a count, in a line `Guesses: <n>`, and contains none of the words BROKEN, PASS or FAIL.
  - Size: S.
- [ ] **a4. Trim skill descriptions** (RS-F5).
  - Proves: G5. QBC: 71, 79.
  - Files: `skills/*/SKILL.md` frontmatter.
  - Done when:
    - the total description characters of the kept skills are lower than at 1.5.2, with both numbers in the commit message;
    - no description names another skill;
    - no SKILL.md tells the agent to load another skill's file.
  - Size: S.
- [ ] **a5. README, manifest and harness docs claims** (RH section 7 docs rows, RH-m5, RH-m12).
  - Proves: G6, P5. QBC: 76, 79.
  - Files: `README.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `catalog/CHANGES.md`, `harness/README.md`, `harness/docs/lean-plan.md`.
  - Done when:
    - a grep finds none of the "industry-standard", "converge", PASS/FAIL, "every scoring bypass" or "up to three commands" claims;
    - one version string appears in plugin.json, marketplace.json and the changelog;
    - `harness/docs/lean-plan.md` is deleted, because this plan replaces it.
  - Size: S.

### b. Harness core (#9), design-affecting

- [ ] **b1. The measurer: trusted base, jail and canary** (bootstrap; PC-C1, PC-M11, IR-C1, RH-K5; SP G1-G3).
  - Proves: R4, R1, P6, G5. QBC: 15, 31, 35, 51, 65, 80.
  - Files: `harness/lib/bhcore.py` (`measure_item`, `overlay_plan`, `_protected`, `holdout_files`), `bin/bh-measure`.
  - Done when:
    - each (ref, mode) gets its own `git clone --shared` checkout;
    - from the plan commit, the measurer overlays:
      - all tests, not only the item's;
      - the test and lint config sections (`conftest.py`, `pytest.ini`, `pyproject.toml` `[tool.pytest*]`, `[tool.ruff*]` and `[tool.mypy*]`, `tsconfig*.json`, `.sqlfluff`, ESLint and oxlint config);
      - the entry-point recipe files and the ratchet files;
    - dependency declarations are not overlaid;
    - builder-added test config is set aside;
    - the measured command runs in `bwrap`: read-only `/`; tmpfs over `/tmp`, the orchestrator's `.brick-harness/` and the builder clones; only the checkout writable; no network;
    - a canary test that must fail runs alongside, and a passing canary records the `tampered` fact;
    - the holdout ref, `holdout_files` and their `tree_key` entries are removed;
    - `protected` defaults to these paths, and an empty list is a gap;
    - a config change the packet declares is measured from the plan commit, where a non-builder wrote it;
    - planted commits on the toy measure as follows:
      - G1, a gutted test: `met:false` with fact `M tests/…`;
      - G2, a forging `conftest.py`: `met:false`, fact `A conftest.py`;
      - G3, a report patch at import that also writes outside the checkout: `met:false`, `tampered`, and nothing written outside the checkout;
      - an edited test recipe: measured with the base recipe;
      - an honest commit: `met`;
    - the measurer's own overhead (checkout, overlay and jail, without the test command) is at most `limits.measure_overhead_s`, default 2 s, on the toy;
    - it is accepted by the plugin's plain pytest entry point, never the 1.5.2 measurer.
  - Size: L.
- [ ] **b2. Measurer correctness** (RH-K6, RH-K7, RH-m9, m10, m11, m13, IR-M2).
  - Proves: R3, R4. QBC: 34, 66.
  - Files: `harness/lib/bhcore.py`.
  - Done when:
    - each run writes to `out/<item>/<sha12>-<slot>`, with pairs deduped;
    - a missing or malformed JUnit file, a NaN or inf sample, and an unreadable target each give unmet plus a teaching fact, never an exception;
    - JUnit `<failure>` is recorded as red and `<error>` as red-by-error;
    - `tree_key` includes the plan files;
    - a test whose background child holds stdout is not recorded as a timeout;
    - two refs measured at the same time keep separate results.
  - Size: M.
- [ ] **b3. Merge guard tested, and an atomic merge** (RH-K8, RH-M13).
  - Proves: R4, P6. QBC: 66.
  - Files: `harness/lib/bhcore.py` (`merge_unmerged`, `_restore_guarded`), `harness/tests/test_toy.py`.
  - Done when:
    - a test on a met item asserts `unmerged == []`;
    - an unmet candidate never reaches HEAD, and the test turns red when the guard is removed;
    - a merge is one commit;
    - a conflict names its item;
    - `merge_unmerged` no longer calls `state()`.
  - Size: M.
- [ ] **b4. Diff facts against the base, without pattern lists** (IR-C1, RH-K5, PC minor 3).
  - Proves: R4, P11, P4. QBC: 8, 11, 15.
  - Files: `harness/lib/bhcore.py` (facts).
  - Done when each planted commit yields exactly its fact, never a refusal, and the opposite direction yields none:
    - JUnit ids present at base and missing at the candidate;
    - a grown JUnit skipped count;
    - grown suppressed findings: `ruff --ignore-noqa` and `eslint --no-inline-config` compared with normal runs, at base and candidate;
    - grown `@typescript-eslint/ban-ts-comment` findings.
  - c4 adds the ratchet-growth fact through the same writer.
  - Size: M.
- [ ] **b5. Dependencies through PEP 723 and uv; jsonschema replaces the hand-written validator** (RH-M6).
  - Proves: P2, G5. QBC: 13, 76, 80.
  - Files: `harness/lib/bhcore.py`, `bin/*`, `harness/schema/`.
  - Done when:
    - `validate()` and the `GAP_KINDS` literal are gone, with the kinds read from `gaps.schema.json`;
    - a schema keyword the old validator ignored rejects bad input in a test;
    - the suite passes under `uv run --script` from a pre-warmed cache with the network off.
  - Size: M.
- [ ] **b6. One teach() helper; gates become facts** (RH section 3, RH-M1, RH-M12, IR-M10, PC minor 6).
  - Proves: P5, P4, G3. QBC: 11, 12, 53, 54, 55, 56, 68.
  - Files: `harness/lib/*.py`, `bin/*`, `hooks/`, `fitness/`, `presets/`.
  - Done when:
    - `teach(rule, wrong, right, ref)` takes all four arguments as required;
    - repeats are grouped: the first `limits.findings_shown` (default 10), then a count;
    - a message is capped at `limits.message_chars` (default 300);
    - four former gates become facts with teaching, and the item stays ready: the commit gate on targets, the `env_setup` block, the tracker sha pin, and the catalogue-schema merge refusal;
    - every order refusal names its next step;
    - one test enumerates every refusal and non-zero exit in `harness/`, `bin/`, `hooks/`, `fitness/` and `presets/`, and asserts the shape `[rule] wrong -> right . ref` with a non-empty right part.
  - Size: M.
- [ ] **b7. Facts reach the orchestrator** (RH-M14, IR-M7, IR-M6).
  - Proves: G1, P4. QBC: 30, 35, 51.
  - Files: `harness/lib/bhorch.py`, `harness/README.md`.
  - Done when:
    - a table (fact, reader, action, channel) lists the facts slice b produces: scope, flaky, red-by-error, tampered, dropped tests, suppression growth, launch refused and stuck;
    - later tasks add their own rows (c1 inferred, c4 ratchet growth, c8 not checked, d5 re-queue, d8 H0 bypass);
    - the channel is `bh run`'s result JSON (`command` `run`) plus one line per item in its run report;
    - at `max_rounds` (default 3) an item is "stuck", reported for a re-plan;
    - each fact, planted on the toy with the stub `claude`, appears in the run report with its action.
  - Size: M.
- [ ] **b8. The planted gaming suite generates the safeguard register** (RH-K3, IR-M15; merges the former planted-suite task).
  - Proves: P6, R4. QBC: 15, 31, 58, 67.
  - Files: `harness/safeguards.json`, `harness/tests/test_safeguards.py`, `harness/tests/planted/`.
  - Done when:
    - every row of the levels and mechanisms tables has at least one planted test with a pytest marker naming its safeguard;
    - the new planted tests cover vacuous tests, endless retries and a hand launch; the other rows reuse the planted cases of b1, b4, b9, c4, d5 and d8;
    - the register's status comes from those markers and the JUnit results;
    - an entry citing a test that did not run or failed is reported;
    - no hand-kept status field remains.
  - Size: M.
- [ ] **b9. Builder clone and the cheap restrictions** (RH-K1, PC-M2, PC-M20; SP C2 and C5). After d0-d3.
  - Proves: R2, R4, P7. QBC: 15, 48, 65, 80, 100.
  - Files: `harness/lib/bhorch.py` (launch), `agents/harness-builder.md`, generated builder settings, `hooks/hooks.json`.
  - Why `git clone --shared`: 0.19 s and 220 KB on a 101 MB repository (against 1.8 s and 61 MB for `--no-local`), with refs separate from the source. Objects are immutable, and nothing is hidden.
  - Done when:
    - the builder works in a `git clone --shared` of the local base commit the program recorded, never a worktree, with no remote fetch;
    - the jobs dir and plugin root are not `--add-dir`;
    - file tools are scoped (`Edit(*)`, `Write(*)`) with `permissions.blockReadsOutsideWorkingDirectories: true`;
    - Bash is allowed only through `autoAllowBashIfSandboxed`, never pre-approved, with `allowUnsandboxedCommands: false`;
    - the sandbox has `denyWrite` on the clone's acceptance tests and packet files, the source repository, the orchestrator dir, the plugin root and orchestrator state under any temp dir, and no `denyRead`;
    - the program, not the builder, stages and commits;
    - each planted attempt has its one stated outcome:
      - Edit or Write of an acceptance test: a PreToolUse refusal with the SG-01 teaching line, and no deny rule on that path;
      - Bash `rm` or a write into tests: the sandbox's read-only error plus the PostToolUse SG-01 note;
      - Write of the orchestrator's packet: refused by the scoped file tools;
      - a Bash append to it: the orchestrator copy's digest is unchanged;
      - a ref deleted in the clone: the source refs are unchanged;
      - Write outside the clone: refused.
  - Size: M.
- [ ] **b10. Launch preconditions** (SP host finding 1, PC-M12, PC-M20, R10). After d0-d3.
  - Proves: R10, R4, P5. QBC: 12, 13, 80.
  - Files: `harness/lib/bhorch.py`, `harness/README.md`.
  - Done when, before each launch:
    - the program runs one sandboxed probe;
    - if the probe fails, or the builder account is in a group listed in `limits.socket_groups` (default `docker`), the launch is refused (an order refusal) with a teaching message to the orchestrator: set `network.allowAllUnixSockets: true` where AppArmor `bwrap-userns-restrict` applies (as on Ubuntu 26.04), run builders under an account outside socket-granting groups, or fix the profile;
    - `allowAllUnixSockets` defaults to false and is set only when the probe passes with it and fails without it; that choice is a fact;
    - each case is shown with a stubbed probe.
  - Size: M.
- [ ] **b11. Run lock and background run** (RH-M11).
  - Proves: R1, G5. QBC: 80.
  - Files: `harness/lib/bhorch.py`, `skills/harness/SKILL.md`.
  - Done when:
    - `bh run` holds a `flock` on its output dir, and a second concurrent `bh run` gets a teaching refusal;
    - `bh check` (d3) takes no lock;
    - the skill says to start `bh run` in the background and act on its exit notification.
  - Size: S.
- [ ] **b12. Gaps, findings and value order** (RH-M7, RH-M8, RH-M9, gaps.md row).
  - Proves: R9, G5. QBC: 80.
  - Files: `harness/lib/bhcore.py` (gap checks, rank, `value_queue`), `templates/`.
  - Done when:
    - a re-review that omits an open gap leaves it open;
    - a finding whose claimed impact cites no file:line is ranked as having no impact;
    - two gaps from different documents never share an id;
    - a missing `est_loc` is a gap, not 1;
    - `gaps.md` renders from a template, and a pipe in a summary renders;
    - links are checked by lychee.
  - Size: M.
- [ ] **b13. Orchestrator minors and duplicates** (RH-m1, m2, m3; RH section 5).
  - Proves: R1, G5. QBC: 76, 80.
  - Files: `harness/lib/bhorch.py`, `harness/lib/bhcore.py`.
  - Done when:
    - one builder's git failure yields a stuck entry, not an aborted run;
    - every launch carries `--max-budget-usd` from `budgets.job_usd`, so a round cannot exceed `budgets.run_usd`;
    - job cache keys include content digests of the skill and the standards data;
    - each of these has a test;
    - `harness/lib/` defines one git runner (today `bhcore._git` and `bhorch.git`), one `item_key` and one `fill`; the `rules.violations` target literal is written in one module (today `bhcore.py` and `bhrules.py`); `_waves` is gone and item order comes from `graphlib.TopologicalSorter`.
  - Size: S.
- [ ] **b14. End-to-end run on recorded fixtures.**
  - Proves: R1, P3. QBC: 9, 10, 78, 80.
  - Files: `harness/tests/fixtures/`, `harness/tests/test_e2e.py`.
  - Done when `bh run` on the toy, with the stub `claude` replaying recorded jobs, ends with every item met or stuck with facts, and `jobs[*]` shows:
    - no `jobs[*]` entry with `kind` `agent` for state, measure, merge, commit or ordering;
    - `jobs[*].tokens` (Claude CLI usage, input plus output) is the only stored token count; item and run totals are sums computed from it;
    - no `Workflow` in any builder's `--tools`.
  - Size: M.

### c. Convention over configuration (#10), design-affecting, after b

- [ ] **c1. Inference replaces `bh-init`** (RH-M5, RH-m8, RS-F10, PC-M7).
  - Proves: G6, P9, G3. QBC: 2, 60, 61, 63, 98.
  - Files: `harness/lib/bhcore.py` (Config), `bin/bh-init` (deleted), `harness/schema/harness.config.schema.json`.
  - Done when the program infers:
    - the test and verify entry points from justfile, Makefile, package.json scripts or pyproject;
    - languages from `git ls-files` with the linters' own mappings;
    - the dependency command from the lockfile (`uv add`, `npm install`, `pnpm add` and the like);
    - where the builder's own tests go, from pytest `testpaths` or the JS test runner config;
    - owners from CODEOWNERS and OpenAPI tags;
  - and further:
    - each inferred value is a fact naming its source file;
    - `bh run` works on the toy and on a Node fixture with no `.brick-harness/config.json`;
    - `bh-init` is gone.
  - Size: L.
- [ ] **c2. Ask once, into a standard file** (S option D).
  - Proves: P9, G6. QBC: 61, 63.
  - Files: `harness/lib/bhcore.py`, `skills/harness/SKILL.md`.
  - Done when, on a fixture without CODEOWNERS:
    - one question is asked;
    - the answer, once approved, is written to CODEOWNERS (or an OpenAPI tag, or a recipe line), never to a plugin file;
    - a rerun asks nothing.
  - Size: M.
- [ ] **c3. Presets in the project's standard config files, run by the build** (IR-C3, RS-F9, PC-M8).
  - Proves: R7, G2, P4. QBC: 4, 5, 16, 19, 57, 62, 81.
  - Files: new `presets/`.
  - Done when:
    - with approval, preset fragments are written into the project's `pyproject.toml`, ESLint config, `.sqlfluff` and `tsconfig`:
      - ruff DTZ, S105-S108, PLR2004, and TID251 with `msg`;
      - ESLint or oxlint `no-restricted-*` with `message`;
      - sqlfluff AM04;
      - TypeScript `strict`;
    - also with approval, they go into a `.pre-commit-config.yaml` of `repo: local` hooks whose tools are pinned in the project's dev dependencies;
    - the project's test recipe runs `pre-commit run --all-files`;
    - no git hook is installed;
    - with Claude Code absent, the test recipe reports a planted naive datetime;
    - the measurer runs only project recipes.
  - Size: L.
- [ ] **c4. Ratchets against the base** (IR-C1).
  - Proves: P11, R5. QBC: 8, 19.
  - Files: `harness/lib/bhcore.py`, `presets/`.
  - Done when:
    - baselines (per-file-ignores, `.sqlfluffignore`, the generated `ignore_imports`, the strict-tsconfig include list, pinned test hashes) are generated at adoption and compared with the merge base;
    - a planted growth of each (a shrink, for the include list) yields b4's fact;
    - the opposite direction yields none.
  - Size: M.
- [ ] **c5. Parity, then retire the ast-grep checks** (RS-F8, RH-K2, RH-K4, RH-m4, IR-m3).
  - Proves: R7, R9, P11. QBC: 8, 23, 73, 81.
  - Files: `checks/`, `harness/checkers.json`, `harness/lib/bhrules.py`, `harness/tests/test_no_waiting.py`, `harness/tests/test_no_project_terms.py`.
  - Done when:
    - a parity report runs the old ast-grep rule and the new linter configuration on every `valid` and `invalid` case of `checks/tests/{HO-02,ID-15,RL-08}.{python,typescript}-test.yml`, and lists, per rule, the cases each one catches;
    - only rules that pass parity are retired, and a failed parity keeps the old check, recorded;
    - no download code and no `rules.violations` target remain;
    - `test_no_waiting.py` is replaced by ruff TID251 over `harness/`.
  - Size: M.
- [ ] **c6. Right-way text for fixed-message rules** (IR-M10).
  - Proves: P5, R5. QBC: 12, 57.
  - Files: `presets/` (right-way data keyed by rule code), `harness/lib/bhcore.py`.
  - Done when:
    - a relayed PLR2004 miss carries its right-way line;
    - the text is overridable in `.brick-harness/`;
    - an enabled rule code with no entry is a fact.
  - Size: S.
- [ ] **c7. Owners lookup in the plugin** (IR-M8, IR-m8).
  - Proves: G6, P9. QBC: 13, 62.
  - Files: `bin/bh` (`owners`), `harness/lib/`.
  - Done when:
    - `bh owners <path|topic>` returns owner, package, database roles and operations on a fixture;
    - it reads CODEOWNERS, OpenAPI tags, the database catalog (through the libpq `PG*` or `DATABASE_URL` environment), package.json `exports`, `__all__` and workspace members;
    - a missing source gives a "not declared" fact naming the file to add.
  - Size: M.
- [ ] **c8. Generic fitness functions as a standalone CLI** (IR-M8, IR-m7).
  - Proves: G2, R7. QBC: 18, 19, 62.
  - Files: new `fitness/`, `presets/` (recipe line).
  - Done when:
    - a vet record for pgTAP at its pinned version (its OpenSSF Scorecard, deps.dev and OSV results, and the decision to use it or not) is committed at `docs/design/evidence/vet-pgtap.md`;
    - the project's test recipe runs four checks: one owner per object, each database object's owner equals its declared owner, grants match the declared roles, and import boundaries from published parts (generated import-linter or dependency-cruiser config, with the ignore list as a ratchet);
    - a planted wrong owner, grant and import are each reported with teaching;
    - an unsupported stack, or no database, gives "not checked", never met.
  - Size: L.
- [ ] **c9. Wiring facts.**
  - Proves: G2. QBC: 20, 21, 22.
  - Files: `harness/lib/bhcore.py`.
  - Done when a fixture with a linter config or check that no recipe runs gives a fact naming it.
  - Size: S.

### d. Flow (#11), design-affecting

d0-d3 need only b1 (d0 also needs b5's jsonschema). d4-d11 come after b9.

- [ ] **d0. L2 packet format.**
  - Proves: R5, R3, G3, P1, P6. QBC: 24, 31, 33, 37, 38, 39, 42.
  - Files: new `harness/schema/packet.schema.json`, `harness/lib/bhcore.py` (validation and Markdown rendering).
  - Done when:
    - one JSON Schema (draft 2020-12), validated by the `jsonschema` library and rendered to Markdown for agents, is the single contract that the test author (L3), the builder (L4) and the measurer (L5) read;
    - it has these fields:
      - `id`;
      - `parent_issue`;
      - `tier`, derived mechanically (d5);
      - `goal`: the intent and why, with no design;
      - `applies`: the G, P and R items copied verbatim from spec §0, with all principles always included, and their QBC ids;
      - `constraints`: cited decision lines, owners and published interfaces, declared paths, and limits as defaults;
      - `acceptance`: Gherkin scenarios, each with `id`, `traces_to` (G, P, R or QBC ids) and `verification` (one of test, lint, fitness, measure; ISO/IEC/IEEE 29148);
      - `verifier`: the exact checks the measurer runs: `acceptance_paths` (the visible acceptance tests, protected), `targets[*]` (items of {id, item, metric, op, value, unit}), `rules[*]` (each with `id` and its teaching message; the packet's `applies` holds only G, P, R and QBC ids) and the ratchet baselines;
      - `paved_road`: `test_paths` (where the builder's own tests go), `dependency_command` (how to add a dependency) and the self-check command, with the same names in the project config and the packet, copied with no mapping;
      - `definition_of_done`: every `acceptance[*]` item met by the measurer;
    - content over the size cap is referenced by path;
    - a design field fails validation, and so does a scenario without `traces_to` or `verification`;
    - the measurer runs exactly the `verifier` list, and `bh check` (d3) runs the same list;
    - rendering a fixture packet gives stable Markdown (a golden-file test).
  - Size: M.
  - Also d0: each stage's output format and the single-contract enforcement, per `docs/spec/packet-standards.md` ("Every stage's output format"): MADR (L1), packet JSON (L2), generated tests with a manifest and JUnit XML (L3), Conventional Commits with `Packet:`/`Acceptance:` trailers (L4), JUnit XML, SARIF 2.1.0 and a result JSON (L5), SARIF (review). Every output names the packet sha256.
- [ ] **d1. Packet assembly against d0; size is never refused** (IR-E3, RH-M10, PC-M3, IR-m1).
  - Proves: R5, P4, P8. QBC: 24, 33, 37, 38, 39, 40, 42.
  - Files: `harness/lib/bhcore.py` (packet assembly).
  - Done when:
    - the program assembles every packet as a d0 instance that validates, with constraints cited by id;
    - a mechanical packet may name the exact edit in its goal;
    - only the planner-written fields count toward `sizing.packet_tokens` (default 1,600, as bytes/4);
    - text over the cap is moved to a file in the packet directory and referenced by path, and over the cap is a fact;
    - no launch is refused for size.
  - Size: M.
- [ ] **d2. The paved road in the packet** (G3, PC-M6, PC-M7, PC minor 11).
  - Proves: G3, G1, R5, P7. QBC: 24, 38, 49, 54, 57.
  - Files: `harness/lib/bhcore.py` (packet assembly), `harness/schema/`.
  - Done when, for a toy item, the program (no agent) fills d0's `acceptance`, `verifier` and `paved_road` fields and writes the rendered packet into the clone's read-only packet directory, and a schema check confirms each part:
    - `verifier.acceptance_paths` (the visible acceptance tests) and `verifier.targets[*]` with numbers;
    - `verifier.rules[*]`: the lint and fitness rules enabled at the plan commit for the touched files, each with its teaching message (c3, c6, c8), and the ratchet baselines present at the plan commit (c4); on the toy with presets applied this includes ruff DTZ with its right-way line;
    - the text of every cited rule and decision line;
    - `bh check` (d3);
    - `paved_road.test_paths` and `paved_road.dependency_command` (c1);
    - the tier-trigger paths (d5);
    - that the program commits;
    - how to ask for a config change: say so in the final report.
  - Size: M.
- [ ] **d3. `bh check`, the self-check inside the builder sandbox** (PC-M4; shift-left).
  - Proves: G1, G3, R5. QBC: 16, 51, 55.
  - Files: `bin/bh` (`check`), `harness/lib/bhcore.py`.
  - Done when:
    - `bh check` measures the clone's working tree through b1's code against the packet's d0 `verifier` list (same overlay, recipes and rules, not a copy), in a temp dir under the clone;
    - it takes no lock;
    - it runs with the network off, the tools pinned and installed at setup, and the uv and pre-commit caches pre-warmed;
    - it prints only the missed checks' teaching messages, and states what it skips (fresh-stack runs);
    - on planted trees, inside the sandbox settings of b9, its list of missed checks equals the measurer's;
    - nothing refuses a finish without it.
  - Size: M.
- [ ] **d4. Packet custody and delivery** (SP section 5, IR-C2, IR-E1).
  - Proves: R5, P6. QBC: 24, 46, 48, 49.
  - Files: `harness/lib/bhorch.py`, `hooks/hooks.json`.
  - Done when:
    - the authoritative packet is kept by digest in the orchestrator's `.brick-harness/`;
    - it arrives once, at SessionStart `additionalContext`, with the prompt a fixed line that names no goal;
    - a packet edited inside the clone changes nothing the program reads;
    - SubagentStart is not used for program launches.
  - Size: M.
- [ ] **d5. Tier from paths and diff; SemVer for pins** (IR-C2, IR-m2, PC-M15).
  - Proves: R6, P6, P8. QBC: 25, 27, 30.
  - Files: `harness/lib/bhorch.py`, plugin defaults table.
  - Done when:
    - one trigger list (contracts, migrations and schema, role and grant files, compose files, major-version pins, the budgets file) is data with an override, each trigger flagged for fresh-stack runs;
    - pin changes come from a lockfile and manifest diff parsed by version (`packaging.version`, npm `semver`): patch and minor are mechanical, major is design-affecting;
    - the tier is set from declared paths at launch and recomputed from the diff;
    - a diff hit re-queues the item, with the fact "tier X from paths Y";
    - planted cases come out as stated: a minor bump stays mechanical, a major bump re-tiers, and a docs-only packet whose diff touches compose is re-queued.
  - Size: M.
- [ ] **d6. Test author first (L3): rows, then generated tests** (RH-M2, IR-M2, IR-M4; keyword-driven testing, `docs/spec/packet-standards.md` L3).
  - Proves: R3, P6, P3, R9. QBC: 31, 34, 41, 82.
  - Files: new `agents/harness-test-author.md`, new test generator under `harness/lib/`, `harness/lib/bhorch.py`.
  - Done when, with recorded fixtures:
    - the program launches the test author before the builder, as another job; it writes acceptance rows from the closed catalogs of `docs/atdd/catalog.yaml` into the packet's `acceptance`, valid against the acceptance criteria schema, and writes no test code;
    - the generator, a program with no agent, turns each row into exactly one test in the project's framework, marked with its acceptance id, plus a manifest from acceptance id to test node id, and both are committed in protected paths in the plan commit;
    - a row whose keyword the generator does not implement is a fact with teaching naming the keyword, never a skipped or empty test;
    - every generated test is red on main: a test that fails by an assertion is recorded red, one that errors is recorded red-by-error and its row goes back to the test author;
    - for a defect, the regression row is written by the test author, or by the finder when the finder is not the builder, and "fails at the parent, passes at the fix" is recorded;
    - `jobs[*]` shows test author, generator (a `program_step`), builder and measurer (a `program_step`), in that order;
    - the generator's bootstrap, which generates the plugin's own v2 acceptance tests from `docs/atdd/criteria/`, is accepted by the plugin's plain pytest entry point, as b1 is.
  - Size: L.
- [ ] **d7. Design step for design-affecting items, with a judge whose outcome is defined** (IR-M3, PC-M9).
  - Proves: P6, P4, G1. QBC: 26, 41, 69.
  - Files: `agents/harness-planner.md`, `harness/lib/bhorch.py`, `harness/schema/jobs.schema.json`.
  - Done when, with recorded fixtures:
    - the planner writes the contract, schema or role delta as a declared file in the plan commit;
    - a fresh judge job (`jobs[*].kind` `agent`, `role` `judge`) records `objections` and `falsifying_calls` in its `jobs[*]` entry;
    - each falsifying call becomes an item in `verifier.targets[*]`, and each objection becomes a fact shown to the approver;
    - the item is never stopped by the judge;
    - `jobs[*]` shows planner, judge, test author and builder as distinct entries, each with `kind` `agent` and its `role`.
  - Size: M.
- [ ] **d8. Hooks H0 and H2; a note for hand-launched Bash** (IR-M1, IR-E2, PC-M10).
  - Proves: R5, P5, P4. QBC: 29, 43, 44, 45, 46, 47, 50.
  - Files: `hooks/hooks.json`, `hooks/*.py`.
  - Done when:
    - each guard has `onFailure: block`;
    - H0 (PreToolUse on Edit and Write) refuses the builder agent type's edit when no packet is registered, with QBC-47's text;
    - a PostToolUse on Bash for that agent type with no packet adds QBC-47's line and records the H0-bypass fact, which the measurer's scope fact also records;
    - H2 (PreToolUse) shows one owner line from c7 on the first touch outside the packet's paths: at most `limits.h2_chars` (default 200), once per path, written through the scope-fact writer, never blocking;
    - no hook reads file contents for patterns;
    - the main session and human sessions are never refused;
    - each case is shown by feeding recorded hook inputs to the hook scripts.
  - Size: M.
- [ ] **d9. Limits table** (IR-M9, PC minor 5).
  - Proves: P8. QBC: 13, 27, 32, 33, 55, 90.
  - Files: plugin defaults table, `harness/schema/harness.config.schema.json`.
  - Done when every limit is read from one table, with overrides in `.brick-harness/config.json` under the existing keys. Defaults:
    - `concurrency` 5;
    - `sizing.packet_tokens` 1,600;
    - `limits.message_chars` 300;
    - `limits.findings_shown` 10;
    - `limits.h2_chars` 200;
    - `limits.record_chars` 6,000 (the 2-page decision record);
    - `max_rounds` 3;
    - `commands.timeout_s` 600;
    - `limits.flaky_reruns` 0;
    - `limits.idle_days` 14;
    - `limits.known_issues` 100;
    - `limits.measure_overhead_s` 2;
    - `limits.socket_groups` [docker];
    - `sandbox`, the Claude Code `sandbox` settings object passed verbatim into the builder's settings, with `sandbox.network.allowAllUnixSockets` false;
    - `evals.runs` 3;
    - `models.<role>` for each agent role (planner, judge, test_author, builder, reviewer);
    - `tiers.triggers`.
    
  Also:
    - an override that differs from the default (for example `limits.idle_days` 7, `evals.runs` 5) changes behaviour in a test;
    - with 6 ready items, at most 5 agents run;
    - ruff PLR2004 is clean over `harness/`.
  - Size: M.
- [ ] **d10. Harness skill.**
  - Proves: R9, G3. QBC: 59, 82.
  - Files: `skills/harness/SKILL.md`.
  - Done when the skill:
    - names the tiers, the test-author step, the packet and `bh check`;
    - references no deleted skill;
    - has no more characters than 1.5.2's.
  - Size: S.

- [ ] **d11. Independent review of security-sensitive diffs** (QBC-36, IR-m5).
  - Proves: P6, G1, P4, P8. QBC: 31, 36.
  - Files: `harness/lib/bhorch.py` (replaces `AUTH_RE`), `agents/harness-reviewer.md`, plugin defaults table.
  - Standards: NIST SSDF PW.7; OWASP SAMM design and implementation review.
  - Done when, with recorded fixtures:
    - the program launches a fresh reviewer job, one that neither planned, tested nor built the item, only when the item's whole diff across all rounds touches the security-sensitive paths: auth, keys, grants, money or signatures;
    - those paths are inferred from standard files (OpenAPI `securitySchemes` and secured operations, role and grant files, money types, key and signing paths), are overridable in `.brick-harness/config.json` (`review.triggers`), and `AUTH_RE` is gone;
    - a planted split diff still triggers the review, and a diff outside those paths launches none;
    - findings are recorded as facts on the item and handed to e5; the review never changes met or blocks a merge.
  - Size: M.

### e. Intake (#12), design-affecting, after d

- [ ] **e1. Issue forms.**
  - Proves: R8, G4, P5. QBC: 83, 87, 88.
  - Files: `templates/.github/ISSUE_TEMPLATE/{decision,slice,defect}.yml` and `config.yml`; `templates/bug-record.md` (deleted).
  - Done when:
    - the three forms validate against GitHub's issue-form schema;
    - each requires parent, goal and acceptance;
    - each required field's `description` carries the right way;
    - blank issues are off;
    - with approval, the forms are written once into the project's `.github/`;
    - `bug-record.md` is gone.
  - Size: M.
- [ ] **e2. Parent set atomically, checked by the program** (IR-M14, PC-M16).
  - Proves: R8, G4, P12. QBC: 88, 89.
  - Files: `harness/lib/bhtracker.py`.
  - Done when, against a recorded GitHub API fixture:
    - the plugin files issues with GraphQL `createIssue(parentIssueId)`, so an agent-filed issue has its native parent at creation;
    - at intake the program links a form's parent field as a sub-issue;
    - an issue still parentless gets QBC-88's message once;
    - for a defect in code with no tracking issue, the message names the owner's standing maintenance tracking issue (from CODEOWNERS), which is created on first need;
    - no GitHub Action is required.
  - Size: M.
- [ ] **e3. Known issues as a bounded backlog** (IR-M14).
  - Proves: R8, G4, P8. QBC: 90.
  - Files: `harness/lib/bhtracker.py`.
  - Done when:
    - the list is found by label;
    - each line names its parent;
    - at `limits.known_issues` (default 100) a new line is refused with teaching: fix and remove one first;
    - a second labelled list is a fact.
  - Size: S.
- [ ] **e4. Intake keeps the body; the repo comes from the git remote** (RH-M4, RS-F10, RH-m6, PC minor 4).
  - Proves: R8, G6. QBC: 75, 83.
  - Files: `harness/lib/bhtracker.py`, `harness/adapters/`.
  - Done when:
    - an admitted issue's full body is the packet's goal source;
    - the repo is read from `git remote get-url origin`, with no bindings file;
    - an issue a human closed is not reopened;
    - `list` filters before its limit;
    - one bad claim does not abort the admission;
    - `room` is read under the lock.
  - Size: M.
- [ ] **e5. Tracking-issue lifecycle; review findings** (IR-M14, IR-M6, PC minor 10).
  - Proves: R8, G4, P3. QBC: 91, 92, 93.
  - Files: `harness/lib/bhtracker.py`.
  - Done when:
    - the program reopens the slice's checklist line from the reviewer's structured output, and a Critical or Major finding becomes a defect sub-issue whose regression test the test author writes (d6);
    - a defect found inside the packet's paths is fixed in the slice, and one found outside is filed through e2;
    - closing the last sub-issue closes the tracking issue;
    - a tracking issue with no sub-issue event for `limits.idle_days` is a fact in the next `bh run` report, with no timer.
  - Size: S.
- [ ] **e6. Hierarchy setup.**
  - Proves: R8, G4. QBC: 87, 94.
  - Files: `bin/bh` (`intake`).
  - Done when, against a recorded API fixture, one approved run creates the milestone, the Projects board and the type labels (labels stand in for issue types in a personal repository), and a rerun changes nothing.
  - Size: S.

### f. Decisions and vetting (#13), design-affecting, after g

- [ ] **f1. Slimmer vetted-decision with a fresh judge** (RS-F2, RS-F4, RS-F6, IR-M5).
  - Proves: R9, P6, P2. QBC: 32, 69, 70, 84.
  - Files: `skills/vetted-decision/SKILL.md`, `harness/lib/bhorch.py` (judge job).
  - Done when, with recorded fixtures:
    - proposer and judge are separate jobs, and the judge receives only the record and the evidence;
    - options are scored against the project's architecture targets and g1's ids;
    - an unverified rule reads "unknown", not fail, so a fixture OSS option is not beaten by existing code by default;
    - falsifying calls become measurer targets;
    - a record over `limits.record_chars` goes back to the proposer with teaching;
    - the skill cites rules by id;
    - SKILL.md has fewer characters than 1.5.2's.
  - Size: L.
- [ ] **f2. vet-oss replaced by OpenSSF Scorecard, deps.dev and OSV-Scanner** (RS minor 3).
  - Proves: R9, P2. QBC: 84.
  - Files: `bin/bh` (`vet`), `skills/vet-oss/` (deleted).
  - Done when:
    - `bh vet <ecosystem> <package@version>` records the three tools' outputs as facts (with recorded responses in its tests), with no model verdict;
    - the vet-oss skill is gone.
  - Size: M.
- [ ] **f3. Narrower bug-analysis; commitlint as a fact** (RS-F11, PC-M8).
  - Proves: R9, P4, P5. QBC: 84.
  - Files: `skills/bug-analysis/SKILL.md`, `presets/commitlint`.
  - Done when:
    - the description triggers only on recording a defect;
    - SKILL.md no longer says a bug is any defect "however small", and has no `Siblings:` line, no termination paragraph ("touches a termination", "termination tier") and no `vetted-decision` step;
    - the record is e1's defect form;
    - commitlint runs in the test recipe and in `bh check` over the item's commits;
    - a `fix:` commit without an issue ref becomes a fact with teaching;
    - no commit-msg git hook is installed.
  - Size: M.

### g. Standards in place of the catalog (#14), design-affecting

- [ ] **g1. Standards data and a short house-rule list** (RS-F7, RS-F3).
  - Proves: R9, P1. QBC: 13, 18, 72, 85.
  - Files: new `standards/` data and schema.
  - Done when:
    - every entry has standard, pinned version, control id and URL (OWASP ASVS, NIST SSDF SP 800-218, SP 800-53, SLSA, Well-Architected);
    - every house rule names its ladder rung and mechanism, or "judgement";
    - the data validates against its schema;
    - no entry cites only "Convention".
  - Size: M.
- [ ] **g2. Readers switch to the new data; the old catalog goes** (PC-M17).
  - Proves: R9, P11. QBC: 8, 72, 85.
  - Files: `harness/lib/bhcore.py` (`standards`, `limits.packet_rules`), `agents/harness-reviewer.md`, `checks/index.json`, `catalog/` (deleted).
  - Done when:
    - only the rule ids that `checks/index.json`, skills or packets read are mapped to standard or house-rule ids;
    - the other catalog ids are dropped, with one line in the changelog;
    - a toy packet lists only g1 ids;
    - no code reads `catalog/`, and it is deleted;
    - `checks/index.json` still runs until c5.
  - Size: M.

### h. Evals (#15), measured alongside

- [ ] **h1. Outcome and cost evals on the host's eval runner** (RS-F12, PC-M13).
  - Proves: R9, R11, P2, G5. QBC: 9, 28, 86.
  - Files: `evals/` (rebuilt as `claude plugin eval` suites).
  - Done when:
    - `claude plugin eval --ablation --runs <evals.runs> --max-cost-usd <budget>` runs the toy item set with and without the plugin;
    - the report gives, per arm, met, measurer rounds (from `bh` `jobs[*]` entries), tokens (summed from `jobs[*].tokens`) and USD, with spread;
    - the paid toy run is committed as evidence;
    - this is the only task that makes live model calls.
  - Size: L.
- [ ] **h2. Retire the wording graders** (RS-F12, RS minor 1).
  - Proves: R9, G5. QBC: 74.
  - Files: `evals/_gen/`, `evals/*`.
  - Done when:
    - no wording or read-count grader and no stale results remain;
    - no prompt holds an absolute path;
    - the `tool_used` trigger checks run as `claude plugin eval` cases for a4's descriptions.
  - Size: M.
- [ ] **h3. DORA metrics and the pre-v2 baseline** (PC-M14).
  - Proves: R11, G5. QBC: 3, 28.
  - Files: `bin/bh` (`metrics`), `harness/lib/bhtracker.py`.
  - Done when `bh metrics` computes, from git, the issue history and `jobs[*]` entries:
    - change-failure rate: merged slices that later get a defect sub-issue;
    - lead time: from the slice sub-issue opening to its merge;
    - tokens per met slice;
  - and also:
    - the same metrics for the pre-v2 period are written once as the baseline file;
    - both are shown side by side;
    - the tests run on a recorded history fixture.
  - Size: M.

Task counts: a 5, b 14, c 9, d 12, e 6, f 3, g 2, h 3 (54).

## 5. How ATDD follows

- A test author who is not the task's builder writes each task's acceptance criteria from its "done when" as keyword rows (`docs/atdd/criteria/<slice>.yaml`, closed catalogs in `docs/atdd/catalog.yaml`), before the build. No agent writes test code: d6's generator turns each row into one test in protected paths, marked with its criterion id and the §0 and QBC ids it proves, for example `test_b1_AC15  # R4, QBC-65`.
- The tests are deterministic:
  - model output comes from recorded fixtures through the stub `claude`;
  - GitHub and registry responses come from recorded fixtures;
  - there is no network.
- A task is done when b1's measurer says met for its generated tests. b1 and the generator's bootstrap are accepted by the plain pytest entry point. The checkbox is crossed then, and not before.
- A slice is done when every §0 item its tasks cite is proven (§0, line 9).
- QBC ids cited on no task, because no single task tests them:
  - 1, 6, 7 and 14 are principles that the tasks carry out;
  - 17 and 52 are withdrawn;
  - 95 is the rollout order;
  - 96, 97, 99, 101 and 102 record decisions.
- Rollout steps 4-6 (adoption in the pilot, generators) are outside slices a-h. f1 ships before step 4.
