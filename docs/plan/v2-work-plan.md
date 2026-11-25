# agent-compliance v2: work plan

Status: plan, 2026-11-25, revised against spec §0 (6e18299). Requirements: `docs/spec/quality-by-construction.md`. §0 (G1-G6, P1-P12, R1-R11) governs, then QBC-n. Decisions: `docs/adr/0001-quality-by-construction.md`. Evidence: `docs/design/evidence/`.

This plan lists work only. Each task:
- cites the §0 items it proves and the QBC ids it satisfies;
- names the files it touches;
- has a "done when" from which an agent that does not build it writes the acceptance tests;
- has a size: S is under a day, M is 1-3 days, L is more.

Release scope: slices a, b (b1-b5, b9) and d (d0-d4, d6, d8, d10). The other former ids (b6-b8, b10-b14, c, d5, d7, d9, d11, e, f, g, h) return only on a measured need from real use.

Finding ids are prefixed by source:
- IR- is `evidence/independent-review.md`;
- RH- is `evidence/review-harness.md`;
- RS- is `evidence/review-skills.md`;
- SP- is `evidence/spike-order-engine.md`;
- PC- is the plan check against §0.

## 1. Rulings applied

These bind every task. They come from §0 and the owner, and are not re-argued.

- **The order engine is a program** (P3, R1). `bh` runs git, tests, measuring, ordering, staging and merging. Agents launch as `claude -p` jobs only for judgement. Measuring costs 0 tokens.
- **Paved road before restriction** (G3, P7, R5). Before any builder restriction ships, the program assembles the builder's packet with no agent, holding:
  - the visible acceptance tests (`verifier.acceptance_paths`), read-only, and the targets (`verifier.targets[*]`);
  - the rules with their teaching messages (`verifier.rules[*]`);
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
  - an attempt to edit acceptance tests.
  
  Nothing refuses on size, and no git hook blocks a commit.
- **No hard-coding** (P8). Every limit is a default with an override in `.brick-harness/config.json`, under the config's existing keys. The file is optional: absent means defaults, and nothing generates it.
- **Nothing depends on CI or on accounts we cannot create** (P12). QBC-17 and QBC-52 are withdrawn.
- **Rules apply forward** (P11). Nothing is retrofitted: no sweeps, and no edits to old decision records.
- **Bootstrap.** b1 (the new measurer) and d6's test generator are built first and accepted by the plugin's plain pytest entry point. Every later task, including the rest of slices a and b, is measured by b1's measurer on tests the generator made from its rows, never by the 1.5.2 measurer (PC-M1).
- **Deterministic acceptance tests.** Model responses come from recorded fixtures, through a stub `claude` on PATH that replays recorded stream-json. No acceptance test makes a live, paid model call.

Owner confirmation asked: the L2 packet format, d0 (the one contract for L3, L4 and L5). No other owner question is open.

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
| PC-M6 generators have no producer | Dropped from d2 (P10) |
| PC-M7 what the builder still guesses | d2: the packet names where its own tests go, how to add a dependency, how to ask for a config change, the rule and decision text it cites, and that the program commits. b1 overlays test and lint config sections, not dependency declarations |
| PC-M10 hand-launched builder's Bash edits pass H0 | d8: a PostToolUse teaching note on Bash for the builder agent type with no packet, plus the H0-bypass fact. The measurer's scope fact also records it |
| PC-M11 measurer checkout unspecified | b1: a `git clone --shared` checkout. Its overhead target is stated on the toy repository as a default |
| PC-M18 paid, nondeterministic tests inside "met" | Recorded fixtures and a stub `claude` in every acceptance test |
| PC-M20 Bash when the sandbox probe fails | b9: Bash is allowed only through `autoAllowBashIfSandboxed`, never pre-approved |
| PC minor 3 ts-comment growth | b4: counted with `@typescript-eslint/ban-ts-comment` at base and candidate |
| PC minor 9 spec wording | Done in 6e18299 |
| PC minor 11 trigger paths in the packet | Dropped with the tier derivation; d2 names the other parts |
| PC minor 13 a5 edits an old decision record | Removed from a5 (P11) |

### Independent review (IR)

| Finding | Resolution |
|---|---|
| IR-C1 builder controls what the measurer runs | b1 (overlay of tests, test and lint config, recipes and ratchet files from the plan commit; jail and canary); b4 (suppression, skip and dropped-test facts) |
| IR-C2 orchestrator grades itself | d4 (prompt from packet fields alone) |
| IR-M1 H0 does not hold | b9 and d4 (a clone exists only from a packet, kept by digest outside the clone); d8 (H0 on Edit/Write, and a Bash note plus fact for hand launches) |
| IR-M2 held-out cases; red by error | Held-out cases dropped (R3). Red by error: b2 records it, d6 returns it to the test author |
| IR-M4 bug fixes graded by their builder | d6 (the finder or the test author writes the regression test; fails at the parent, passes at the fix) |
| IR-M11 runtime state | Packets and facts in the orchestrator's `.brick-harness/`, outside the clones (b9, d4) |
| IR-M12 v2 contents | This plan |
| IR-M13 agents act as the owner | Dropped under P12. Accepted residual |
| IR-E1, IR-E3 | H1 is the packet at SessionStart (d4); one packet schema (d0) |
| IR-E4, IR-E5 | Done in the spec (6e18299) |
| IR-m1 rules file in the packet | d0, d2: cited by id, with the cited lines in the packet file |
| IR-m4 Major count | Evidence correction only |
| IR-m6 PostToolUse linter | Not planned: `bh check` (d3) is the paved road |

### Earlier reviews (RH, RS), one task each

- **RH-K1, K5, K6, K7, K8:** K1: b9; K5: b1 and b4; K6 and K7: b2; K8: b3.
- **RH-M2, M6, M10, M13:** M2: d6; M6: b5; M10: d0 and d1; M13: b3.
- **RH-m5, m7, m9-m13:** m5 and m12: a5; m7: a2; m9, m10, m11 and m13: b2.
- **RS-F1, F3, F5, F13:** F1 and F13: a1; F3: a3; F5: a4.
- **RS minor 2:** settled (built on `main`).
- **SP residual risks:**
  - report forging that spares the canary is bounded by the jail (b1), and accepted as residual;
  - hooks under `--bare` are untested, so bare mode stays off.

## 3. Order and dependencies

1. **b1, the measurer, and d6's test generator.** Both are accepted by the plain pytest entry point; the generator turns every later task's rows into tests, and b1 measures them.
2. In parallel:
   - **a**;
   - **b2-b5**;
   - **d0-d3, the packet format and the paved road.** These need only b1 (and b5 for d0), because d3 shares the measurer's code.
3. **b9**, the builder restrictions. It comes only after d0-d3 are met.
4. **d4, d6, d8 and d10**, after b9.

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
    - `bin/` holds only `bh`, `bh-answer`, `bh-measure` and `bh-init`;
    - packet assembly and the other functions `bhorch` calls remain;
    - `_write_gaps_doc` and `_committed_finding_ids` are gone;
    - the tests that called the CLIs call the functions and pass;
    - a grep for the nine names over the skills and docs is empty.
  - Size: S.
- [ ] **a3. Templates** (RS-F3).
  - Proves: R9, P4. QBC: 79.
  - Files: `templates/`.
  - Done when:
    - `templates/` holds `plan-dry-run.md` and `bug-record.md`;
    - `catalog-audit.md`, `compliance-bindings.md` and `review-brief.md` are gone and nothing references them;
    - `plan-dry-run.md` asks for the guesses as a count, in a line `Guesses: <n>`, and contains none of the words BROKEN, PASS or FAIL.
  - Size: S.
- [ ] **a4. Trim skill descriptions** (RS-F5).
  - Proves: G5. QBC: 71, 79.
  - Files: `skills/*/SKILL.md` frontmatter.
  - Done when:
    - the longest description of the kept skills is shorter than the longest at 1.5.2; the measurer computes both counts from the `v1.5.2` tag and the tree, so no commit message carries them (history is immutable);
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
    - each run writes to `<measure_out>/<item>/<sha12>-<slot>` (default `.brick-harness/out`), with pairs deduped;
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
  - Size: M.
- [ ] **b5. Dependencies through PEP 723 and uv; jsonschema replaces the hand-written validator** (RH-M6).
  - Proves: P2, G5. QBC: 13, 76, 80.
  - Files: `harness/lib/bhcore.py`, `bin/*`, `harness/schema/`.
  - Done when:
    - `validate()` and the `GAP_KINDS` literal are gone, with the kinds read from `gaps.schema.json`;
    - a schema keyword the old validator ignored rejects bad input in a test;
    - the suite passes under `uv run --script` from a pre-warmed cache with the network off.
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
### d. Flow (#11), design-affecting

d0-d3 need only b1 (d0 also needs b5's jsonschema). d4, d6, d8 and d10 come after b9.

- [ ] **d0. L2 packet format.**
  - Proves: R5, R3, G3, P1, P6. QBC: 24, 31, 33, 37, 38, 39, 42.
  - Files: new `harness/schema/packet.schema.json`, `harness/lib/bhcore.py` (validation and Markdown rendering).
  - Done when:
    - one JSON Schema (draft 2020-12), validated by the `jsonschema` library and rendered to Markdown for agents, is the single contract that the test author (L3), the builder (L4) and the measurer (L5) read;
    - it has these fields:
      - `id`;
      - `parent_issue`;
      - `tier`: mechanical or design-affecting;
      - `goal`: the intent and why, with no design;
      - `applies`: the G, P and R items copied verbatim from spec §0, with all principles always included, and their QBC ids;
      - `constraints`: cited decision lines, owners and published interfaces, declared paths, and limits as defaults;
      - `acceptance`: Gherkin scenarios, each with `id`, `traces_to` (G, P, R or QBC ids) and `verification` (one of test, lint, fitness, measure; ISO/IEC/IEEE 29148);
      - `verifier`: the exact checks the measurer runs: `acceptance_paths` (the visible acceptance tests, protected), `targets[*]` (items of {id, item, metric, op, value, unit}), `rules[*]` (each with `id` and its teaching message; the packet's `applies` holds only G, P, R and QBC ids);
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
    - `verifier.rules[*]`: the lint and fitness rules enabled at the plan commit for the touched files, each with its teaching message;
    - the text of every cited rule and decision line;
    - `bh check` (d3);
    - `paved_road.test_paths` and `paved_road.dependency_command`;
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
- [ ] **d6. Test author first (L3): plain acceptance tests in the project's own framework** (RH-M2, IR-M2, IR-M4; ATDD, `docs/spec/packet-standards.md` L3).
  - Proves: R3, P6, P3, R9, G6. QBC: 31, 34, 41, 82.
  - Files: `agents/harness-test-author.md`, `harness/lib/bhorch.py`, `harness/schema/packet.schema.json`.
  - Done when, with recorded fixtures:
    - the test author, another job launched before the builder, returns the packet's `acceptance` criteria (`id`, `scenario`, `traces_to`, `verification`) and one test file in the project's own framework, each test's name carrying its criterion id;
    - the program writes that file at `verifier.acceptance_paths` (protected) and commits it with the packet, the plan commit, whose `Packet:` trailer names the kept packet;
    - `bh run` takes each ready item from the plan to a packet the program writes (no agent), then the test author, the builder, the measurer and the merge, in one run;
    - the red run on main is the one measurer's run of the project's own test command (JUnit XML): every criterion has a test that fails by an assertion, and no test of the file errors (an import or collection error is not red); otherwise the file goes back to the test author, at most `max_rounds` times; criteria whose tests already pass on main make the item met with no build;
    - a defect packet carries `kind` `defect`, `parent` and `found_by`; its regression test is written by the `found_by` agent when that agent is not the builder, and otherwise by the `test_author` job; "passes at the fix" is recorded only when the measurer observes it green at the builder's result;
    - `jobs[*]` shows test author, red run (a `program_step`), builder and measurer (a `program_step`), in that order;
    - the bootstrap of the plugin's own rows is accepted by the plugin's plain pytest entry point, as b1 is; the keyword catalog and the row engine stay the plugin's own test tooling, and a user project never needs them (G6).
  - Size: L.
- [ ] **d8. Hook H0; a note for hand-launched Bash** (IR-M1, IR-E2, PC-M10).
  - Proves: R5, P5, P4. QBC: 29, 43, 44, 45, 46, 47, 50.
  - Files: `hooks/hooks.json`, `hooks/*.py`.
  - Done when:
    - a guard blocks by two documented mechanisms, each with one job: a guard that crashes, times out or cannot start must not let the call through, so each hook handler in `hooks/hooks.json` has `onFailure: block` (the handler field of Claude Code v2.1.295 and later, under `hooks.<event>[*].hooks[*]`); a guard's own refusal is a PreToolUse `hookSpecificOutput.permissionDecision: deny` with a reason;
    - H0 (PreToolUse on Edit and Write) refuses the builder agent type's edit when no packet is registered, with QBC-47's text, through `permissionDecision: deny`; a packet is registered when the program wrote its file under `.brick-harness/packets/` at launch (d4 custody), and the hooks read only Claude Code's hook-input fields (`session_id`, `agent_id`, `agent_type`, `cwd`, `tool_input`) plus that directory, never a packet id in the input;
    - a PostToolUse on Bash for that agent type with no packet adds QBC-47's line and records the H0-bypass fact, which the measurer's scope fact also records;
    - no hook reads file contents for patterns;
    - the main session and human sessions are never refused;
    - each case is shown by feeding recorded hook inputs to the hook scripts.
  - Size: M.
- [ ] **d10. Harness skill.**
  - Proves: R9, G3. QBC: 59, 82.
  - Files: `skills/harness/SKILL.md`.
  - Done when the skill:
    - names the tiers, the test-author step, the packet and `bh check`;
    - references no deleted skill;
    - has no more characters than 1.5.2's.
  - Size: S.

Task counts: a 5, b 6, d 8 (19).

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
- Rollout steps 4-6 (adoption in the pilot, generators) are outside slices a, b and d.
