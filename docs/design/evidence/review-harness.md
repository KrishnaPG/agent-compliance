# Harness runtime review: agent-compliance v1.5.2

## 0. Which code was reviewed (read this first)

The checkout at `~/workspace/agent-compliance` is **stale**:
- It is on branch `harness-lean` at `1566a95`, which is 10 commits behind remote `main` = release v1.5.2 = `c02e524` (`git fetch --dry-run` shows it).
- The local `origin/main` ref still points at `7fff403` (v1.5.1). No local branch or worktree is newer than `c02e524`.
- In the release, `harness/workflows/*.js` (1,485 lines), `harness/lib/prelude.js` (170) and `tests/test_workflows.py` are deleted. `harness/lib/bhorch.py` (1,399), `harness/schema/jobs.schema.json` (275), `bin/bh` and `agents/harness-*.md` replace them.
- So a verdict on the checkout's workflows would judge code the owner can no longer run.

Installed copies disagree:

| Where | Version | Commit | Note |
|---|---|---|---|
| user scope | 1.4.0 | `16aab49` | old main; still has the workflows, where "a cheap agent runs each tool" (checkout README:47-48) |
| altmetrics project | 1.5.2 | `c02e524` | |
| marketplace clone | — | `c02e524` | |

Which version this session loads is undetermined. The harness agents are listed as available, which points to 1.5.1 or later, but the user-scope install record says 1.4.0. Settle this before anyone uses it.

This review is of `c02e524`, extracted read-only to the scratchpad directory `ac152/`. Every `path:line` below is against that tree.

Side effects on the original repository:
- `git fetch --dry-run` added 13 loose objects to `.git/objects`, `c02e524` among them.
- No ref, branch, index or working-tree file changed; `git status` is clean, `HEAD` is `1566a95` and `origin/main` is `7fff403`.
- All runs used copies in the scratchpad.

**Method**
- I read `bhorch.py`, `bin/bh`, `agents/*.md`, `skills/harness/SKILL.md`, README, `safeguards.json`, `test_safeguards.py`, `docs/lean-plan.md` and `docs/findings.json`.
- Four scoped subagents covered the rest; I spot-checked their key claims against the code:
  - opus: measurer, merge, state;
  - sonnet: mutation testing;
  - sonnet: tracker, rule checks, init;
  - sonnet: gaps, rank, value, packet.
- Full suite on the release copy: **297 passed, 2 skipped**, 163 s. The 2 skips are the Beads tests (`bd` not on PATH).


## 1. Verdict in brief

**The shape of 1.5.2 is right; the code is not yet safe to rely on.**

What is right, and should be kept:
- One program, `bh`, runs every mechanical step itself.
- Agents start only for judgement work, each as a headless `claude -p` job with a schema and a budget.
- The deterministic measurer alone decides what is met.
- Results are cached by document digest and tree.
- The cost of every job is recorded.
- The orchestrator fixed the old version's worst flaw, an agent in the mechanical path.

Why it is not safe yet:
- **The anti-gaming structure is open.** A builder can read and delete the held-out cases (K1), and by default no tests are protected at all (K5).
- **The measurer can be wrong.** It can record a failing ref as met (K6) and can crash instead of failing closed (K7). The test that claims an unmet candidate is never merged misses the case that matters (K8).
- **The rules target is either a gate or empty.** It blocks every item on non-linux-x86_64 hosts (K2), and it is vacuous or gameable elsewhere (K4).
- **The register's own test proves nothing** (K3).
- **Nothing has been proven in a real run.** The release holds no record of the paid toy run that the lean plan defines as "done". `README:96` says it "still has to prove" itself, and `findings.json` H-1 is open (M10).

Gaps against the intended flow:
- No stage writes tests before the build (M2).
- There are no tiers, and decisions never become work (M3).
- Issue intake loses the issue body (M4).

Size and rules:
- The 8.8k lines are still 8.9k, 6.9k of them code.
- A self-imposed "standard library only" rule keeps the re-implementations the lean plan promised to replace (M6).
- Five gates remain (section 3).

## 2. Findings

Totals: 8 Critical (K1-K8), 14 Major (M1-M14), 13 Minor (m1-m13), 27 theoretical minors discarded.

Each finding: severity, `path:line`, problem, evidence, fix. "Spot-checked" means I re-read the cited code myself.

### Critical

**K1. SG-01's "gaming is impossible by construction" is false for the builder.**
- The builder has the whole `Bash` tool, not a command prefix (`agents/harness-builder.md:6`), plus `Write` and `Edit`, under `--permission-mode dontAsk` (`bhorch.py:365-368`).
  - The code knows bare `Bash` means every command: it narrows only the review job to `git diff/log/show` (`bhorch.py:352-353`).
- The builder works in a `git worktree add --detach` of the same repository (`bhorch.py:711-718`), so it shares every ref with the main checkout.
- The plugin root is one of its `--add-dir` directories (`bhorch.py:354`). The CLI describes these as "more directories Claude can access".
- **Reproduced** in a throwaway repo:
  - From a worktree, `git show refs/brick-harness/holdout:test_holdout.py` printed the hidden test.
  - `git update-ref -d refs/brick-harness/holdout` removed the ref for the main repo too.
  - An absent ref makes `holdout_files` return nothing ("empty when the ref is absent", `bhcore.py:768-772`). The held-out cases then drop out of measurement without a word: **fail-open**.
- **Inferred from the code, not reproduced:**
  - The measurer reads targets from the invoking checkout's working file (`bhcore.py:877-878`).
  - The only target guard compares that file with HEAD (`bhcore.py:1199-1208`).
  - So a target the builder lowers and commits in the main checkout is scored and never flagged.
  - Writes to the plugin root, `bhcore.py` included, are open to it.
- The only barrier is prose: "write nothing outside it" (`agents/harness-builder.md:13-14`).
- The claims are at `harness/README.md:183`, at `harness/README.md:318`, where the tests are said to cover "every scoring bypass", at `safeguards.json` SG-01 (lines 5-18: "never in a builder's checkout") and in the register's `about`.
- Fix, host first:
  - run each builder in a separate `git clone --no-local --single-branch` with no harness refs and no plugin root in `--add-dir`, then fetch its commit back;
  - add the host's Bash sandbox, if the pinned Claude Code version has one, to keep writes inside the clone;
  - record an absent holdout ref as a fact.
- Effort M.

**K2. `rules.violations == 0` is a gate by environment.** Reproduced.
- The plugin's own catalog is on by default. On a raw copy of the toy, `bhrules.active` is True, with 6 checks and 3 selected for python.
- With `platform.system` and `platform.machine` patched to Darwin and arm64, `bhcore.measure` recorded `csv-reader` **unmet**: every real target was met (`tests.failed` 0, `tests.passed` 2, the bench target met), and `rules.violations` was "not measured". The only error was "checker: no pinned release asset for Darwin-arm64".
- `bhrules.py:227` accepts only `linux-x86_64` (`checkers.json` pins one asset).
- On macOS, on arm64, offline, or after a failed download, `violations` is None (`bhrules.py:289-291`).
- Every item then gets an unmet target it cannot meet (`bhrules.py:261-268`), so the run never meets anything.
- The `error` text does not say how to fix it.
- The exe is trusted on the zip's sha, not its own (`bhrules.py:231`), so a crash mid-extract leaves a binary that stays broken.
- Fix:
  - use `ast-grep` from PATH, or pinned through `uvx --from ast-grep-cli==0.51.3`, npm, brew or mise;
  - with no checker, record a fact and add no target;
  - delete `ensure` and `_sha`.
- Effort S. (Tracker/rules subagent; spot-checked.)

**K3. `test_safeguards.py` does not back the README's claim** that it "fails when an entry claims more than its tests show" (`README:183`).
- It checks only that each listed name matches some `^def test_` in `tests/` (`test_safeguards.py:17-21,47-48`) and that `kind == "gate"` iff `status == "to-remove"` (`:38-41`).
- The kind is self-declared.
- Evidence, by mutation, in a scratch copy:
  - SG-05's tests replaced by the unrelated grep test `test_no_generic_machine_or_model_terms`;
  - an invented "impossible by construction" mechanism added;
  - a refuse-to-merge gate labelled `structure` added;
  - all 3 tests stayed green.
- It also passes SG-15 as `implemented` on two tests that are skipped here: `test_every_operation_against_real_beads` and `test_admission_and_reconcile_through_real_beads`, both skipped because `bd` is not on PATH.
- Fix: lean-plan W15, which was promised and not done (`docs/lean-plan.md:71`).
  - Tests carry `@pytest.mark.sg("SG-05")`.
  - The register's test list is generated from the JUnit result, counting only passed tests.
  - An entry whose tests did not run is `partial`.
- Effort S.

**K4. The `rules.violations == 0` target, added to every item, is vacuous in two ways.** From the code, not reproduced.
- **Nothing is scanned on an uncovered stack.** `total` starts at 0 and only scanned files add to it (`bhrules.py:295-323`). The base checks are selected, but they match only `.py`, `.ts` and `.sql` extensions (`EXT`, `:41-45`). On a Go, Rust or Java project no file is scanned, and the target reads "0 violations, met".
- **A builder can exempt its own file.**
  - The bound facts come from a text regex over whole files, comments included: `ENTRY` (`bhrules.py:50`) and `OUTBOX` (`:56-63`), read by `_modules_matching` (`:120-129`).
  - A bound module is removed from that rule's scan (`:298-300`).
  - So a comment holding `Router(` exempts a file from ID-15, and one holding `INTO outbox` exempts it from HO-02 (`checks/index.json` binds).
  - These are hand-maintained patterns too (rule: no hand-maintained pattern lists).
- Fix:
  - add the target only when at least one check ran, and record the stacks left unchecked as a fact;
  - match bound modules with an ast-grep rule over the AST, or have the owner name them once through a gap.
- Effort S.

**K5. SG-01 guards no tests out of the box.** Reproduced.
- In a scratch copy of the toy, with `protected` removed as `bh-init` leaves it, the item's tests were replaced by `def test_nothing(): pass` and a wrong implementation was added. `bh-measure` recorded the item `met`: `tests.passed` 1, `tests.failed` 0.
- The run used the test fixture, which points at an empty catalog, so rule checks were off. With them on, the RL-08, HO-02 and ID-15 checks would not catch a gamed test either.
- `protected` defaults to `[]` (`bhcore.py:256`), `bin/bh-init` never writes it, and no gap reports it empty.
- So only plan files are overlaid. A builder can edit its acceptance tests, bench and runner scripts and is measured on its own edits.
- Every item's default targets are `tests.failed == 0`, `tests.errors == 0` and `tests.passed >= 1` (`agents/harness-planner.md:21`, `bhcore.py:1989-1993`). So a builder that swaps the item's tests for one trivial passing test is measured met.
- `harness.config.schema.json:270` says "the measurer fails a ref that changes one", which contradicts the overlay design.
- Fix: guard the test command's own files and test configuration by default, report an empty `protected` as a gap, and record the JUnit test ids that are missing compared with HEAD as a fact.
- Effort S. (Measurer subagent, trigger; spot-checked.)

**K6. Two measurements of one item share an output folder, so a failing ref can be recorded met.**
- `record` and `measure_item` both use `out/<item>` (`bhcore.py:894,932-933`).
- `_result_path` deletes the earlier result file before the command writes a new one (`:613-618`).
- So two `bh-measure` processes for one item at two refs read each other's JUnit or bench file.
- **What triggers it.** Build rounds pass one ref per item, so the race needs two refs for one item in a single `measure_all`, with concurrency at its default of 2 (`bhorch.py:279`) and no dedupe of the pairs (`bhorch.py:573,581-583`). Any of these does it:
  - two applied harvest picks touching the same item: harvest refs carry no items, so `affected()` fans out per ref (`bhorch.py:987`);
  - an item without paths, which is in every ref (`bhcore.py:1121-1122`), plus two or more refs;
  - a manual `bh measure --item X@a --item X@b`.
- **Reproduced**, by the measurer subagent and then by me, with its script (`scratchpad/exp-scripts/race.py`), which forces the interleaving.
  - A ref whose test reported 1 passed, against a target of `passed >= 3`, was recorded `met` with `tests.passed = 3`, read from the other ref's report.
- Fix: give each run its own folder (`out/<item>/<sha12>-<slot>`) and dedupe the pairs.
- Effort S.

**K7. `bh-measure` crashes instead of failing closed.**
- A scoped npm name in `standards.stack`, such as `@types/node@20`, does not match the regex. `m.group` is then called on None (`bhcore.py:1052-1054`) whenever a ref changed a lockfile.
- Test output that is not valid UTF-8 raises `UnicodeDecodeError` in `_run(text=True)` (`bhcore.py:382-394`).
- `bin/bh-measure:37-41` catches only `HarnessError`, so no JSON is printed and the exit code is 1, the code for "unmet".
- The orchestrator records "not measured" (`bhorch.py:558-568`). Nothing reaches the scoreboard, so the same crash repeats every round.
- Both were reproduced by the measurer subagent; I re-ran its script (`AttributeError: 'NoneType' object has no attribute 'group'`, exit 1, no JSON) and confirmed each on its own:
  - the regex does not match `@types/node@20`;
  - `Popen(text=True).communicate()` on the bytes `\\377\\376` raises `UnicodeDecodeError`.
- Fix:
  - skip stack entries that do not match;
  - decode with `errors="replace"`;
  - in `bin/`, catch every exception and print a JSON error with exit 2.
- Effort S.

**K8. The test that claims "an unmet candidate is never merged" does not test the case that matters.**
- `test_toy.py:562-571`, `test_merge_takes_refs_from_the_scoreboard_only`, has the docstring "an unmet candidate on its branch is never merged, whatever a caller says".
- It uses an item with no met current result. So the guard that keeps a newer **unmet** candidate of a **met** item out of `unmerged` is never exercised: `sd == "met-unmerged"` (`bhcore.py:1673`). That guard is what keeps, for example, a harvest ref that broke a met item out of HEAD.
- Evidence: with the guard removed, the full suite stays green, 297 passed. The mutation subagent found this; I re-ran it serially myself.
- The test whose setup does make exactly that case asserts only status and readiness, never `unmerged` (`test_toy.py:171-181`).
- The code is right today. But the test's claim is vacuous for that case, so nothing would catch a regression that merges a failing ref.
- Fix: add `assert s["unmerged"] == []` to `test_toy.py:181`, and point the `:562` test at a met item.
- Effort S.

### Major

**M1. The commit gate on targets stalls every build.** Reproduced.
- `commit_harness` refuses the whole harness commit while `targets.json` drops or changes a target that HEAD has (`bhcore.py:1182-1186`).
- That is a content refusal, not an order refusal. The harness's own finding H-3 is still open (`docs/findings.json`).
- Because one commit carries everything, a single changed target makes every later commit fail: scoreboard, gaps and plan. Then `phase_build` marks every ready item failed: "plan files still uncommitted" (`bhorch.py:881-889`).
- Reproduction: a scratch toy run with the plugin's fake `claude`.
  - I changed one target of `csv-reader` (`tests.failed == 0` to `== 1`) without committing it.
  - `bh run --skip gaps plan harvest` then:
    - marked both ready items failed, `csv-reader` and `json-writer`;
    - logged three refused commits;
    - measured nothing (`unmeasured: 3`);
    - stopped with "no progress".
- The message, "the owner commits that", does not say what to do or how to prevent it.
- The guard is also incomplete. Commands are part of the target digest (`bhcore.py:414-423`), yet a weakened command in `bricks.json` commits freely.
- It is a dead end. `merge_unmerged` then refuses every round with "commit the plan files first (bh-commit)" (`:1344`), and `bh-commit` refuses again.
- Fix:
  - commit every other harness file regardless;
  - leave the moved targets uncommitted and listed as an owner fact;
  - make the measurer read the targets from HEAD (`git show HEAD:…`), not from the working file (`bhcore.py:878`), so an uncommitted lowering has no effect.
- Effort S.

**M2. No stage writes tests first.**
- The intended flow puts tests written by a non-builder before the build. No job does that:
  - the planner "invents nothing" and writes only items, targets and contracts (`agents/harness-planner.md:14,19-24`);
  - `bricks.schema.json` has no tests field;
  - the packet carries test commands, not test files (`bhcore.py:3604-3637`).
- Nothing writes `refs/brick-harness/holdout`. It is only read (`bhcore.py:753-772`); only a test creates it (`tests/test_measurer_safeguards.py:46`).
- `protected` assumes the acceptance tests already exist (`README:278`). The toy ships them hand-written.
- A review finding "becomes work only as a failing test" (`README:165-167`), but nothing turns a finding into a test, so findings pile up in `gaps.json`.
- Fix: add a `tests` job.
  - It is a fresh agent that did not build.
  - It writes acceptance tests, and held-out tests to the holdout ref, from the contract and targets.
  - Its output becomes the protected paths.
- Effort M.

**M3. There are no tiers, and decisions never become work.**
- Item `kind` is `brick | system | change` (`bricks.schema.json:27-31`). There is no tier for mechanical, design-affecting or epic work, so:
  - a one-line mechanical change goes through gaps, plan, packet and builder like an epic;
  - nothing routes design-affecting work to `vetted-decision`.
- Decisions (`D-n`, `standards.decisions`) only settle gaps (`bhcore.py:3349-3381`; `agents/harness-planner.md:28`). A new decision produces no item unless the owner edits the build order.
- Fix: add a `tier` field and route by it. A recorded decision should be an input the planner turns into `change` items.

**M4. Issue intake loses the issue body.**
- `admit` passes only `{ref, id, title}` (`bhtracker.py:492-494`).
- The planner has no Bash (`agents/harness-planner.md:6`), yet it is told to quote targets "from the tracker entry" (`:19`). It cannot.
- GitHub: `ready` ignores `{parent}` (`adapters/github.json:10`), so `tracker.goal` has no effect.
- GitHub: `claim` cannot fail (`:13`), so two runs can take the same issue.
- Reconcile reopens every closed entry whose item is not met (`bhtracker.py:552-555`). That includes a human's "won't fix" or duplicate close, on every run, so the harness fights the tracker's owner.
- Fix:
  - put the entry body in the planner's input;
  - use `{parent}` in the `ready` command;
  - reopen only entries this actor closed, and report the rest as a fact.
- (Tracker subagent; the first two points spot-checked.)

**M5. Stack detection is a hand-maintained pattern list.**
- It is built from `EXT`, `SKIP_DIRS` and file-name sets (`bhrules.py:41-46,99-117`), and covers only python, typescript and sql.
- The config's `ecosystems` uses its own words: the sample says "node" (`examples/sample.config.json:62`) while `detect()` says "typescript".
- The two vocabularies are never reconciled.
- Fix: let ast-grep's own language mapping and `git ls-files` decide.
- (Tracker/rules subagent; spot-checked.)

**M6. "Standard library only" is the root cause of most re-implementation.**
- The rule is stated at `bhcore.py:3-4` and `bhtracker.py:28`.
- It produced:
  - a JSON-Schema subset validator (`bhcore.py:130-202`), although jsonschema is already a test dependency. It silently ignores keywords it does not implement. Reproduced by the measurer subagent: `validate` passes a tracker entry with `ref: ""` although `tracker.schema.json:17` sets `minLength: 1`. It checks the plan, the config, the catalogue and every agent output (`bhorch.py:531`);
  - a Markdown link checker (`bhcore.py:2189-2204,2259-2282`), written after lychee was considered and rejected (`bhcore.py:15-17`). It gives false positives:
    - it misses `~~~` fences;
    - it does not exclude inline code;
    - it does not handle `#L10` anchors;
    - it does not number duplicate heading slugs;
    - it emits one gap per link, with no cap;
  - a JSON-path mapper (`bhtracker.py:128-154`) in place of `gh --jq`/`jq`;
  - a YAML-frontmatter reader (`bhorch.py:122-139`);
  - a release downloader (K2);
  - a ~135-line hand-built gaps.md renderer (`bhcore.py:2714-2848`; `|` breaks tables);
  - eight lockfile readers (M14).
- The lean plan's wave 2, which was to replace these, did not happen (`docs/lean-plan.md:24-40`, `:80`).
- Fix: PEP 723 inline dependencies run by `uv run --script` (or a uv lock, as `lean-plan.md:79` planned). Then delete the re-implementations.
- Effort M.

**M7. Gap learning hides new questions.**
- A decision covers a gap by kind plus a path prefix (`bhcore.py:3328-3342`).
- One answer silences every later gap of that kind under that path. Probe: one decision moved two different items' "no targets" gaps to `re_asked`.
- Check-gap ids ignore evidence (`bhcore.py:2100`), so equal ids collide.
- (Gaps subagent; spot-checked.)

**M8. Findings are not verified like gaps, and the rank trusts claimed impact.**
- `add_findings` skips `_bad_evidence` (`bhcore.py:2955-2994`). This affects review and missing-context findings (`bhorch.py:925,1065`).
- `_finding_gap` overwrites `source` (`bhcore.py:2944`).
- `rank_key` counts unverified `impact` strings (`bhcore.py:2859-2873`): 4 invented ids outrank a reproduced finding.
- `bh-gaps --write` defaults `--source review`, which clears every review gap and moves `reviewed_head` (`bin/bh-gaps:34`, `bhcore.py:2679`).
- A re-review replaces every `review` gap with what the reviewer returns (`bhcore.py:2638-2640`). A gap the reviewer leaves out, through truncation or a lapse, closes without any check.
- Fix:
  - run `_bad_evidence` on findings;
  - count only impact ids that resolve to an item;
  - require `--source` whenever `--write` is given;
  - close a gap only when the reviewer returns it marked closed.
- (Gaps subagent; the coverage and default-source points spot-checked.)

**M9. Value order is skewed by missing estimates.** (Gaps subagent; not re-read by me.)
- An item without `est_loc` costs 1 (`bhcore.py:3238,3265`), so an unestimated feature looks very cheap and jumps the queue.
- Such features should be listed as unvalued.

**M10. The work-packet cap is reported, never enforced, and the gaps job is unbounded.**
- The packet's `sizing.packet_tokens` (1600) is only reported (`bhcore.py:3656-3686`): text is never cut, and dependency contracts go in whole.
- The gaps job's input is not bounded either. The job is told to give "one verdict per rule of the base catalog and of the project overlay" (`agents/harness-gaps-reader.md:22`).
  - The catalog is 205 KB. At bytes/4 that is about 51k tokens, an upper-bound estimate: the method loads only in-scope domains. Every project document comes on top.
  - The default job cap is $2 (`bhorch.py:87`).
  - A cap overrun is a failed job that is not cached (`bhorch.py:446-452`), so it is retried and paid again every run.
- No recorded paid run has measured any job: `README:96` says "a paid toy run still has to prove…"; `findings.json` H-1 is open; `lean-plan.md:13` defines done as a toy full run.
- Fix:
  - one cheap paid toy run that records each job's tokens;
  - scope the gaps job to the domains the documents touch (the compliance-review method already scopes);
  - enforce the packet cap.

**M11. `bh run` is a long process, and nothing tells the main session to run it in the background.**
- `SKILL.md:11` says only "Run `bh run`". The host's Bash tool stops at 10 minutes, while one builder may take 30 minutes (`bhorch.py:88`) and a run has rounds.
- There is no run lock. A second `bh run` force-removes the first run's live worktrees (`bhorch.py:713-715`).
- `README:171-173` still describes the workflow era ("an agent's shell limit").
- Fix: the skill says `run_in_background` and wait for completion; `bh run` takes a `flock` on `measure_out`.
- Effort S.

**M12. One `env_setup` failure blocks an item until the owner edits it.**
- Any `env_setup` error in the item's latest record produces a gap that `blocks` the item (`bhcore.py:2418-2436`, `:1665-1668`). That record can be a candidate's, caused by the ref or by a one-off failure.
- `blocked` is not in `READY_FROM` (`:1596`), so the item is never re-measured or rebuilt until its target digest changes.
- A measured fact acts as a gate. Fix: record it as a fact and keep the item ready. (Measurer subagent; spot-checked.)

**M13. Merge failures are misattributed, and the merge is not atomic.**
- Any `git merge` refusal is recorded as the item's `conflict` (`bhcore.py:1367-1370`), for example an untracked or dirty file in the owner's checkout. The dirty check at `:1342` covers harness files only.
  - So a met candidate is rebuilt into the same refusal, round after round.
- The merge commits the ref's edits to guarded paths, and a second commit reverts them (`:1357-1366`, `:1380-1402`). If the process dies between the two, HEAD keeps the ref's test edits, and `overlay_plan` then treats them as the plan.
- Fix:
  - refuse up front, as an order refusal, when `git status --porcelain` is non-empty, saying "commit or stash, then merge";
  - merge with `--no-commit`, restore the guarded paths, then make one commit.
- The first point was reproduced by the measurer subagent, and I re-ran its script. The met candidate became `conflict` with "(merge refused: local changes or unrelated history)", while the user's untracked file was kept.

**M14. Most measurer facts reach no one.**
- `flaky`, `noise`/`within_noise`, `dependencies`, `scope` and `ignored_edits` go only into `scoreboard.json` (`bhcore.py:588-598,817-819,951-1066,1225-1246`).
- Builder feedback (`bhorch.py:723-736`), `state.last` (`bhcore.py:1678-1687`), the gap checks and the skill read none of them. So SG-05 and SG-06 do not stop a rebuild loop, despite claims in `safeguards.json` (SG-05 "shown in the report"; SG-06 "within-noise").
- The dependency fact is also wrong (measurer subagent; not re-read by me):
  - `_lock_versions` keeps one version per name (`bhcore.py:1485,1497`), so the AntD 5+6 case SG-09 was written for is caught only by sort order;
  - any `.lock` file is parsed as TOML (`:1491`), so Pipfile.lock and composer.lock silently yield nothing;
  - the 8 formats are a hand-kept list (`:1466-1502`).
- Fix:
  - send `flaky` and `within_noise` into the feedback and the stuck reason, or delete them;
  - replace the lockfile readers with an SBOM diff (syft or osv-scanner, after vet-oss), or delete the fact.
- Effort M.

### Minor (practical value only)

- m1. `bhorch.py:903`: `asyncio.gather` without `return_exceptions`. One builder's git failure, for example `worktree add` (`:717`), aborts the run with no result file and no stuck report.
- m2. `bhorch.py:1143-1147`: the budget is checked only between rounds. A round of N parallel builders can overshoot `run_usd` by up to N × `job_usd`.
- m3. `bhorch.py:627-634`: the gaps and plan job keys hold the skill path, not the catalog or skill content. After a plugin update, a cached review of the old catalog is reused.
- m4. `tests/test_no_waiting.py:12-20`: a hand-kept regex ban list that duplicates the plugin's own ast-grep check `checks/base/RL-08.python.yml`. Run that check over `harness/` instead.
- m5. `harness/docs/findings.json` is a hand-kept issue list beside the tracker the harness supports. File these as issues.
- m6. (Tracker subagent, not re-read.) Tracker edge cases (`bhtracker.py:324-330,357-366,420-423`): `list` filters by type after the limit; one bad claim aborts the whole admission; `room` is read before the lock.
- m7. (Dead functions confirmed by my caller scan; the rest is from the gaps subagent.) Gaps/rank leftovers: `_write_gaps_doc` and `_committed_finding_ids` have no callers (`bhcore.py:2894-2918`); plain `write_text` bypasses the atomic write (`bhcore.py:2690,2981,2986`); the review diff is cut mid-hunk (`:3041`).
- m8. `bin/bh-init:42-43,62-71` writes placeholders into a config that validates but cannot run. It infers nothing.
- m9. (Measurer subagent, not re-read.) `bhcore.py:346-359`: CSV `min`, `max` and `median` drop NaN or inf samples silently. `min` over [1000, nan, 900] gives 900, though README:113 says non-finite values fail closed.
- m10. (Measurer subagent, not re-read.) A new holdout case does not make met items stale: the `_facts` pathspec leaves the holdout out (`bhcore.py:1599-1615`) while `tree_key` includes it (`:1101`).
- m11. (Measurer subagent, not re-read.) `bhcore.py:394`: `communicate()` waits for EOF, so a test that leaves a background child holding stdout is recorded as a timeout.
- m12. `README:171-173` says "up to three commands" per measurement, but a bench runs `runs` times (`bhcore.py:525-532`). The sentence is also from the workflow era ("an agent's shell limit").

- m13. `tree_key` leaves out plan files and held-out cases, and no test notices: with either removed, the suite stays green (`bhcore.py:1100-1101`; mutation subagent). Today the only reader is the `flaky` fact, which nothing reads (M14).

Discarded theoretical minors: **27**. By reviewer:
- me, 8: a write through `git diff --output` in the review job; a cached harvest apply reported as not ok; a worktree left behind on a `set_branch` error; a corrupt job-cache file; orphaned children on cancellation; `merge --abort` with unrelated local edits; an "already in HEAD" retry corner; a deadline kill that reaches only the direct child;
- measurer subagent, 10;
- tracker/rules subagent, 4;
- gaps subagent, about 5.

## 3. Owner rules, one line each

| Rule | Held? | Evidence |
|---|---|---|
| No pass/fail gates | **Broken** in 5 places | See the refusal table below |
| No agent in the mechanical path | **Held in 1.5.2** | `bhorch.py` runs state, measure, merge, commit, gaps merge and tracker itself; an agent starts only for gaps, plan, build, harvest and review (`bhorch.py:77-84`). The checkout's workflows broke this ("a cheap agent runs each tool", checkout README:47-48) |
| Host or OSS first | **Broken** | The stdlib-only rule (M6): validator, link checker, JSON-path mapper, frontmatter reader, downloader, renderer, the eight lockfile readers (M14). Host features: the jobs use `claude -p` well, but no sandbox (K1) and no `run_in_background` (M11) |
| Self-sustained, no project scaffolding | **Broken** | `bh-init` writes placeholders the project must fill (`SKILL.md:10`, `bin/bh-init`). The toy needs 9 hand-filled config groups, `na` with 9 reasons among them. The test command, ecosystems, lockfiles and protected paths could be inferred |
| No hand-maintained pattern lists | **Broken** | `bhrules.py:41-67,99-135` (M5, K4); `GAP_KINDS` duplicated in `bhcore.py:1954-1974` and `gaps.schema.json:87-108`; `AUTH_RE` (`bhorch.py:90-93`); lockfile formats (`bhcore.py:1466-1502`, M14); `test_no_waiting` BANNED |
| Token cost measured | **Partly** | Per-job tokens and cost are recorded from the CLI result (`bhorch.py:238-245,462-473`), but the release holds no record of a paid run (M10). Measured on the toy, at bytes/4. What the orchestrator itself hands each job is small: an agent body of 1.0-3.6 KB (250-900 tokens), an output schema of 0.1-1.4 KB, an input file of 0.4-3.2 KB, and a packet of 1.0-1.3 KB. That totals 2.3k tokens or less per job, before the host's own system prompt and whatever the agent reads by itself. The main session loads SKILL.md (2.7 KB) and the printed summary, which is capped (`bhorch.py:1297-1325`); README.md (28 KB, about 7k tokens) is named as "the reference" (`SKILL.md:6`). Unbounded: the gaps job, told to give a verdict on every rule of the base catalog (332 by the 1.5.0 commit message; 385 rule rows in `catalog/` with packs) (catalog 205 KB; at most about 51k tokens, estimated as bytes/4) |
| Refusal only for order, with a teaching message | **Mostly** | `set_branch` refusals name the right way (`bhcore.py:849-861`). `merge_unmerged` "commit the plan files first (bh-commit)" names it (`:1344`). The ast-grep and Beads errors do not teach the fix |

### Refusals, classified

**Gate: refuses on content or environment.** This breaches the owner's rule.

| Where | What it refuses | Teaches the fix? |
|---|---|---|
| `bhcore.py:1182-1186` | a target moved vs HEAD (M1) | no: only "the owner commits that" |
| `bhcore.py:2418-2436`, `:1665-1668` | the item after one `env_setup` error: blocked (M12) | no |
| `bhrules.py:227-240` | the item when ast-grep has no asset for the platform, or the download or sha fails: unmet forever (K2) | no |
| `bhtracker.py:248-269` | the tracker when `bd`'s sha does not match the pin: unreachable | no |
| `bhcore.py:1311,1324` | the merge when the catalogue fails its schema: forces a rebuild | no |

**Order, with a teaching message.** These are fine.

| Where | Message |
|---|---|
| `bhcore.py:886` | restore the scoreboard from git |
| `bhcore.py:1181`, `:1341` | finish or abort the merge |
| `bhcore.py:1344` | commit the plan files first. It dead-ends behind the gate (M1) |
| `bhcore.py:858-861` | a retry must start from the previous commit |
| `bhcore.py:2624` | the source 'check' is reserved |
| `bhcore.py:3454` | the gap is not in the report |

**Order, without a teaching message.** Each needs one line naming the next step.
- `bhcore.py:841,903,1114,1338` and `bhorch.py:272`: not a git repository.
- `bhorch.py:278`: the claude CLI is not on PATH.
- `bhcore.py:844,883`: unknown item.
- `bhcore.py:848`: not a commit.
- `bhcore.py:850`: already in HEAD.
- `bhcore.py:1267`: unreadable scoreboard, with no hint, unlike `:886`.
- `bhorch.py:888`: plan files still uncommitted.

**Not refusals.**
- `bh-measure` exit 1 means measured unmet.
- `bh-state` exit 1 means problems were found.
- `merge_gaps` rejects an unresolvable citation from an agent. That is input validation, listed under `rejected` (H-2).

## 4. Fitness for the intended flow

| Stage | Piece today | Verdict |
|---|---|---|
| Work arrives from build order | planner job reads the build order (`agents/harness-planner.md:19-20`) | serves as is |
| Work arrives from issues | `bhtracker.admit` → `bricks.json` items of kind `change` | needs changes: body lost; GitHub parent and claim broken (M4) |
| Work arrives from decisions | none: decisions only silence gaps | wrong shape / missing (M3) |
| Tiers (mechanical, design-affecting, epic) | none: `kind` and sizing notes only | missing (M3) |
| Plan | `phase_plan` + planner, cached on the document digest (W2) | serves, with fixes: no tiers; the target-moved gate (M1) |
| Tests written first by a non-builder | none: no job writes tests, nobody writes the holdout ref | missing (M2) |
| Build | `build_one`: worktree per item, packet, retry merge of the previous ref | needs changes: isolation (K1); the packet cap (M10) |
| Deterministic measurer with retry | `bh-measure` + `phase_measure` + feedback + `max_rounds` + W6 no-progress stop | right shape; needs changes: a shared output folder (K6), crashes (K7), an `env_setup` gate (M12), facts that never reach the retry (M14) |
| Merge and report | `merge_unmerged`, `bh-gaps --source cycle`, the run result led by the product view | needs changes: misattributed conflicts and a two-commit merge (M13) |
| Review | `phase_review` per feature that became sellable | serves; findings unverified (M8) |

## 5. Size and dead weight

Lines are counted per file with `git show`; examples and fixtures are excluded.

| | 1.4.0 (old main `16aab49`) | 1.5.2 (`c02e524`) |
|---|---|---|
| code: lib + workflows + bin | 8,501 | **6,920** (bhcore 3,691; bhorch 1,399; bhtracker 662; bhrules 462; bin 706) |
| plus schemas, adapters, agents | 10,318 | **8,864** |
| tests | 5,447 | 5,228 |

- The earlier "about 8.8k lines" still holds as 8.9k including schemas, or 6.9k of code. The workflows went (−1,655 lines), but the orchestrator (+1,399) and its schema (+275) took their place.
- Lean-plan promises (`docs/lean-plan.md`):
  - Done: checksums, paging, `--part` and `--value`; the workflow prelude; the agent-in-path; model per job from the agent files (W4); the W6 no-progress stop; the W2/W3 document-digest cache.
  - Not done:
    - wave 2 entirely (lychee, jsonschema, junitparser or extractor, hyperfine spread, ecosystem CLIs or syft, the ast-grep package, `:24-40,80`);
    - W7, measure only what changed: no result reuse by tree key (`:57`);
    - W8, affected tests only (`:58`);
    - W13, one `bh` command: `bh` was added, but 12 `bh-*` scripts remain (`:69`);
    - W15, a generated register (`:71`);
    - Setup, install pinned tools (`:79`);
    - rule 7, done = a toy full run (`:13`).
- Code used by no workflow: 9 of the 12 `bh-*` scripts beside `bh` (bh-admit, bh-branch, bh-brief, bh-commit, bh-gaps, bh-merge, bh-rank, bh-reconcile, bh-state; 484 lines).
  - Neither `bhorch.py`, the skill nor any agent calls them. Only tests and humans do.
  - `bhorch.py` calls their Python functions directly. It uses only `bh-measure` (`bhorch.py:545`); the skill uses `bh-init` and `bh-answer`.
- Dead functions: `_write_gaps_doc` and `_committed_finding_ids` (`bhcore.py:2894-2918`).
- Duplication:
  - `GAP_KINDS` vs `gaps.schema.json`;
  - `item_key` (`bhorch.py:756-776`) restates `bhcore.tree_key` minus the result files;
  - `bhorch.git` (`:107-111`) sits beside `bhcore._git`;
  - `bhorch.fill` (`:738-741`) restates `Config.slot`, its port defaults included;
  - `measure_item:482-484` restates `bhrules.item_targets`;
  - `_waves` (`bhcore.py:1871-1885`) re-implements stdlib `graphlib.TopologicalSorter`;
  - the `scoreboard_md` key is never written.
- `merge_unmerged` builds the whole `state()`, gap checks and lockfile parsing included, only to read `unmerged` (`bhcore.py:1345`).

## 6. Tests

**Suite.** 19 files and 5,228 lines: 297 passed, 2 skipped, in 163 s. The skips are the two real-Beads tests.

**What proves behaviour.** Three groups run real code rather than checking shape:
- `test_measure.py` and `test_measurer_safeguards.py` run real commands in toy git repositories: fail-closed cases, overlay, holdout, flaky, noise, scope, environment.
- `test_bhorch.py` drives the real orchestrator against a fake `claude` binary (`tests/fake_bin/claude`): auth fallback, budget overrun, deadline, restart cache, product view.
- `test_toy.py` runs the toy end to end through the bin tools.

**Mutation results.** The mutation subagent applied single-line mutations to `bhcore.py`, `bhrules.py` and `bhorch.py`, and ran the full suite with xdist after each.
- Its result files record 42 mutations: 37 red and 5 green. Its summary says 47 and 8; the extra 3 greens are not in its files.
- 26 more were planned but not run.

| Claim | Mutated | Result |
|---|---|---|
| fail-closed paths: no targets, pending, non-zero exit, timeout, zero tests, unreadable or odd JUnit, non-finite or non-numeric or missing metric, no bench command; status ignoring errors | `bhcore.py:400-567` (13 mutations) | **red**, each by a test named for it |
| overlay of plan, protected and holdout paths; the guard set | `bhcore.py:759,798,801,803` | **red** |
| a candidate never replaces a met current; an unreadable board is never overwritten | `bhcore.py:886,940,1266,1270,1586` | **red** |
| flaky detection; oscillation threshold; bench median | `bhcore.py:1243,1099,3143,542` | **red** |
| commit refuses moved targets or a merge in progress | `bhcore.py:1179,1183` | **red**. These tests lock in the M1 gate |
| `rules.violations` count; value order by slice; citation line and quote checks | `bhrules.py:315`, `bhcore.py:3245,2477,2480` | **red**. Both citation checks hang on one test |
| run budget; restart reuse; job output schema check | `bhorch.py:1098,1144,421,531` | **red** |
| **only met candidates are merged** | `bhcore.py:1673` | **GREEN** (K8; I re-verified it with a full serial run) |
| flaky key covers plan files and held-out cases | `bhcore.py:1100,1101` | **GREEN** (m13) |
| the error text for a bench result or a pending bench | `bhcore.py:522,538` | GREEN; the status still fails closed through "metric not measured" |

Not run:
- the merge abort and conflict recording, the catalogue union, and `_restore_guarded`;
- the job key's content (k5, k7);
- `max_rounds`;
- the `rules.violations` target itself and the scope inputs.

**Verdict on the tests.** The measurer's fail-closed core, the overlay, the scoreboard rules and the orchestrator's budget and restart are proved by behaviour. The merge path and the register are not.

**Vacuous or shape-only tests**
- `test_safeguards.py`, all 3 tests: the register's names-only check (K3). **Critical**, because it backs every SG claim.
- `test_no_waiting.py`: a regex grep over source text with a hand-kept ban list (m4). It duplicates the plugin's own RL-08 ast-grep check, and it misses a loop on `time.monotonic()`.
- `test_no_project_terms.py`: a text grep. It is skipped without a deny-list file, though it runs on this host.
- `test_config.py:23,45`: fixtures accepted or rejected by the schemas. Those fixtures cannot reveal the validator ignoring keywords (M6).
- `test_checks.py:86`: asserts that constants are equal.
- `test_bhorch.py`:
  - `test_the_workflow_path_is_gone` checks files are absent;
  - `test_claude_is_started_in_one_place_only` counts a substring (`:479-481`);
  - `test_every_agent_file_allows_the_structured_output_tool` checks shape.
  - These are harmless as lint, but they prove no behaviour.

**Tests that lock in a gate as intended behaviour.** These must change together with M12 and M1.
- `test_toy.py:357`, `test_failing_env_setup_blocks_the_item`.
- `test_toy.py:426`, `test_commit_refuses_moved_targets_and_a_merge_in_progress`.

**What no test covers**
- The default rule-check path. The toy fixture points at an empty catalog (`test_toy.py:44-54`), and rule tests use a fake checker. No test runs the plugin's own catalog with the real ast-grep, which is how every project runs (K2, K4).
- The real host CLI. The README says so (`README:96`), and `findings.json` H-1 is open.
- The builder bypasses (K1).
- The shared output folder (K6), and both crash paths (K7).
- The platform gate (K2).
- A run with `protected` empty (K5).
- Two concurrent `bh run` processes (M11).

## 7. Verdict per component

Effort: S is under a day, M is 1-3 days, L is more.

| Component | Verdict | Reason | Effort |
|---|---|---|---|
| `workflows/*.js`, `lib/prelude.js` (checkout, user-scope 1.4.0) | **delete**: done upstream | they put an agent in the mechanical path; replaced by `bhorch.py` in 1.5.2. Update the checkout and the user-scope install | S |
| `lib/bhorch.py` orchestrator | **fix** | right shape: a program, `claude -p` jobs, document-digest cache, W6 stop, cost per job. Needs: builder isolation (K1), a run lock and background run (M11), a tests-first job and tiers (M2, M3), error handling (m1) | M |
| `bin/bh` | **keep** | the one entry point | S |
| `agents/harness-*.md` | **fix** | builder has bare `Bash` plus the plugin root (K1); gaps reader asked for a verdict on every rule (M10); add a test-writer agent (M2) | S |
| `measure_item`, `measure`, `overlay_plan`, `bh-measure` | **fix** | the overlay with `git checkout <rev> -- paths` is the right tool. Shared output folder (K6), crashes (K7), `protected` empty by default (K5), NaN in CSV (m9) | S |
| `merge_unmerged`, `_restore_guarded` | **fix** | misattributed conflicts; a two-commit merge window (M13); the met-only guard is untested for a met item (K8); builds the full `state()` just to list what is unmerged | M |
| `set_branch` | **keep** | `update-ref` with the old value is an atomic compare-and-swap; add the next-step text to its refusals | S |
| `commit_harness` | **fix** | the content gate on targets stalls every build (M1); commands are not guarded | S |
| `state()` | **fix** | `env_setup` gate (M12); 9 s at 1,000 items (H-4); called repeatedly per round | M |
| flaky (`tree_key`), noise, dependency and scope facts | **fix or delete** | nothing reads them (M14); replace the lockfile readers with an SBOM diff after vet-oss | M |
| history and `oscillating` | **keep** | feeds the stuck reasons | S |
| `validate()` (own JSON Schema subset) | **replace**: jsonschema | silently ignores keywords (M6) | S |
| `bhrules.py` checks | **fix** | vacuous and gameable target (K4); hand-kept stack lists (M5) | M |
| `checkers.json` + downloader (`ensure`) | **replace**: ast-grep from PATH, `uvx` or npm | gate by platform (K2) | S |
| `bhtracker.py` + adapters | **fix** | body lost; GitHub parent and claim; reopens human closes (M4); `jq` path mapper (M6); sha pin is a gate | M |
| gap checks (`check_gaps`) | **fix** | id collisions (M7); link checker → lychee (M6) | M |
| `gaps.md` renderer | **replace**: a template, or delete | 135 hand-built lines; a pipe character in a summary breaks its tables (M6) | S |
| rank and review input | **fix** | findings unverified; claimed impact trusted; omission closes gaps (M8) | S |
| value order (`value_queue`) | **keep**, fix one thing | missing `est_loc` counts as 1 (M9) | S |
| learning and `bh-answer` | **fix** | coverage by kind and path prefix hides new questions (M7) | M |
| work packet and `bh-brief` | **fix** | cap not enforced; no test files in the packet (M10, M2) | M |
| `schema/*.json` | **keep**, fix `bricks` | add `tests` and `tier`; deduplicate the `GAP_KINDS` enum | S |
| `bh-init` | **replace**: inference inside `bh run` | placeholders the project must fill; nothing inferred (lean-plan step "onboarding inside the run") | M |
| 9 manual `bh-*` CLIs (admit, branch, brief, commit, gaps, merge, rank, reconcile, state) | **delete** | no workflow calls them (484 lines); the orchestrator uses the functions; W13 promised one `bh` | S |
| `bh-answer` | **keep** | the main session records the owner's answers with it | S |
| `safeguards.json` + `test_safeguards.py` | **fix** | vacuous (K3); generate it from pytest markers and JUnit results (W15) | S |
| `docs/findings.json` | **replace**: tracker issues | a hand-kept issue list | S |
| `docs/decisions/0001-work-tracking.md` | **fix** | caller list is stale (`bh-admit`, `bh-gaps`, `bh-reconcile`; the orchestrator now calls the functions); its evidence lives in another project (line 3), so the plugin is not self-contained | S |
| `schema/jobs.schema.json` | **keep** | one output schema per job, inlined for `--json-schema`, checked again on return (mutation k6 red) | S |
| rest of the test suite (`test_measure`, `test_measurer_safeguards`, `test_toy`, `test_bhorch`, `test_rank`, `test_rules`, `test_tracker`, `test_value_order`, `test_learning_packet`, `test_work_tracking`) | **keep**, fix gaps | behavioural; 37 of 42 recorded mutations red. Add tests for K8, K6, K7, K2 and the real catalog path; change the two that lock in gates (M1, M12) | M |
| `test_no_waiting.py`, `test_no_project_terms.py` | **replace**: run the plugin's RL-08 ast-grep check over `harness/`; keep the project-terms grep as a lint | regex greps with hand-kept lists | S |
| `docs/lean-plan.md`, README | **fix** | wave 2, W7, W8, W13 and W15 not done; workflow-era text (README:171-173); the "every scoring bypass" claim is false | S |
