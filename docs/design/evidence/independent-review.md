# Independent review: Quality by Construction v7

Reviewed 2026-11-25. The reviewer did not write the design or its evidence.

Inputs (all read in full):
- the design page, v7 (an earlier draft of `docs/spec/quality-by-construction.md`);
- `evidence/inv-plugin.md`, `review-harness.md`, `review-skills.md`, and two pilot-only inventories (the pilot's checks and defect classes; its work-intake history), kept in the pilot project's own repository. They are cited below as [ev pilot inventory] and [ev pilot intake history].

No other file was changed.

**Scope.** P3, S and I are taken as decided. Findings below say how the design, as written, must be completed *within* those decisions. None of them argues against the decisions.

**Basis tags.**
- [text]: the design's own words.
- [ev file:line]: an evidence file.
- [checked]: run on this machine.
- [inference]: the reviewer's reasoning, not yet verified.

**Totals.**
- 3 Critical, 15 Major, 8 Minor kept.
- 5 excess items.
- 11 theoretical minors discarded.

Findings the design already admits are listed separately at the end and are not counted.

**Index by kind.** Each finding is listed once, under its main kind.

| Kind | Findings |
|---|---|
| Contradictions | C3, M3, M5, M6, M12, m1, m2 |
| Claims not backed | M15, m3, m4 |
| Missing pieces | M7, M8, M9, M10, M11, M14, m5, m6, m7, m8 |
| Excess | E1 to E5 |
| Gaming routes missed | C1, C2, M1, M2, M4, M13 |

---

## Critical

### C1. The builder controls what the measurer runs
**Where.**
- Terms, "Ratchet / baseline": "The list may only shrink, so new code must pass and old code is fixed when it is next touched."
- Levels, L4: "Counter: the tests sit in protected paths (SG-01), and the measurer runs the protected copy."
- Levels, L5: "The deterministic measurer runs the test entry point, the item's tests and targets".

**Problem.** Only the item's own acceptance tests are named as protected. The measurer runs the test entry point from the builder's tree, so any of these one-line edits turns a miss into "met" [inference, ev review-harness.md:138-146]:
- the `test` or `verify` recipe in the build recipe file;
- `[tool.ruff]`, `[tool.pytest]`, `conftest.py`, `tsconfig*.json` or `.sqlfluff`;
- every ratchet list the design itself creates: per-file-ignores, `.sqlfluffignore`, the generated `ignore_imports`, the `tsconfig.strict.json` include list, and the pinned gate-test hashes;
- inline suppressions: `# noqa`, `eslint-disable`, `@ts-expect-error`, `pytest.mark.skip` or `xfail`;
- acceptance tests of earlier slices, which are no longer "the item's".

The design gives "may only shrink" no mechanism. Humans have the same routes.

The evidence already names the fix for part of this:
- K5: "guard the test command's own files and test configuration by default … record the JUnit test ids that are missing compared with HEAD as a fact" [ev review-harness.md:145].
- Suppression markers are a recorded fact type [ev inv-plugin.md:22].
- RUF100 for stale ignores [ev pilot inventory].

**Decide before building.**
1. The measurer overlays these from the base ref: entry-point recipes, test and lint config, ratchet files, and all existing tests.
2. Ratchets compare against the merge base, not the working tree. This matches review-harness M1's "read the targets from HEAD".
3. A diff that adds a suppression or a skip, or grows a ratchet list, or drops a JUnit test id, is a recorded fact with a named reader (see M7).
4. A legitimate config change is declared in the packet and written by a non-builder.

### C2. The orchestrator grades itself
**Where.**
- Plane 2: "The orchestrator decides the tier (epic, design-affecting or mechanical) from facts at launch".
- "the orchestrator approves a design-affecting packet (L2); a mechanical packet needs no approval beyond the tier fact."
- Terms: the work packet is "Written by the planner or orchestrator, never by the builder."
- "The measurer records the scope fact (plugin SG-02), and the orchestrator re-tiers or re-plans."
- Mechanisms table, row "Orchestrator brief template", gaming route "Steps written into the goal": "Nothing mechanical. The brief is kept with the item, so the owner can read it".
- Orchestrator briefs: "That is what happened when 34 of 47 committing agents skipped vetted-decision."

**Problem.** The design's own diagnosis blames the orchestrator's briefs for the skipped design step. The same actor then does all of the following [text]:
- sets the tier, which decides whether design and tests-first happen at all;
- may write the packet, and approves it;
- writes mechanical packets with no approval;
- is the only reader of the facts meant to correct its own under-tiering.

The table's gaming route "Under-tiering to save tokens" is the orchestrator's route, and its counter routes back to the orchestrator.

The tier rules also contradict each other, so even an honest orchestrator has no rule to follow:
- the Mechanical tier lists "Renames, pin bumps, docs";
- the Design-affecting trigger is "Touches a contract, schema, roles or grants, compose, pins, or an architecture-target budget".

**Decide.**
1. The tier is computed by the engine from the packet's declared paths against the trigger list. That is data, not judgement.
2. A scope fact that hits a trigger re-queues the item automatically.
3. The planner, never the orchestrator, writes every packet, mechanical ones included.
4. The builder's prompt is assembled mechanically from packet fields, so there is no free-text brief in which to slip steps.
5. The owner reads one fact line per item: "tier X from paths Y".

### C3. Under S, nothing says how plugin-shipped checks reach the human's build
**Where.**
- Principles: "The same code rules apply to every author. … They run in the build and cost zero tokens."
- Principles: "No code rule exists for agents only".
- Hooks: "Any check they run is a check the human's build runs too."
- S, option C: "The plugin ships linter presets and pinned checkers and runs them itself".
- S, recommended: "The generic checks of Plane 1 then ship in the plugin … A project supplies only standard files it already has."
- Plane 1: "CI runs both as the last line, added last."
- Rollout step 5: "CI backstop on a self-hosted runner."

**Problem.** The text contradicts itself. Option C has the plugin run its presets "itself", and S says a project uses the plugin "without setup". But Plane 1 and End of build say every check is one "the human's build runs too". A check the plugin runs itself, in a project with no setup, is not in the human's the test entry point. Built as worded, presets become agent-only rules, and aims 1 and 2 fail.

The only way to keep both is for presets to enter the project's build. That needs a line in the project's build recipe file or linter config, which is S's own "ask once, write a standard file" step (D). The design never says this is how presets land. "Pinned checkers" fetched by the plugin also repeat the platform gate K2 [ev review-harness.md:97-109].

Until rollout step 5, nothing runs the build on a human's push: "rules file: run the tests before push | prose only (no hook/CI)" [ev pilot inventory]. For rollout steps 1-4, only agents are held. The design also never says what a red CI after a human's direct push to main does.

**Decide.**
1. Generic checks ship as standalone configs or a CLI, written once into the project's own standard config files (S-D), so the test entry point and CI run them for everyone.
2. The plugin never runs a check the project build does not.
3. Decide what red CI on a human push produces: a fact, or a defect under its slice.
4. Decide whether a minimal CI running the test entry point moves ahead of step 5.

---

## Major

### M1. H0 as specified does not hold
**Where.**
- H0: "A refusal leaves nothing to game, because only the orchestrator or planner can create the packet: it lives in a protected path (SG-01)."
- Terms: "SG-01 overlays protected paths … so the builder's edits to them have no effect."
- Trigger: "H0 · PreToolUse (Edit/Write), first code edit without a packet".
- Plane 2 banner: "Order comes from the flow, not from refusals."
- History table: "H0 records a bypass as a fact".

**Problems.**
- (a) **The packet can be self-written.** SG-01 is a measure-time overlay, but H0 reads the worktree at edit time. A builder with bare Bash [ev review-harness.md:76-78] can write a packet file, and H0 lets it through. The P3 spike plants exactly this test, yet the design already asserts the result.
- (b) **Bash edits bypass both hooks.** The matcher covers Edit and Write only, so `sed -i`, heredocs, `git apply` or a Python write never reach H0 or H2 [inference]. The spike does not list this route.
- (c) **The scope is undefined.** The plugin is on in any project. If H0 matches every edit, it refuses the main session and every human-driven session. If it matches only the `harness-builder` agent type, a "launch by hand" of a general-purpose agent, the case it targets, is never refused.
- (d) **The orchestrator message has no channel.** A PreToolUse hook answers only its own session [ev inv-plugin.md:34]. No channel is named for "Message to the orchestrator".
- (e) **The text contradicts itself.** The banner and history row say order comes from the flow and H0 records a fact. The H0 section says it refuses.

**Decide.**
- Make order structural at launch: the engine creates a builder's clone only from a packet. This is K1's separate-clone fix [ev review-harness.md:91-94].
- Then either drop H0 or keep it as a fact for hand launches, with a defined predicate, Bash coverage and a delivery channel.

### M2. Tests-first drops held-out cases, and the red-on-main check misses the common case
**Where.**
- L3: "Vacuous tests: the red-on-main fact and pinned hashes".
- L4: "A mission-command brief: the packet plus the failing tests."

**Problems.**
- **Overfitting is open.** The builder sees every test, so special-casing expected outputs passes measurement. The plugin already has a holdout ref [ev inv-plugin.md:11], and review-harness M2's fix has the test author write "held-out tests to the holdout ref" [ev review-harness.md:214-217]. The design omits both.
- **Red-on-main carries no information for new modules.** A test for a module that does not exist yet is red on main through an ImportError or collection error, whatever it asserts [inference]. JUnit separates `<error>` from `<failure>`.

**Decide.**
1. Held-out cases, unseen by the builder (needs the K1 fix).
2. Record whether a test is red by failure or red by error.

### M3. The design-affecting tier has no design step
**Where.**
- Orchestrator briefs: "Design-level work starts with a design agent. It produces a decision record (L1 for an epic, or the planner's packet at L2). … One agent never both designs and builds."
- L2: "No design beyond L1" and "Counter: the packet has no design field".
- L4: "The builder designs freely within the constraints".
- L3: tests are written "from the packet and contract".

**Problem.** A non-epic slice that changes a contract, schema or grants gets no L1, and the planner may not design. So the builder designs, in the very tier named after design. This also contradicts the pilot's agent rules file, which routes such choices through vetted-decision. And L3 needs the contract change before the tests exist, but no role writes it.

**Decide.** One of:
- the planner authors the contract, schema or role delta in the packet, judged by a fresh agent; or
- every design-affecting slice gets a short L1.

### M4. Mechanical bug fixes are graded by their builder
**Where.**
- Tier table, Mechanical: "a bug fix inside one owner with no change to a contract, schema, role, compose file or budget | L4, then L5 | 1 builder".
- Defect table, weakened tests: "Protected acceptance paths written by a non-builder (L3)".

**Problem.** Bug fixes get no L3, so the builder writes both the regression test and the fix. Bug fixes are frequent: 199 of 460 commits carry `fix(#N)`, though that prefix also marks issue delivery [ev pilot inventory]. The intake already names a finder for each defect: "A test, the measurer, a review or an agent finds it".

**Decide.**
1. The finder, or the test author, writes the failing regression test into a protected path.
2. Record "fails at the parent, passes at the fix" [ev review-skills.md:238].

### M5. L1's counter rests on what the design itself replaces
**Where.**
- L1: "Counter: vetted-decision judges every option against the catalog, and the owner approves".
- Verdict table: "vetted-decision | Fix: slimmer, with a fresh agent as the judge".
- Verdict table: "Catalog | Replace with references to maintained standards".
- Findings: "The skills also grade their own work: one agent proposes and judges."

**Problem.** The record the owner approves is judged by its own author [ev review-skills.md:77], with a tie-break that favours keeping existing code [ev review-skills.md:107], against a catalog marked for replacement. The rollout does not schedule the slimmed skill before the pilot's first epic.

**Decide.**
1. L1 is a proposer plus a fresh judge, scored against the project's architecture targets plus named standards.
2. Falsifying calls become measurer targets [ev review-skills.md:306].
3. Order it in the rollout before step 4.

### M6. "Gate" is undefined, so four mechanisms cannot be classified
**Where.**
- Principles: "No pass/fail gates on quality. Facts are recorded, limits cap rounds, and only measured targets move an item on."
- End of build: the measurer runs "layout, lint, generated-code freshness, unit tests, and the item's acceptance tests. A miss goes back to the builder … within the round limit".
- Intake: "A review finding attaches to the slice under review. It reopens that slice's checklist".

**Problem.** Every lint or ratchet finding becomes must-pass for "met". That is the shape the evidence calls a gate: "counts violations as unmet until zero … these pattern rules therefore act as a gate" [ev review-skills.md:184], and "The rules target is either a gate or empty" [ev review-harness.md:53]. The design never says why its linters differ. Also undefined:
- (a) the item's state at the round limit;
- (b) a reviewer's opinion reopening a slice, which contradicts "only measured targets move an item on";
- (c) red CI on a human push (see C3).

**Decide.**
1. A one-line definition, for example: a gate is a pass/fail outcome taken from opinion or environment. A deterministic check that is declared before the work, holds every author, teaches, and has a recorded exception path is a target.
2. At the round limit: a fact to the owner and a re-plan. Name this "stuck" state in the measurer, which P3 ports.
3. Critical and Major review findings become a failing protected test written by the test author. Then only a measured target reopens a slice [ev review-harness.md:213].

### M7. Facts have no readers, and the rollout fixes only Criticals
**Where.**
- L3: "The measurer records whether they fail on main".
- L5: "the measurer records the flaky fact".
- Terms: "the measurer's facts reach no one (review K1, K5)".
- Rollout: "Nothing from the existing plugin is used before its Critical findings are fixed."
- P3: "the measurer core and value order, after their Critical fixes".

**Problem.** Facts are the design's main non-gate tool, yet none has a named reader or action: red-on-main false, flaky, scope, H0 bypass, idle tracking issue.
- "Facts reach no one" is M14, a Major, not K1 or K5 [ev review-harness.md:321-331].
- A Critical-only fix list would port the measurer with M14 (facts unread) still open.
- It would also leave two gates in the ported code: M1, the commit gate [ev review-harness.md:186-204], and M12, the env_setup block [ev :307-310].

**Decide.**
1. A table: fact → reader → action → channel.
2. Rollout condition: the Criticals plus M1, M12 and M14.

### M8. Under S, the declared data the generic checks need has no standard source
**Where.**
- S, option B: "owners from CODEOWNERS and OpenAPI tags; ownership facts from the database catalog".
- S, option D: "records the answer in a standard file (CODEOWNERS, an OpenAPI tag)".
- Defect table: "diffed against the specified role table" and "policy literals checked against the registry".
- History table: "everything ships in the plugin, and a project supplies only standard files".

**Problem** [inference]:
- CODEOWNERS maps paths to people or teams, for review requests. It cannot name a module.
- The owner tag is an OpenAPI vendor extension the pilot chose. Writing it into another project is plugin scaffolding under another name.
- The pilot's Markdown role table, its role-naming convention, its policy registry, the Rec 20 list and the gate hashes are pilot-only.

So "everything ships in the plugin" is wrong for these, and the design does not say where they live. Also undefined:
- how a generic plugin reaches an unknown project's database for "ownership facts";
- behaviour on an unsupported stack, which today reads "0 violations, met" [ev review-harness.md:127].

**Decide.**
1. For each generic check, its declared-data source in a project other than the pilot. Candidates to vet: Backstage `catalog-info.yaml` `spec.owner`, package.json `exports` or PEP 8 `__all__` for published parts, and workspace members for boundaries.
2. Or state that project-specific fitness functions stay project tests, run through the project's own entry point.
3. An unsupported stack produces a "not checked" fact, never a met target.

### M9. Limits: no override place is named, and the list is incomplete
**Where.**
- Principles: "Every limit is a default with a stated override in a standard place, never a constant or a plugin-specific file".
- L2: "Capped at 1,600 tokens (sizing.packet_tokens)".
- H1: "At most 2,000 characters".
- H2: "About 200 characters".
- Messages: "the first 10 are shown, then a count".
- L1: "at most 2 pages".
- L5: "the round limit".

**Problem.**
- No override place is stated for any limit.
- `sizing.packet_tokens` is a key in the harness's own config, which is a plugin-specific file.
- Five limits used in the design are missing from its list: H1's 2,000 characters, H2's 200 characters, the first 10 findings shown, the 2-page record cap, and the round limit (whose value is also absent).
- The 100-box Known-issues cap [ev pilot intake history] is also missing.
- The packet cap is "reported, never enforced" today [ev review-harness.md:288-289].
- Token caps need a tokenizer; characters are deterministic.

**Decide.**
1. One standard home for overrides. One candidate is the host's settings files, if the pinned Claude Code version supports plugin options [not verified].
2. The full list of limits.
3. Caps in characters.
4. What happens at the packet cap: cut, or record a fact.

### M10. The teach() helper: no home, and the claim is overstated
**Where.**
- Messages: "Every project check, fitness function and hook reports through one helper whose arguments are all required: teach(rule, wrong, right, ref). A bare rejection can't be written."
- Messages: "A rule with a fixed message (for example ruff PLR2004) gets a one-line 'right way' keyed by its rule code."

**Problems.**
- (a) **Coupling.** If the helper ships in the plugin, project tests import Claude Code plugin code. Then the test entry point fails without the plugin, the same coupling review-skills criticises in LC-43 [ev review-skills.md:167].
- (b) **The claim is false.** A plain `assert`, a `raise`, or `right="fix it"` bypasses the helper. Required arguments do not make the text teach.
- (c) **The text has no home.** The right-way text for fixed-message linters is project-specific: the design's own PLR2004 example names the pilot's policy registry file. It has no standard home, and it shows only when output passes through a wrapper, not in an IDE or a bare `ruff check`.

**Decide.**
1. Where the helper lives (see C3).
2. Right-way text as data keyed by rule id, held in the document the `ref` cites.
3. A rule id with no entry is a fact.

### M11. Plugin runtime state has no home under S
**Where.**
- H0: "it lives in a protected path (SG-01)".
- H2: "It also records the fact for the orchestrator".
- Mechanisms table: "The brief is kept with the item".
- Intake: a slice is "A sub-issue of the tracking issue".
- S: "never in a plugin file".

**Problem.** The design gives no location for the packets, tier facts, scope, flaky and red-on-main facts, the scoreboard, the held-out cases or the ratchet baselines. Each choice has a cost:
- If the packet is an issue body, any agent can edit it, because agents hold the owner's token (M13).
- If it is a repo file, it is scaffolding of the kind option E rejected, and K1 lets the builder write it.

**Decide.** One home per kind of state. Candidates to vet:
- the packet as a sub-issue body, hashed at approval;
- facts as check runs or git notes;
- the holdout as a ref outside the builder's clone.

### M12. The contents of v2 cannot be derived from the design
**Where.**
- P3: "porting only what the host lacks (the measurer core and value order, after their Critical fixes)".
- Verdict table: "Orchestrator bh, set_branch, value order, bh-answer, history | Keep. The shape is right … | —".
- L2: "planner (plugin harness-planner / bh-brief)".
- Verdict table: "9 unused bh-* scripts; old workflows | Delete".
- H1: "SubagentStart".

**Problem.** Three lists disagree:
- P3 ports two pieces;
- the verdict table keeps, fixes, replaces or deletes a dozen harness and skill components;
- the levels table relies on harness-planner, bh-brief and SG-01/02.

The evidence says the orchestrator needs a fix of effort M, not "Keep, —" [ev review-harness.md:521]. bh-brief is one of the nine scripts marked for deletion [ev :441]. Under a bh-style engine, builders are separate `claude -p` sessions [ev :44], while SubagentStart fires "in the parent session around each subagent" [ev inv-plugin.md:33]. So H1 would not fire [inference; this is the spike's third question].

**Decide.** One table: flow function → host feature, OSS tool or ported module → fixes → effort. Where the spike's two outcomes differ, show both.

### M13. Agents act as the owner on GitHub
**Where.**
- Plane 2: "the owner approves an epic's decision record (L1)".
- H0: "only the orchestrator or planner can create the packet".
- Intake: "Agents file most issues through gh issue create".
- Standards: "least privilege (NIST SP 800-53 AC-6)".

**Problem.** "Every issue and every comment is authored by the single owner login (agents file with the owner's token)" [ev pilot intake history]. So any approval, packet, label or sub-issue link can be produced by any agent. "The owner approves" and "only the planner can create" cannot be checked. The design cites AC-6 but does not apply it.

**Decide.**
1. A separate identity per agent role (for example, a GitHub App or fine-grained tokens) with per-role scopes.
2. Owner approval is an action recorded under an identity agents do not hold.

### M14. Intake mechanics
**Where.**
- Industry practice: "issue forms with required fields (parent, goal, acceptance). … the parent check also runs on new issues, as a GitHub Action that comments with a teaching message".
- The parentless message: "No parent decision. Every issue sits under a decision's tracking issue: pick one, or start a decision if this is a new capability."
- "A tracking issue with no slice activity is reported to the owner as a fact."
- The Minor row names the pilot's Known-issues issue by number.

**Problems.**
- (a) **A form's parent is body text.** It is not a native sub-issue link, and nothing is named to convert it.
- (b) **The Action races the link.** The local gh (2.46.0) has no parent flag on `gh issue create` [checked: `--help` lists only milestone and template], so an agent creates the issue and then links it in a second call. An Action on `opened` can fire in between and comment falsely, which teaches agents to ignore it [inference; newer gh not checked].
- (c) **The message offers no right way for older code.** A defect in code that predates any tracking issue has no listed parent: "No decision has an issue list" [ev pilot intake history], and "start a decision" is wrong for a bug.
- (d) **"No activity" has no event.** A timer breaks the pilot's rule "No waits by sleeping or polling; react to events".
- (e) **The Known-issues list is hard-coded.** It is a pilot issue number inside a generic flow.

**Decide.**
1. Set the parent atomically, or run the check on the link event.
2. A default parent for defects in existing code, for example one standing tracking issue per owner.
3. Report idle tracking issues at an event.
4. Find the Known-issues list by label.

### M15. The success measure and the cost case cannot show what the design claims
**Where.**
- "it only pays if reopens fall. That is measured with the churn metrics; the reopens-per-day baseline before the lean process was 11."
- "measured runs took 80k–420k tokens per agent", plus the "Rough tokens per item" column.
- "That is what happened when 34 of 47 committing agents skipped vetted-decision."
- Rollout: "built and proven on the toy project".

**Problems.**
- (a) **Reopens fall by construction.** I2 turns review findings into checklist reopens and minors into Known-issues lines, and compliance-review is deleted. That skill was the source of 10 of the 16 reopens [ev pilot intake history]. So reopen events fall whatever the flow does. The metric is gamed by the design's own intake change, and it is computed by the author's script.
- (b) **There is no stop rule.** No threshold or window is set.
- (c) **Cost claims are unbacked.**
  - The token figures (80k-420k per agent, and the per-tier columns) appear in no evidence file. The evidence says "No recorded paid run has measured any job" [ev review-harness.md:294].
  - The "11" baseline is not in the evidence either.
  - "2 to 4.7 times" is really 1.5x to 4.7x, and is "a floor, not a like-for-like baseline" [ev review-skills.md:120-129].
- (d) **The benefit claim is unbacked.** 34 of 47 is "an upper bound of omission", because many committing agents had no design choice to make [ev pilot inventory]. The causal claim about briefs is not shown.
- (e) **"Proven" has no acceptance list.** The spike plants only two routes: editing the tests and writing one's own packet. The other gaming rows have no planted test: under-tiering, vacuous tests, suppressions and ratchet growth, Bash-path edits, and a split diff dodging review.

**Decide.**
1. A per-slice metric independent of issue mechanics, recorded by the measurer: measurer rounds, defects found after merge and traced to the slice, and tokens from the job records.
2. A target and a stop rule, as a default with an override.
3. One planted test per gaming row.

---

## Excess (cut without losing an aim)

- **E1. H1 duplicates the packet.** L2 already carries "the touched owners' rows and published interfaces", and L4's brief is "the packet plus the failing tests". Cutting H1 saves about 500 tokens per agent and removes the SubagentStart dependency (M12).
- **E2. H2's own record duplicates SG-02.** The diff-derived scope fact cannot be deleted by the builder. Keep H2's one-line note and drop its record.
- **E3. Brief and packet are two schemas for one artifact.** The brief has goal, tier, constraints, acceptance and environment; the packet has goal, constraints, declared paths and acceptance. Merge them into one packet that adds tier and environment fields.
- **E4. History inside the design.** "From earlier proposals to this design" (20 rows), the decided option tables (S A–E, I1–I4), "Withdrawn: D1, D3–D7" and the decided D2, P, S and I boxes are about a quarter of the page. Move them to evidence or git history; the decision lines stay.
- **E5. Unbacked token numbers.** Cut the "Rough tokens per item" column and the "80k–420k" line until rollout step 2 measures them.

## Minor (kept for practical value)

1. **Packet content contradiction.** "The agent rules file shrinks to judgement … At L2 these become packet constraints." contradicts "A brief never contains … the agent rules file repeated." Both spend packet tokens.
2. **Two trigger lists.** Fresh-stack runs "for items tiered on compose, recipes, schema, roles or bring-up", while the tier triggers read "a contract, a schema, roles or grants, compose, pins, or an architecture-target budget". One detector needs one list.
3. **"Cover most of them" overstates.** Of the 9 check rows, at most 3 are covered out of the box. The rest are "still a hand-maintained list, only moved" or uncovered [ev review-skills.md:186-201]. Count the ban lists in ruff and oxlint config in the "pattern lists to stop growing" ratchet.
4. **Major count.** "2 Critical and 7 Major findings" should be 11 Major (F3–F13), which understates the replacement work.
5. **The review trigger needs a detector.** "auth, keys, grants, money or signatures" needs one. Today's is `AUTH_RE`, a hand-maintained pattern list [ev review-harness.md:364]. Derive it from declared data, or list it as a limit with an override.
6. **Guidance during writing is ownership only.** Only H2 acts while the agent writes, so every Plane 1 class surfaces only at end of build, at the cost of a measurer round. A silent PostToolUse hook that runs the project's own linter on the changed file is "a check the human's build runs too". Measure it in the spike.
7. **pgTAP question.** Roles and grants are the second-largest defect class (~37). The pilot already evaluated pgTAP, and as far as the reviewer recalls it has owner and privilege assertions (`table_owner_is`, `table_privs_are`, `roles_are`) [not verified]. Would assertions generated from declared data replace the custom pg_catalog diff? (This is a question, not a recommendation.)
8. **Published-part declarations exist.** The design says "nothing declares that today", but package.json `exports` and PEP 8 `__all__` are standard declarations S could infer from (the pilot's rules file already cites "package exports" as structure).

## Admitted by the design but not resolved (not counted)

- TID251 "Parity unproven".
- Brief steps: "Nothing mechanical" (now C2).
- SG-01 and SG-02 hold "only after those fixes".
- The order-engine spike.
- "Tiering is a prediction".
- Issue types replaced by a label.

## Discarded theoretical minors: 11

1. One step in the issue-chain example.
2. "weren't reopened", although one such issue was reopened once.
3. The wording of "or when its file is next touched".
4. H0's packet check is not a check the human build runs.
5. H2 on files with no owner.
6. The Known-issues issue has no parent itself.
7. DDL outside migration paths dodging tiering.
8. Reviewer freshness is not stated.
9. H0's "Stop and ask" (a subagent cannot ask).
10. The planner and the test author could be the same agent.
11. Owner approval per epic vs the owner's standing autonomy preference.
