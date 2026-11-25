# agent-compliance: critical review of skills, catalog, checks, templates and evals

Read-only review, 2026-11-25. Every path below is relative to `~/workspace/agent-compliance` unless it is absolute.

**What was reviewed.** The working tree is branch `harness-lean` at `1566a95` (v1.5.0). The installed plugin is 1.5.2 (`~/.claude/plugins/cache/agent-compliance/agent-compliance/1.5.2`). A `diff -rq` of the two shows that five skills, all templates, all checks and all evals are identical (local `evals/results/` aside). They differ in five places:
- `skills/harness/SKILL.md`: 1,082 words in the tree, 447 in 1.5.2;
- LC-41 wording;
- the NO domain added to scenarios 66 and 67;
- the README's version pin and harness paragraph;
- the version strings.

Findings on the harness skill cover both versions and cite the version they come from. `harness/` and `bin/` were left to the other reviewer.

**Method.** I read all six SKILL.md files, the five templates, the README, both manifests, `catalog/index.md` and the six check rules with their tests in full. I sampled rules across all 16 base domains and five packs, then:
- counted provenance and row length with a script;
- probed ruff 0.16.1 on the RL-08, ID-15 and HO-02 cases;
- read the eval design and graders, and parsed every local eval result.

ast-grep is not installed on this machine, so the check tests were **not run**.

---

## Verdict

The deterministic parts are worth keeping:
- the harness idea of a measurer that alone decides;
- the literal-follower plan dry run;
- trigger evals graded on tool use.

The LLM-judged parts are not worth keeping as they stand:
- They are not shown to converge. On the same artifact and catalog, Opus, Haiku and Sonnet returned three different verdict sets. Their ground truth was re-labelled twice in 11 minutes while the rules under test were being reworded.
- They grade their own work.
- They emit PASS/FAIL readings, which act as gates.
- Their tie-break favours keeping your own code over OSS.
- They cost 10k to 42k tokens before reading any evidence.

The catalog is sold as "industry-standard" (`README.md:3`), but 58% of its rows cite only "Convention:". It was split out of one earlier project, so many rows impose that project's architecture.

Recommendations:
- Delete `compliance-review` and `compliance-catalog`.
- Replace `vet-oss` and the checks with maintained OSS.
- Slim `vetted-decision` and `bug-analysis`.
- Keep the harness skill, fixed.
- Rebuild the evals around outcomes and measured cost.

---

## Findings

### F1. Critical: the claim that "reviews converge" is unsupported, and the evidence points the other way

- **The claim.** "a compliance review converges because the set of BROKEN rules only shrinks" (`skills/compliance-review/SKILL.md:8`; `README.md:7`).
- **What the plugin's own eval results show.** These are local, git-ignored files in `evals/results/`. Each run's `suite.modelOverride` and grader names were read from its `aggregate-result.json`.
  - **Verdicts depend on the model.** The three runs at `2026-11-18T10-00-42Z` used the same tree, the same artifact (`reports-db`) and the same truth:
    - Opus failed `DS-08-broken` and `DS-08-location`;
    - Haiku failed `DS-07-held` and `ID-09-na`;
    - Sonnet passed.

    The review is meant to run on Sonnet (`compliance-review/SKILL.md:26`). But the inline path, and vetted-decision, vet-oss and bug-analysis, run on whatever model the session uses. So which rules count as BROKEN depends on who runs the review.
  - **The ground truth moved while the rules under test were edited.**
    - At 09:58Z the grader expected DS-08 HELD (`DS-08-held`); at 10:00Z it expected BROKEN.
    - At 10:00Z it expected DS-07 HELD (`DS-07-held`); at 10:08Z it expected BROKEN.
    - In between came commit `3b40008` (evals, 10:05:32Z) and commit `21532e8` (10:07:27Z, "rows small models misread are made decisive (DS-07, DS-08, …)").
    - After both, Sonnet missed `DS-07-broken` in both runs (`2026-11-18T10-08-57-252Z`), and no accuracy run is recorded since.
  - **Repeat runs agreed.** In every directory, the two runs on one model gave the same verdicts. So run-to-run stability on one model is not disproved; it is simply not measured beyond n=2.
- **The cache does not fix it.** The key cache (`compliance-review/SKILL.md:22`) only avoids re-running a verdict. Any key change (an artifact edit, a catalog bump, or a re-review in another session) re-judges the rules.
- **Candidate mechanisms for the loops the owner saw.** The pilot project observed 31 doc conflicts and reopened issues. These generators inside the "fixed" review could produce them; this is inferred, not traced:
  - "Possible missing rules" and the waste question on every review (`compliance-review/SKILL.md:31-32`) feed back into rebuilding the catalog (`compliance-catalog/SKILL.md:3`).
  - Catalog drift re-runs every changed id (`compliance-review/SKILL.md:18,23`). The catalog went from 1.0.0 to 1.5.0 between 11-18 and 11-21 (`git log -- catalog/index.md`), and 1.5.2 is installed.
  - The weakness audit has no round limit and repeats until it rates the catalog ADEQUATE (`compliance-catalog/SKILL.md:27`; `templates/catalog-audit.md:10-17`).
  - PR-09 requires every confirmed review finding to be filed in the same turn (`catalog/base/PR.md:15`).
- **Fix.** Delete `compliance-review` and `compliance-catalog` (see F13 for the dependencies to move first). Let only measured targets move work on.

### F2. Critical: skills grade their own work, against the owner's rule and the catalog's own PR-04

- **compliance-review.** With fewer than about 100 rules in scope, the review runs "inline with no reviewer subagent" (`compliance-review/SKILL.md:26`). This is usually the session that wrote the artifact. PR-04 requires "a reviewer who did not write the artifact and shares no context with its author" (`catalog/base/PR.md:10`).
- **vetted-decision.** One agent lists the options, judges them, "attacks the leading option" and then recommends (`skills/vetted-decision/SKILL.md:24-29`). It is the main decision path in the pilot project, whose rules file requires it.
- **vet-oss.** One agent finds the candidates and judges them (`skills/vet-oss/SKILL.md:21-28`).
- **Accuracy evals.** The catalog author also wrote the ground truth (`evals/accuracy/truth.json`). The DS-07 and DS-08 truth was re-labelled alongside rewording those same rows (F1), so a pass shows only that the plugin agrees with itself.
- **Harness (tree).** Every item gets `tests.passed >= 1`, and the builder adds its own unit tests (`skills/harness/SKILL.md:25,38`). With no protected acceptance tests, the builder's own tests satisfy the target. Exactly what the measurer counts is for the harness reviewer to confirm.
- **Fix.** A fresh agent that did not propose the work does the judging, or a deterministic measurer does. The proposer never grades its own work.

### F3. Major: LLM pass/fail readings act as gates, and catalog rows tell projects to build gates

- **The plugin's own outputs work as opinion gates:**
  - `Verdict: PASS | FAIL` (`compliance-review/SKILL.md:45`; `README.md:68`), even though it says it "never gates a commit" (`:33`);
  - "ready when the audit rates it ADEQUATE" (`compliance-catalog/SKILL.md:27`);
  - a candidate is presented "only when no row is BROKEN or UNVERIFIED" (`vet-oss/SKILL.md:28`);
  - "One option with no BROKEN and no UNVERIFIED rule" (`vetted-decision/SKILL.md:29`);
  - "Each guess is a BROKEN plan-format rule" (`templates/plan-dry-run.md:15`).

  None of these is a measured target. Each is a model's opinion with a pass/fail outcome.
- **Catalog rows require gates in projects:**
  - PN-03 "An unproven claim is a gate step" (`catalog/base/PN.md:9`);
  - PN-13 "each [task] … a real-flow gate" (`PN.md:19`);
  - DC-11 "a named blocked gate" (`DC.md:17`);
  - PR-07 "A gate's refusal … never a bypass" (`PR.md:13`);
  - the Gate term (`catalog/index.md:45`).

  A plan that follows the owner's no-gates rule is BROKEN under PN-13. The review then reports, as findings, rules the owner has already rejected.
- **Fix.**
  - Report counts as measurements, for example "dry run: 3 guesses", with no pass/fail label.
  - Rewrite PN-03, PN-13, DC-11 and PR-07 as measured targets plus refusals for order only, each refusal with a teaching message.

### F4. Major: under uncertainty, the tie-break keeps your own code, against host/OSS first

- **vetted-decision.** Option O1 "keep the current design" is always present and always has `path:line` evidence (`vetted-decision/SKILL.md:24`). A runtime rule supported only by documentation is UNVERIFIED, never HELD (`:26`). A falsifying call that cannot run yet makes the recommendation UNVERIFIED (`:28`). Only an option with no UNVERIFIED rule qualifies (`:29`). So an option not yet built cannot beat the code that exists.
- **vet-oss.** A product-class tool must clear 186 rules (NO, SC, ID, LC, RL, OB, DS and PF at minimum; `vet-oss/SKILL.md:12`) with no UNVERIFIED row. Otherwise the answer is "no OSS meets the rules … keep the current owner" (`:28`). Toolchain tools are judged only on five criteria (`:21`).
- **Contradiction between skills.** The harness builder adopts a helper library on its own, recording only job, ecosystem, library and why (`skills/harness/SKILL.md:37`, tree). vet-oss says to load "before any search when about to suggest … a library" (`vet-oss/SKILL.md:3`). The same act gets opposite instructions depending on which skill is loaded.
- **Fix.**
  - Judge an unbuilt option on its falsifying call, and turn that call into a harness target.
  - Get adoption facts from a deterministic scorer (see the vet-oss row in the final table).

### F5. Major: token cost, and descriptions that load the skills when they are not needed

Six descriptions, 463 words, sit in every session's skill listing. Each body pulls in further files.

| Skill | Mandated minimum load: words / tokens (bytes/4, the skill's own estimate) | What the load includes | Measured on toy evals, with plugin vs without |
|---|---|---|---|
| vetted-decision | 7,560 words / about 11.1k tokens; 12,694 words / about 18.8k tokens once LC and DS are in scope (any session, token or cleanup) | the skill; compliance-review's "Inputs" (`:12-13` pulls in the whole 1,408-word skill); `index.md`; DC/PN/PR (`compliance-review/SKILL.md:24`, `index.md:10`) | `decision-reused`: 10.3 vs 7.0 turns, $0.075 vs $0.049 |
| vet-oss | 18,559 words / about 27.3k tokens for a product-class tool at every tier | the skill, compliance-review, the index and the eight mandatory domains (`vet-oss/SKILL.md:12`). The skill says "adopted, about 3 tool calls" (`:17`), but the index plus eight domain files alone take 9 reads | `oss-judged-by-rule-ids`: 18.3 vs 8.0 turns, $0.191 vs $0.052 |
| bug-analysis | 6,605 words / about 9.6k tokens with one domain; 11,739 words / about 17.3k with a termination (`bug-analysis/SKILL.md:21`) | the skill, compliance-review, the index, the bug-record template and the touched domains | `bug-record-rule-lines`: 9.7 vs 3.2 turns, $0.101 vs $0.033 |
| compliance-review | 6,630 words / about 9.6k tokens minimum; 28,017 words / about 41.6k for the full base without packs | the skill, the index, DC/PN/PR; the full case adds all 16 domains and the reviewer brief | `full-review`: 15.1 vs 4.0 turns, $0.218 vs $0.046 |
| compliance-catalog | 28,699 words / about 42.4k tokens, plus the project's sources | the whole base, so it can "skip it" (`compliance-catalog/SKILL.md:22`), plus the index, scenarios, audit and bindings templates | none |
| harness | 1,082 words / 1.7k tokens (tree); 447 words / about 0.6k (1.5.2) | the skill alone | none |

Caveats on the measured column:
- The figures are means pooled across that day's result directories.
- The without-plugin arm did less work: it wrote no rule rows, so it is a floor, not a like-for-like baseline.
- In `decision-reused`, the without-plugin arm also passed 3/3, at lower cost.

Some descriptions fire in the normal build flow:
- **bug-analysis**: "Load before any investigation when … failing test … and before any commit whose subject type is `fix`" (`bug-analysis/SKILL.md:3`). In the intended flow, the builder's job is to make failing acceptance tests pass, so this description fires on the normal red-to-green path. No no-trigger eval covers that case (`evals/no-trigger/*` covers only commit-message, explain-function, fix-typo, pr-bug-review, rename-variable, run-test and standards-question).
- **vetted-decision**: "any option list for the project owner" (`vetted-decision/SKILL.md:3`).
- **vet-oss**: "before any search when about to suggest … library" (`vet-oss/SKILL.md:3`).

**Fix.** Narrow each description to its single trigger, and drop the cross-skill "as compliance-review Inputs" load.

### F6. Major: skills restate the newest catalog rules, giving each rule two homes

- **Where the termination block appears.** The LC-39 to LC-43 block ("tier, number, mechanism, child-first, rule ids in the code comment") is restated in:
  - `compliance-review/SKILL.md:24,29`;
  - `vetted-decision/SKILL.md:25,27`;
  - `bug-analysis/SKILL.md:21,36`;
  - `templates/review-brief.md:16`.
- **What it contradicts:**
  - "the catalog row is the whole rule" (`compliance-review/SKILL.md:26`);
  - "The rules come from the catalog, never from sources this skill picks" (`vetted-decision/SKILL.md:8`);
  - the catalog's own DC-02 (`catalog/base/DC.md:8`).
- **It has already drifted.** 1.5.2 changed LC-41 and added NO to scenarios 66 and 67. None of the four restating files changed.
- **No eval tests it.** No eval mentions LC-39 to LC-43 or "termination" (0 files under `evals/`, results excluded).
- **Fix.** State the rule once.

### F7. Major: the catalog is one project's conventions presented as industry standards, and it leaks that project's architecture into every user

- **Provenance counts** (script over `catalog/base/*.md`, 332 rows):
  - 192 rows cite only "Convention:";
  - 25 mix an external source with a convention;
  - 115 cite an external source only.

  `README.md:3` and `.claude-plugin/plugin.json:4` call the catalog "industry-standard rules".
- **Origin.** Commit `fc86516`: "Base catalog split out of the Scholemy catalog".
- **Rows that impose that project's architecture:**
  - LC-01: every resource names a level from L0 to L6 (`LC.md:29`).
  - SC-01: "the one designated build-and-release host (the release node)" (`SC.md:7`). It cites Twelve-Factor V, which asks only that build, release and run be kept separate.
  - HS-01: "a webhook is never the hand-off", with a circuit breaker per consumer (`HS.md:7`).
  - LC-43: rule ids of this plugin go in a code comment at every acquisition and termination site (`LC.md:71`). Product code becomes coupled to the plugin's id scheme.
- **Rows are hard to judge from the row alone.** The plugin says "a catalog row is written to be judged by [Sonnet]" (`compliance-review/SKILL.md:26`). The median row is 36 words, but ID-15 is 248, HO-40 172, NO-28 155 and CI-14 152.
- **Fix.**
  - For the 140 rows with an external source, point to the maintained standard itself:
    - OWASP ASVS and NIST SP 800-53 for ID;
    - SLSA and OpenSSF Scorecard for SC;
    - the AWS Well-Architected Framework (reliability, operational excellence, performance) for RL, OB and PF;
    - Enterprise Integration Patterns for HO and HS.
  - The 192 convention rows are house rules. Keep only those the owner endorses, and make each one a lint configuration or a measured target.

### F8. Major: the checks are hand-maintained patterns, stricter than their rules on one side and easy to evade on the other

The misses and false positives below come from reading the patterns; the ast-grep tests were not run.

- **HO-02 is stricter than its rule.** The check flags every `publish`, `produce` or `send` outside the outbox modules (`checks/base/HO-02.python.yml:13-22`). Rule HO-02 also allows change-data capture and "a step that publishes the outcome of an effect it just committed" (`catalog/base/HO.md:8`). Those legitimate forms are flagged as false positives.
- **Receivers are matched by name.** The check finds the client by a regex on its variable name: `nc`, `js`, `producer$` and similar (`HO-02.python.yml:21-22`). `self.bus.publish(...)` and `client.publish(...)` are missed.
- **ID-15 needs the receiver to be literally `jwt`** (`checks/base/ID-15.python.yml:16-21`). `from jwt import decode; decode(...)` and `import jwt as pyjwt` both escape.
- **The checks gate in practice.** `checks/README.md:3` says a check "never replaces the rule's review". The harness nevertheless counts violations as unmet until zero (`harness/safeguards.json:249`, flagged for the harness reviewer). These pattern rules therefore act as a gate.

Which maintained linter already covers each check. Classes:
- **(a)** a maintained rule covers it out of the box;
- **(b)** a maintained engine covers it with a list the project writes, which is still a hand-maintained list, only moved;
- **(c)** nothing covers it.

| Check, ecosystem | What it flags | Maintained equivalent | Class | Basis |
|---|---|---|---|---|
| RL-08 python: async sleep in a `while` loop | `await asyncio.sleep` or `trio.sleep` in `while` | ruff **ASYNC110** async-busy-wait. It flagged cases 2 and 4 | (a) | run here |
| RL-08 python: sync `time.sleep` or bare `sleep` in a `while` or `for` loop | cases 1 and 3 | ruff ASYNC110 did **not** flag them. semgrep registry `python.lang.best-practice.sleep.arbitrary-sleep` flags any literal `time.sleep`, which is broader. ruff **TID251** with a `time.sleep` ban flagged it | (a) via semgrep (broader); (b) via TID251 | semgrep: rule source read via `gh api`; TID251: run here |
| RL-08 python: `poll*interval` names | naming heuristic | none | (c) | n/a |
| RL-08 typescript: `setInterval`, `window.setInterval` | | ESLint core `no-restricted-globals` / `no-restricted-properties` (oxlint has `no_restricted_globals`) | (b) | upstream rule source confirmed via `gh api`; not run |
| RL-08 typescript: `await sleep` or a `setTimeout` promise in a loop | | ESLint core **`no-await-in-loop`** (also oxlint `no_await_in_loop`). It flags any `await` in a loop, which is broader | (a) | upstream rule source confirmed via `gh api`; not run |
| RL-08 typescript: `pollInterval` names | | none | (c) | n/a |
| HO-02 python and typescript: broker publish outside the outbox | | ruff TID251 module ban plus `per-file-ignores`, import-linter (Python), ESLint `no-restricted-imports` with overrides, dependency-cruiser (TS). These restrict which modules may *import* the client, a coarser property. Nothing checks "publish only after commit" | (b) for the boundary; (c) for the rule's real property | TID251 run here; ESLint source confirmed; import-linter and dependency-cruiser from memory |
| ID-15 python: verify outside the entry | | ruff **TID251** `jwt.decode` ban plus `per-file-ignores` for the entry module. It caught the `from jwt import decode` form the ast-grep rule misses. semgrep `unverified-jwt-decode` checks a *different* property (verify=False) and is **not** coverage | (b) | run here |
| ID-15 typescript | | ESLint `no-restricted-imports` (`jsonwebtoken`, `jose`, `node:crypto` verify names) with file overrides; oxlint `no_restricted_imports` | (b) | upstream rule source confirmed via `gh api`; not run |
| sql ecosystem | | listed in `checks/README.md:25`, but no checks exist, so there is nothing to map to sqlfluff | n/a | read |

Ruff's `per-file-ignores` reproduces the plugin's "binds" mechanism (an allowed-module list) with no custom engine.

- **The binds documentation is wrong.** It says binds are "read from the project's bindings" (`checks/README.md:28`). The bindings template has no such row (`templates/compliance-bindings.md:5-18`). The harness infers them heuristically instead (`harness/lib/bhrules.py:132-177`).

### F9. Major: humans and agents are not held to the same rules

- Apart from the six checks, every rule lives in skill prose that only an agent loads. A human who commits a `fix:` with no record, or an ADR with no option judgement, meets nothing.
- **Fix.** Move the mechanical parts into tools that hold both kinds of author in CI or pre-commit:
  - commitlint for `fix(#N):` (`bug-analysis/SKILL.md:35`);
  - a GitHub issue form for the bug record (`templates/bug-record.md:1-9`);
  - ruff and ESLint configurations for the checks.

### F10. Major: a project has to build scaffolding before the skills do what they claim

- **The bindings file.** It names 12 bindings, including commands most projects do not have (`templates/compliance-bindings.md:7-18`):
  - "Close: the command that runs a record's Test and closes its issue";
  - "Bug ledger: the command that lists every record";
  - "Evidence environment".
- **Without bindings, results are only in the reply.** Every skill then answers in the reply, marked unrecorded (`compliance-review/SKILL.md:13`). bug-analysis can close a bug only through the bindings' close command (`bug-analysis/SKILL.md:38`).
- **Without an overlay, there are no packs.** A project with no overlay is reviewed with no pack (`compliance-review/SKILL.md:14`).
- **Fix.** Derive the tracker from the git remote (`gh repo view`) and drop the other bindings.

### F11. Major: bug-analysis turns every small defect into a tracker issue plus sweeps

- **What it requires:**
  - a defect "however small … in any file" (`bug-analysis/SKILL.md:8`) gets "One issue per bug" in the same turn (`:17`);
  - siblings are "worked as one list with the fix" (`:22`);
  - an independent review follows (`:37`);
  - "A second fix to one place steps back to the design first (`vetted-decision`)" (`:36`), which adds about 19k tokens.
- **What it conflicts with.** The owner's rules: apply new rules forward without retrofit sweeps, and discard theoretical minors.
- **What is worth keeping:**
  - the record is written before the fix;
  - the cause is never rewritten;
  - the bug closes only when its regression test passes.
- **Fix.** Keep those three. Make the test check deterministic: the new test fails at the parent commit and passes at the fix.

### F12. Major: the evals measure wording and tool counts, not outcomes or cost

- **Grader mix.** 216 graders are `tool_used`, which is good for triggering. 84 are `regex`.
- **No grader uses cost.** Every run records `costUsd`, `turns` and `durationSeconds`, but no grader reads them. The "cost" group counts file reads instead, for example `evals/cost/incremental-section-edit/graders/only-dc-ds-domain-files.md`. `README.md:163` claims these are "measured against a full review".
- **Trigger cases are artificial:**
  - they run with `allowed_tools: [Skill]` and `max_turns: 2` (`evals/trigger-bug/test-fails-1/prompt.md:4-5`), so the model has nothing else to do;
  - each skill has 2 to 6 prompts, which echo the description's words ("for compliance against our catalog");
  - no eval covers the harness or the termination block (0 files each).
- **Wording graders:**
  - `same-recommendation` matches `'O2'` anywhere (`evals/skills/decision-reused/graders/same-recommendation.md:3`), so "rejected: O2" passes;
  - `analysis-heading` (`'Analysis:'`) and `says-unrecorded` test the format only.
  - The without-plugin arm fails these by construction: `bug-record-rule-lines` without the plugin failed on `analysis-heading`, `says-unrecorded` and `rule-line-id01`. So with-versus-without proves only that the plugin's vocabulary appears.
  - Where the outcome is graded, the plugin adds nothing measurable: `decision-reused` passes 3/3 without the plugin too, at $0.049 against $0.075.
- **The only outcome measure is weak.** The accuracy group has 2 toy designs. The catalog author wrote the truth and re-labelled it during the runs. The verdicts depend on the model (F1).
- **The results are stale.** They are git-ignored local output. The last run was 2026-11-18T10:15Z, and 15 commits to skills, catalog and templates have landed since (counted in UTC). The evals are identical in the installed 1.5.2.
- **Fix.** Grade outcomes and measured cost:
  - the root cause matches a truth written by someone else;
  - the regression test fails on the parent and passes on the fix;
  - tokens and turns are compared against the no-plugin arm with a recorded ceiling.

  Run trigger cases with the full tool set. Add negative cases from the intended flow: a red acceptance test during build, a library mentioned in passing, an options list.

### F13. Major: deleting compliance-review breaks three kept skills unless two things move first

- **What depends on it.** `vetted-decision/SKILL.md:12-13,26`, `vet-oss/SKILL.md:12-13`, `bug-analysis/SKILL.md:12-13,21` and `skills/harness/SKILL.md:29` (tree) all load compliance-review's "Inputs", or its scoping or judging method, by reference.
- **What has to move:**
  - The bindings lookup (`compliance-review/SKILL.md:13`) becomes one sentence in each kept skill, or goes away once the tracker is derived from the git remote (F10).
  - The judging method goes too. `catalog/index.md:7-13` already states the load order and `:15-24` the readings, so nothing new is needed.
- **The installed harness also depends on compliance-catalog.** The 1.5.2 harness skill sends `overlay_candidates` to `compliance-catalog` (`1.5.2/skills/harness/SKILL.md:14`). That puts a skill the owner removed from routine use back into the routine path.
- **The pilot project is affected.** Its rules file and one of its decision records require vetted-decision.
  - A slimmed skill keeps the name.
  - That decision record justifies the skill by "a fixed catalog that covers them" and says one target is only partly in that catalog. If the catalog is replaced (F7), the record must name the targets it lists itself, plus the named external standards, and that wording needs a change.
- **The harness consumes the checks and the catalog (for the harness reviewer).** Replacing `checks/` and `catalog/` changes what the measurer and the work packets read: `checks/index.json`, and each packet's `rules` field (`skills/harness/SKILL.md:29`, tree).

---

## Minor findings kept for practical value

1. **Eval prompts hardcode a path on the reviewer's machine.** 11 prompts name an absolute checkout path (e.g. `evals/accuracy/billing-sync/prompt.md:7`), so the suite fails on any other checkout. This breaks the "reusable across projects" rule. Effort S: use a relative path or `${CLAUDE_PLUGIN_ROOT}`.
2. **The reviewed branch is not what is installed.** The tree is `harness-lean` (v1.5.0, a 1,082-word harness skill). The installed plugin is 1.5.2 (447 words), and the `v1.5.1` tag `7fff403` is not an ancestor of HEAD. A fix made on this branch will not reach what agents load. Effort S: review and fix on `main`.
3. **vet-oss contradicts itself, and a product-class record skips the catalog entirely.**
   - "Every verdict names a catalog rule id" (`vet-oss/SKILL.md:8`) conflicts with "a toolchain tool is judged on maintenance, pinned install, fitness …" (`:21`). A toolchain record in the pilot project follows `:21` and so cites no rule id.
  - A **product-class** record in the pilot project ("Class: product") also cites no catalog rule id, against `:8` and `:12`.
   - Six of the pilot project's 13 evidence directories cite no catalog id; the others cite between 1 and 38.
   - This states only what is on disk. It supports F5: the costly rule-row part is the part left out.
   - Effort S: settle `:8` against `:21` when slimming.

**Discarded as theoretical: 9.**
- NIST `SC-24`/`SC-28`/`SC-45` share the catalog's SC prefix.
- Base file headers say "Base catalog 1.1.0" (e.g. `LC.md:3`) while the index says 1.5.0.
- `checks/README.md:25` lists an empty `sql` ecosystem.
- bug-analysis uses "Supersedes:" against DC-03's wording ban; DC-03 covers documents, not tracker comments.
- The rule "catalog" and the helper "catalogue" share a name in the tree harness skill.
- 88 base rules appear in no scenario.
- The review key needs `git hash-object`.
- Probe leftovers sit in `evals/results`.
- The README pins v1.5.0 while a 1.5.1 tag exists.

---

## Fit for the intended flow

The intended flow: an epic design decision, then a plan, then tests written by a non-builder, then the build, then a deterministic measurer.

| Step | What serves it now | Problem | What is needed |
|---|---|---|---|
| Epic design decision | vetted-decision | Grades itself (F2), favours keeping code (F4), costs 11k to 19k tokens (F5) | Slim skill: options (keep, native, delete, OSS), one falsifying call per option, a fresh judge agent, written as an ADR in the MADR format. The falsifying call is handed to the harness as a target |
| Plan | `templates/plan-dry-run.md` (good: an independent literal follower); compliance-review PN rows | PN-03, PN-13 and DC-11 require gates (F3) | Keep the dry run as the plan check, reported as a count of guesses |
| Tests written by a non-builder | **nothing** | The tree harness treats acceptance tests as protected inputs that must already exist (`skills/harness/SKILL.md:38`). No skill or template writes them from the spec | **Missing:** a test-author step (a fresh agent given only the spec and contracts) whose output becomes the protected paths |
| Build | Harness builders; bug-analysis | bug-analysis fires on the normal red-to-green path (F5). The builder adopts libraries without vetting while vet-oss says it must vet (F4) | Narrow the bug-analysis trigger; get library facts from Scorecard and OSV |
| Deterministic measurer | Harness measure (out of scope); ast-grep checks | The checks are heuristic and can gate (F8) | Linter configurations (ruff, ESLint, import-linter) as the code-rule part of the measurer |

Also missing: nothing carries a decision's falsifying call into the measurer's targets, and no skill has a measured cost ceiling.

---

## Summary table

| Component | Verdict | Reason | Effort |
|---|---|---|---|
| `skills/compliance-review` | **Delete** | Its convergence claim is unsupported: the verdicts depend on the model (F1). It grades inline (F2), emits PASS/FAIL (F3) and costs 9.6k to 41.6k tokens (F5). The owner saw it cause loops. Move the bindings lookup and its method first (F13); send diffs to the host's `/code-review` | M |
| `skills/compliance-catalog` | **Delete** | It keeps generating hand-maintained rules, loops until ADEQUATE (F1, F3), costs 42k tokens and is project scaffolding. Remove the 1.5.2 harness call to it (F13). Base upkeep becomes a maintainer note | S |
| `skills/vetted-decision` | **Fix** (slim) | The structure is useful (keep, native, delete, OSS options; a falsifying call). It grades itself (F2), favours keeping code (F4), loads 11k to 19k tokens (F5) and restates LC rules (F6). Use a fresh judge, the ten targets plus named standards, and the falsifying call as a harness target. The skill name stays; the pilot project's decision record needs rewording (F13) | M |
| `skills/vet-oss` | **Replace** with OSS | 27k tokens for a product tool at every tier; 186 rules with no UNVERIFIED row favour own code (F4, F5); `:8` contradicts `:21` (minor 3). Use OpenSSF Scorecard (Maintained, Signed-Releases, Pinned-Dependencies, Vulnerabilities, Code-Review), deps.dev, OSV-Scanner and a licence scanner, plus a short note of requirements as `path:line` and one install check | M |
| `skills/bug-analysis` | **Fix** (slim) | Keep: record before the fix, cause never rewritten, close only when the test passes. Drop: per-typo issues, sibling sweeps, the termination block and the vetted-decision chain (F6, F11). Narrow the trigger (F5). Use an issue form and commitlint so humans are held too (F9) | M |
| `skills/harness` | **Keep**, fix | The deterministic measurer is the right core. Add the non-builder test-author step. Drop the coupling to compliance-review scoping (tree `:29`) and compliance-catalog (1.5.2 `:14`). Confirm `tests.passed >= 1` cannot be met by the builder's own tests (F2). Fix on `main`, not `harness-lean` | S |
| `catalog/` (base, packs, scenarios, CHANGES) | **Replace** | 192 of 332 rows cite only "Convention:" from one earlier project (F7). Rows impose gates (F3), the catalog went from 1.0.0 to 1.5.0 in 3 days (F1), and rows run up to 248 words. The harness's packet `rules` and `checks/index.json` must follow (F13). Point to maintained standards (ASVS, 800-53, SLSA/Scorecard, Well-Architected, EIP). Keep the owner-endorsed house rules as lint configurations or targets | L |
| `checks/` | **Replace** with linter configurations | Hand-written patterns: HO-02 is stricter than its rule, and ID-15 and HO-02 are easy to evade (F8). Ruff ASYNC110/TID251 and ESLint `no-await-in-loop`/`no-restricted-*` cover most of them by configuration. Drop the `poll*interval` heuristic, which nothing else covers | S |
| `templates/review-brief.md` | **Delete** | Used only by compliance-review; restates LC rules (F6) | S |
| `templates/catalog-audit.md` | **Delete** | Used only by compliance-catalog; the ADEQUATE/WEAK gate has no round limit (F1, F3) | S |
| `templates/plan-dry-run.md` | **Keep**, fix | An independent literal follower fits the plan step. Report a count of guesses instead of "BROKEN" (`:15`) | S |
| `templates/bug-record.md` | **Replace** with a GitHub issue form | Host feature; holds human and agent authors to the same record (F9) | S |
| `templates/compliance-bindings.md` | **Delete** | 12 bindings of project scaffolding (F10). Derive the tracker from the git remote | S |
| `evals/` | **Fix** (rebuild) | Wording and read-count graders; no cost grader; trigger cases restricted to the Skill tool; truth written and re-labelled by the author; stale and git-ignored results; hardcoded paths (F12, minor 1). Keep the `tool_used` trigger graders. Add outcome and cost-ceiling graders and negative cases from the flow | M |
| `README.md`, `.claude-plugin/` | **Fix** | The "industry-standard", "converge" and PASS/FAIL claims are not supported (`README.md:3,7,68`; `plugin.json:4`). Rewrite them for what remains and line up the version with what is installed (1.5.2) | S |
