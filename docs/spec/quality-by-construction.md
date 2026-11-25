# Quality by Construction: specification

Status: v9 design, decided items marked in section 13. Rationale for the decisions is in `docs/adr/0001-quality-by-construction.md`. This file holds the requirements.

Requirement words follow RFC 2119 (MUST, MUST NOT, SHOULD, MAY). Each requirement has a stable ID, QBC-n, which acceptance tests cite. Evidence files are in `docs/design/evidence/`.

## 0. Goals, principles and requirements (acceptance checklist)

Owner, 2026-11-25. This section governs: where a later section conflicts with it, this section wins, and the conflict is a defect to fix in the later section. Every slice's acceptance criteria cite the items they prove (G*, P*, R*) as well as the QBC ids, and a slice is done only when its cited items are proven.

### Goals
- [ ] **G1.** Code quality is caught before and during writing, not by review loops or CI after the fact.
- [ ] **G2.** The same quality rules apply to every author, human or agent, enforced in the build.
- [ ] **G3.** Agents are guided by the paved road: the right way is the easy way, and acceptance criteria and rules are handed over upfront.
- [ ] **G4.** Work enters in a structured way: decisions first, then slices; nothing free-floating; the backlog is bounded.
- [ ] **G5.** Low cost and fast flow: low tokens, low maintenance, no step that slows the whole process.
- [ ] **G6.** A self-sustained, reusable plugin that works in any project on day one.

### Principles
- [ ] **P1.** Industry standards and best practices for every choice; no invented processes.
- [ ] **P2.** OSS and code reuse before new code. Host first: use what Claude Code, git and GitHub already do.
- [ ] **P3.** No agent in the mechanical path. Period. A program runs git, tests, measuring and ordering.
- [ ] **P4.** No pass/fail gates on quality. Facts are recorded, limits cap rounds, and only measured targets move work on. Refusals are used only for order.
- [ ] **P5.** Every rejection teaches what is wrong, the right way, and how to prevent it, concisely.
- [ ] **P6.** Nobody grades themselves.
- [ ] **P7.** Paved road over restriction. Keep a restriction only when it is cheap and protects measurement.
- [ ] **P8.** No hard-coding. Every limit is a default with an override in a standard place (the plugin's project-local folder).
- [ ] **P9.** Convention over configuration: presets, inference, ask once, and answers stored in standard files.
- [ ] **P10.** No excess: build only for a measured need; low cost, clear, extensible.
- [ ] **P11.** Rules apply forward: ratchets, no retrofit sweeps, no reopening old decision records.
- [ ] **P12.** Don't plan around things we can't control (for example CI, or accounts we can't create).

### Requirements
- [ ] **R1.** Order engine: a program launching `claude -p`. Measuring costs 0 tokens.
- [ ] **R2.** Builders work in a `git clone --shared` of the local base commit. No remote fetch is required.
- [ ] **R3.** Acceptance tests are visible (ATDD) and written by someone other than the builder. "Red" means a failed assertion.
- [ ] **R4.** Integrity: the measurer lays the planner's tests and config over the build, checks a canary, and records tampering as a fact. Kept cheap restrictions: the Bash sandbox and scoped Edit/Write.
- [ ] **R5.** The packet is written only by the orchestrator or planner, and arrives at session start. A builder that edits without one gets a teaching refusal (order). It carries the goal, tier, constraints, `acceptance[*]`, the visible acceptance tests (`verifier.acceptance_paths`), `verifier.targets[*]`, `verifier.rules[*]` with their teaching messages, the paved road (`paved_road.test_paths`, `paved_road.dependency_command`), the ratchet baselines and a self-check command (`bh check`).
- [ ] **R6.** The tier is derived mechanically from the declared paths and the actual diff. Semantic Versioning: a patch or minor pin bump is mechanical; a major bump is design-affecting.
- [ ] **R7.** Linter presets (ruff, ESLint, oxlint, sqlfluff) are written into the project's standard config files and pre-commit, so a human's build runs them. Old pattern checks are retired only after parity.
- [ ] **R8.** Intake (GitHub-native): milestone (goal), decision tracking issue, slice sub-issues, defect sub-issues. Minors go in one Known issues list, bounded at a default of 100 set as policy. Issue forms with required fields; a parent check that teaches.
- [ ] **R9.** The owner's 8 verdicts: delete compliance-review and compliance-catalog; vetted-decision slimmer with a fresh judge; vet-oss replaced by Scorecard, deps.dev and OSV; bug-analysis narrowed; catalog replaced by standards plus house rules; pattern checks replaced by ruff and ESLint; evals on outcomes and cost; harness skill kept with a test-author step.
- [ ] **R10.** Host caveat: on Ubuntu 26.04 the sandbox needs `allowAllUnixSockets`, so the builder account stays outside the docker group.
- [ ] **R11.** Measured success (DORA): change-failure rate, lead time per slice and tokens per met slice, compared with the pre-v2 baseline.
- [ ] **R12.** Rules reach each item by facts, not by an agent's judgment (section 6.6). Each item gets only the rules that apply to it, so no project pays for the whole catalog, and no item misses a rule its change needs. A measured miss corrects the mapping.

## 1. Purpose and scope

How code quality is enforced for every author, human or agent, and how coding agents are guided before and during writing. Architecture, design and coding-standard rules live in the build. Agents get order and just-in-time context only, scaled by how much design the work carries.

- QBC-1. Quality rules MUST be enforced by the build (Plane 1) for every author. Agent guidance (Plane 2) MUST carry only order and just-in-time context.
- QBC-2. The design applies to any project the plugin runs on. Project-specific facts MUST come from standard files the project already has (section 7).

## 2. Why: measurements from the pilot project

The pilot project is the private first user of the plugin. Its measurements, five days into the project, with about +-30% noise (defect counts come from commit subjects):

- 13 of 47 committing agents in the session ran the decision skill (vetted-decision); 11 ran the owner-lookup recipe; 4 did both. Across all sessions: 265 committing agents, 36 ran vetted-decision, 29 the lookup, 11 both.
- 22 reopens on 16 issues, mostly from review rounds after the build, not from a failing build.
- 6 of the 9 rules in the project's agent rules file were prose only; 3 had a check.
- 68 hand-written regexes in 31 layout scripts: the pattern lists are to stop growing.
- 34 of 47 committing agents skipped the decision step.

- QBC-3. Success MUST be measured with DORA metrics (change-failure rate and lead time per slice) plus tokens per met slice, compared with the pre-v2 baseline (§0 R11). Reopen counts are not a success measure.

## 3. Principles

- QBC-4. The same code rules MUST apply to every author. Architecture, design and coding-standard rules MUST run in the build and cost zero tokens.
- QBC-5. No code rule MAY exist for agents only, and no hook MAY match code patterns. A pattern worth catching MUST become structure, a fitness function or a configured linter rule in the build, where it also catches a human.
- QBC-6. Nobody grades themselves. Order MUST come from the flow, never from the builder deciding whether a rule applies to it.
- QBC-7. Each rule MUST have one home. When a build check covers a rule, its prose line MUST be deleted.
- QBC-8. Rules apply forward. Each new check MUST start from a baseline (a ratchet). No old check MAY be retired until its replacement catches the same planted violations (parity test).
- QBC-9. Tokens MUST be counted per item, not per prompt. The number of agents per tier is the real cost; the figures are to be measured (R11).
- QBC-10. The design MUST use host features and OSS first. The plugin MUST be self-sustained (section 7). It is proven on its toy project, and nothing from the existing plugin is used before review (section 8).
- QBC-11. There MUST be no pass/fail gates on quality. Facts are recorded, limits cap rounds, and only measured targets move an item on. A refusal MAY be used only for order, when a step is attempted before the step it depends on (H0), and it MUST teach the right step.
- QBC-12. Every rejection MUST teach the right way. This applies to any check, hook, verifier, linter or tool that rejects or reports something. Its message MUST say what is wrong and how to do it right, including how the error could have been prevented. Messages MUST stay short (section 6.6).
- QBC-13. Every choice MUST follow a named industry standard or best practice and MUST reuse OSS or existing code before new code is written. Every limit and trigger list in this spec is a default with an override in the plugin's project-local `.brick-harness/` folder (§0 P8), never a constant. This covers at least:
  - the work-in-progress limit (default 5 agents);
  - the packet cap (default 1,600 tokens) and message cap (default 300 characters);
  - the model per role;
  - the tier triggers;
  - a project's conventions (owner tags, database roles, build recipes).
- QBC-14. Only what a measured need asks for SHOULD be built. Costs SHOULD stay low, the design clear, and room to extend.

## 4. Terms

| Term | Meaning |
|---|---|
| Orchestrator | Whoever launches agents and writes their briefs: today the main Claude session, or a human lead. |
| Builder | The agent (or person) that writes the code for one work item. |
| Work packet | The written input a builder starts from: goal, constraints, declared paths and acceptance criteria. Written by the planner or orchestrator, never by the builder. |
| Measurer | A deterministic script, not an agent, that runs the build, tests and targets and alone says whether an item is "met". In the plugin it is `bh-measure`. |
| agent-compliance plugin / harness | The reusable Claude Code plugin. Its harness has a planner, work packets, builders in their own `git clone --shared` copies of the local base commit (§0 R2), the measurer, and a safeguard register (`safeguards.json`, SG-01 to SG-19). |
| SG-01, SG-02 | Plugin safeguards. SG-01 overlays protected paths (such as acceptance tests) so the builder's edits to them have no effect. SG-02 records a fact when a diff touches paths outside its item. |
| Owner tag | A declaration on every API operation naming its owning module. A command prints the owner, package, database roles and operations, generated from the contracts. |
| Fitness function | A build test that checks an architecture property declared once, such as "every served object's database owner equals its declared owner". |
| Ratchet / baseline | A new check starts by accepting today's known findings, recorded as a list. The list may only shrink. |
| Parity test | Planted violations that both the old check and its replacement must catch before the old check is removed. |
| Mechanism kinds | Every agent-side safeguard is one of: structure (the wrong thing can't happen), fact (recorded, never refused), order (steps run in sequence), limit (rounds or size capped). |

- QBC-15. SG-01 and SG-02, as built in plugin 1.5.2, do not hold: a builder can delete the protected tests, nothing is protected by default, and the measurer's facts reach no one (review K1, K5). Every counter in this spec that cites them MUST be treated as holding only after those fixes, proven by a planted tampering test.

Standards behind the design: fitness functions (Ford, Parsons and Kua, Building Evolutionary Architectures); make illegal states unrepresentable and least privilege (NIST SP 800-53 AC-6); ATDD and acceptance criteria; mission command (commander's intent); Nygard ADRs for epics only; context engineering (minimal context delivered just in time).

## 5. Plane 1: the build

Any author, zero tokens. The test entry point (unit, lint, layout) is one entry point for humans and agents. The verify entry point runs the stack checks: acceptance and contracts. CI may run both, but nothing depends on it (§0 P12).

- QBC-16. There MUST be one test entry point and one verify entry point, used by humans and agents alike, and by CI wherever it exists.
- QBC-17. Withdrawn (§0 P12): nothing depends on CI. CI MAY run the same entry points.

### 5.1 The ladder: the first rung that fits wins

- QBC-18. A rule MUST be placed on the first rung of this ladder that fits:
  1. Structure. Privileges, schemas, package exports, separate deployables, types, generated clients. The wrong thing can't be built. This rung includes paved-road generators (as Backstage templates, Nx or Rails generators do): for example a generator that puts a new read in the owner's package with the right role, grants and contract entry. They are added later, once repeated shapes are seen.
  2. A fitness function derived from declared data: the owner map from owner tags, contracts, the role table, the policy registry. Nobody maintains a pattern list.
  3. A rule in a maintained linter, configured rather than written (for example ruff, oxlint, sqlfluff, TypeScript strict, import-linter).
  4. A unit or acceptance test.
  5. Design-time judgement, handled in Plane 2.

### 5.2 Defect classes and their mechanisms

Counts are approximate commit mentions in the pilot project. A candidate replacement MUST NOT remove the old check until it passes a parity test with planted violations (QBC-8).

- QBC-19. Each defect class below MUST have the stated mechanism, on the stated rung, with the stated ratchet.

| Defect class | Pilot count | Mechanism (rung) | Candidate replacement / limits found | Ratchet |
|---|---|---|---|---|
| Fresh-stack and rerun failures (largest class) | ~42 | 4: acceptance on a fresh stack, run twice. Runs at L5 for items tiered on compose, recipes, schema, roles or bring-up; the rest run on a warm stack | none | none |
| Role or grant mistakes | ~37 | 2: actual grants from the database catalog diffed against the specified role table, parsed rather than pattern-matched | Could replace parts of the 12 regexes in the login test | none |
| Ownership breach | ~17 | 1: database roles and the migrator wall (done). 2: each object's database owner equals its declared owner (done). 2: import boundaries per owner, generated from the owner map | Import-linter needs each module to declare a published and an internal part, which nothing declares today. Applies forward: a module declares its interface when next touched, if a check needs it | Generated ignore-imports list, which only shrinks |
| Duplicate implementation of an owner's rule | n/a | 5: judgement; structure can't see two pieces of code that mean the same rule. At L2 the packet carries the touched owner's published interface, so the builder extends it rather than copying | none | none |
| Time zones and naive datetimes | ~18 | 3: ruff DTZ; 2: a time-lint fitness check (exists) | none | per-file-ignores |
| Secrets and credentials | ~16 | 3: ruff S105 to S108; 2: parse the realm and compose configuration | The regex checks for identity and vault configuration, when next touched | per-file-ignores |
| Business constants | 12-30 | 3: ruff PLR2004; 2: policy literals checked against the registry | PLR2004 flags magic values in comparisons only, not env reads or defaults, so the hardcoded-values check (14 regexes) stays for those | per-file-ignores |
| Polling or sleep | 9-16 | 3: ruff TID251 banned-api; oxlint no-restricted-globals | TID251 bans by name: it can't tell sleep(0) apart or see a `.fetch(` method on any object. Parity unproven | The 3 allowed paths become per-file-ignores |
| Unbounded reads and performance | ~10 | 3: sqlfluff AM04 plus a small rule set; 4: measured-budget tests | none | .sqlfluffignore; new files pass |
| Money and units | 5-11 | 1: Decimal types; 2: the UN/CEFACT Rec 20 unit list pinned as data | none | none |
| Weakened tests | ~4 | 1: protected acceptance paths written by a non-builder (L3); 2: hash-pinned gate tests | The "never edit the gate tests" prose | Pin today's hashes |
| Loose TypeScript | n/a | 3: `strict: true` | none | A strict tsconfig include list that only grows |

### 5.3 Wiring fixes the inventory found

- QBC-20. Every check that exists MUST run in some recipe of the test or verify entry point. In the pilot, three layout checks ran in no recipe.
- QBC-21. Every linter configuration present in the repository MUST be run by the build. In the pilot, ruff ran only on the hooks tree; the configurations for other trees were never run.
- QBC-22. The contract, demo-contract and web test targets MUST be part of the test or verify entry point (in the pilot they were outside it).
- QBC-23. Each existing regex check MUST be replaced only after a configured linter or derived check passes parity, or when its file is next touched. There MUST be no sweep.

## 6. Plane 2: agent guidance

Order and just-in-time context only. Order comes from the flow, not from refusals.

- QBC-24. A builder MUST be launched only with an approved work packet as input. That launch order is what puts design before code.
- QBC-25. The orchestrator MUST decide the tier (epic, design-affecting or mechanical) from facts at launch: does the work touch a contract, a schema, roles or grants, compose, a major-version pin change, or an architecture-target budget? The builder MUST NOT decide the tier, or whether a rule applies to it.
- QBC-26. Approval: the owner MUST approve an epic's decision record (L1); the orchestrator MUST approve a design-affecting packet (L2); a mechanical packet needs no approval beyond the tier fact.

### 6.1 Levels per tier

| Tier | Trigger | Levels run | Agents | Tokens per item |
|---|---|---|---|---|
| Mechanical | Renames, patch or minor pin bumps (SemVer), docs, a bug fix inside one owner with no change to a contract, schema, role, compose file or budget | L4, then L5 | 1 builder (haiku or sonnet) | to be measured (R11) |
| Design-affecting | Touches a contract, schema, roles or grants, compose, a major-version pin change, or an architecture-target budget | L2, L3, L4, L5 | Planner, test author and builder (sonnet) | to be measured (R11) |
| Epic | A new capability or owner | L1 first, then each slice as design-affecting | Plus 1 design agent (opus) and the owner | to be measured (R11), plus slices |

- QBC-27. The tiers, triggers and levels run MUST be as in the table. The triggers are a plugin default, started narrow and widened where scope facts show slippage (QBC-13).
- QBC-28. The new flow costs more up front than one builder plus review loops, so it only pays if change-failure rate and lead time improve at an acceptable tokens-per-met-slice. This MUST be measured against the pre-v2 baseline (§0 R11, QBC-3).

Tiering is a prediction, because the diff doesn't exist at launch. Two facts correct it, and neither refuses anything:

- QBC-29. H2 MUST tell the builder, the first time it touches a path outside the packet, which owner that path belongs to.
- QBC-30. The measurer MUST record the scope fact (plugin SG-02), and the orchestrator re-tiers or re-plans.

| Level | What | Who | Kind | Gaming route and counter |
|---|---|---|---|---|
| L1 Epic design | vetted-decision writes one decision record, at most 2 pages, which the owner approves. Its constraints become Plane 1 checks and slice acceptance criteria. No ADR per issue | opus + owner | order | A record written to fit a preferred build. Counter: vetted-decision judges every option against the catalog, and the owner approves |
| L2 Plan | The work packet: goal; constraints (cited decision lines, the touched owners' rows and published interfaces); declared paths; acceptance criteria. No design beyond L1 | planner (plugin harness-planner / bh-brief) | structure, limit | A design slipped into the packet as steps. Counter: the packet has no design field, and it cites L1 rather than restating it. Capped at 1,600 tokens (`sizing.packet_tokens`) |
| L3 Tests first (ATDD) | A test author who is not the builder writes acceptance tests from the packet and contract into protected paths. The measurer records whether they fail on main | test author (sonnet) | structure, fact | Vacuous tests: the red-on-main fact and pinned hashes |
| L4 Build | A mission-command brief: the packet plus the failing tests. The builder designs freely within the constraints | builder | order | The builder edits the tests until they pass. Counter: the tests sit in protected paths (SG-01), and the measurer runs the protected copy |
| L5 Verify | The deterministic measurer runs the test entry point, the item's tests and targets, and the verify entry point on a fresh stack for the triggering tiers. Only it says "met". A miss returns the missed numbers for a retry within the round limit | measurer (no agent) | fact, limit | Endless retries: the round limit. A lucky pass on a flaky test: the measurer records the flaky fact |
| Review | Only for diffs touching auth, keys, grants, money or signatures, plus a duplication check on design-affecting items | sonnet or opus | order | A diff split to dodge the triggers. Counter: triggers are judged on the item's whole diff |

- QBC-31. Each level MUST do what its row says, with the stated kind, and the stated counter MUST be implemented for the stated gaming route.
- QBC-32. A decision record (L1) MUST be at most 2 pages by default (QBC-13) and MUST NOT be written per issue.
- QBC-33. The packet MUST have no design field and MUST cite L1 decisions rather than restate them. The packet MUST be capped at 1,600 tokens by default, overridable in `.brick-harness/` (QBC-13).
- QBC-34. The test author MUST NOT be the builder. The measurer MUST record whether the acceptance tests fail on main.
- QBC-35. Only the measurer MAY say an item is "met".
- QBC-36. A review step MUST run for diffs touching auth, keys, grants, money or signatures, and a duplication check MUST run on design-affecting items. Triggers MUST be judged on the item's whole diff.

### 6.2 Orchestrator briefs

This guidance is for whoever launches an agent, human or Claude. The brief is the builder's only context besides the repo, so its shape decides whether the design step happens at all. If a brief pre-chooses the design, the decision step has nothing to decide, and the builder reasonably treats the design as settled and goes straight to code.

- QBC-37. A brief MUST state the goal and the constraints, not a pre-chosen design.
- QBC-38. A brief MUST contain:

| Part | What goes in it | Source |
|---|---|---|
| Goal | The outcome in user terms, and why it matters. One or two sentences | the issue |
| Tier | Mechanical, design-affecting or epic slice, with the fact that set it | the orchestrator, from the tier triggers |
| Constraints | The decision lines that bind the work, cited rather than restated. The owners touched and their published interfaces. Budgets and targets. What must not change | the owners command, the decision records, the architecture targets |
| Acceptance | The path of the failing acceptance tests written by another agent (L3), plus measurable targets. "Done" means the measurer says met | the test author, the targets |
| Environment | Only the context modules the task needs (for example a VM module when it runs a stack) | the orchestrator |

- QBC-39. A brief MUST NOT contain: a pre-chosen design (no "do X, then Y", no chosen mechanism, no file-by-file instructions; if the design was decided at L1, cite it); the project's agent rules file repeated (the builder already loads it); or claims taken from another agent's report without a fact check (for example, ownership is checked in the database catalog, not taken from a self-written "held").
- QBC-40. Exception: a mechanical item (a rename, a patch or minor pin bump, a wording fix) has no design to decide, so its brief MAY name the exact edit.
- QBC-41. Design-level work MUST start with a design agent that produces a decision record (L1 for an epic, or the planner's packet at L2). A build agent then takes that record as input. One agent MUST NOT both design and build.
- QBC-42. The packet MUST stay within its cap. What doesn't fit is either not needed or belongs in a cited document.

### 6.3 Hooks: order and just-in-time context

- QBC-43. Hooks MUST do two jobs only: enforce order (silent unless something is out of order) and give small, just-in-time context, capped in size and sent once.
- QBC-44. Hooks MUST NOT match code patterns. Any check a hook runs MUST be a check the human's build runs too.
- QBC-45. Hooks MUST ship in the plugin's `hooks/hooks.json`, because plugin subagents ignore hooks in their frontmatter. Data MUST come from project build recipes, so there are no pattern lists.

H0, PreToolUse (Edit/Write), first code edit without a packet. Kind: order.

- QBC-46. H0 MUST refuse a builder's edit, with a message that teaches, until a packet exists. It fires only when the flow was bypassed (for example a launch by hand) and costs no context otherwise. For a mechanical item the orchestrator writes a minimal packet (tier, goal, paths).
- QBC-47. H0 messages: to the builder, "No work packet for this clone. Builders start from a packet the orchestrator writes (goal, tier, constraints, tests). Stop and ask to be relaunched with one." To the orchestrator, "Builder <id> started without a packet. Launch builders through <launch step>, which writes the packet first; mechanical work gets a minimal one."
- QBC-48. A path whose refusal must teach MUST have no permission deny rule, because deny rules run before hooks and silence them; the teaching refusal comes from a hook (§0 P5, R4). The packet MUST live in a protected path (SG-01), so only the orchestrator or planner can create it. (Why it refuses: a note alone would let the builder carry on, which is how gaming starts.)

H1, session start. Kind: limit on size.

- QBC-49. H1 MUST deliver the packet at session start (§0 R5), not on SubagentStart (withdrawn: R5): the packet's goal and constraints, the owner rows for its paths, the visible tests, the rules with their teaching messages, the ratchet baselines and the `bh check` command, within the packet cap (QBC-13). It MUST only inform and refuse nothing.

H2, PreToolUse (Edit/Write). Kind: fact.

- QBC-50. On the first touch of a path outside the packet, H2 MUST show one line that teaches (about 200 characters by default, once per path, QBC-13), for example: "apps/x/y.py belongs to owner Y, outside your packet. Call Y's published interface, or ask the orchestrator to widen the packet." It MUST record the fact for the orchestrator and MUST NOT block.

End of build, measurer retry, no hook.

- QBC-51. When a builder finishes, the measurer MUST run the same checks a human's build runs: layout, lint, generated-code freshness, unit tests, and the item's acceptance tests. A miss MUST go back to the builder with the checks' own messages and the missed numbers, for another round within the round limit (kind: fact, limit). This replaces a blocking SubagentStop hook, which would refuse and whose worktree target is undocumented.
- QBC-52. Withdrawn (§0 P12): CI is not a backstop the design relies on. The measurer's checks (QBC-51) are the last line.

### 6.4 Messages: every rejection teaches

This contract covers every message from both planes: build checks, fitness functions, linters, hooks, and the measurer's retry.

- QBC-53. Shape: `[rule] what is wrong -> the right way, and how to prevent it next time . ref`. Where this spec quotes a message (QBC-47, QBC-50, QBC-88), the quoted sentences fill the wrong and right parts of this shape, and a check matches each quoted sentence on its own.
- QBC-54. A message MUST name the right way concretely (a command, an API, a file or a published operation), never only "don't". For example: `[policy] 30 is a business value in plan.py:88 -> read it with policy.resolve('plan.window_days'); new values go in policy.sql . ref`.
- QBC-55. A message MUST be at most about 300 characters per finding by default. Repeats MUST be grouped: the first 10 by default are shown, then a count. Both are defaults with overrides (QBC-13). The measurer's retry MUST send only the missed checks' messages.
- QBC-56. Every project check, fitness function and hook MUST report through one helper whose arguments are all required, `teach(rule, wrong, right, ref)`, so a bare rejection can't be written (kind: structure).
- QBC-57. Third-party linters MUST use each tool's own custom-message field where it has one: ruff banned-api msg, oxlint and ESLint no-restricted-* message, import-linter contract names. A rule with a fixed message (for example ruff PLR2004) MUST get a one-line "right way" keyed by its rule code, only for rules that are enabled.

### 6.5 Every agent-side mechanism, with its kind and gaming route

These are the mechanisms outside the levels table above.

| Mechanism | Kind | Gaming route | Counter |
|---|---|---|---|
| Tier set by the orchestrator from facts at launch | order | Under-tiering to save tokens, which skips the design step | H2 and the measurer's scope fact (SG-02) show a diff that reached tier-triggering paths, and the item is re-planned |
| A builder is launched only with an approved packet | order | A launch outside the flow | H0 refuses the first edit with a teaching message to both builder and orchestrator |
| Orchestrator brief template (goal, tier, constraints, acceptance; no design field) | structure | Steps written into the goal | Nothing mechanical. The brief is kept with the item, so the owner can read it |
| H0: no edit without a packet | order | The builder writes its own packet | The packet sits in a protected path (SG-01) |
| H1 context at start | limit | None: it only informs | none |
| H2 outside-the-packet note | fact | None: it refuses nothing | none |
| Measurer retry with missed numbers, and with the critical or major findings of the triggered review (before the merge) | fact, limit | Editing tests; endless retries; a diff split to dodge the review triggers | Protected tests (SG-01); the round limit; triggers judged on the item's whole diff by the program |

- QBC-58. Each mechanism MUST have the kind and counter listed. A new agent-side mechanism MUST be added to this table with its kind and gaming route.
- QBC-59. The project's agent rules file SHOULD shrink to judgement: cite a standard; adopted tool first; measure before optimising; search before adding. At L2 these become packet constraints.

### 6.6 Rule selection: who decides which rules apply, and how

Industry practice adopted: static analysers turn rule packs on by the languages and frameworks they detect (Semgrep, CodeQL), and ISTQB risk-based testing picks checks from what a change touches. So facts decide, never an agent's judgment, and each measured miss corrects the mapping. Every catalog rule is kept: v1's rows are all present, with `embodied_by` naming the mechanism for a row a v2 mechanism enforces. Each rule is explained from the repo itself (`text`, `why`, `right`, `question`, with `cites` as a provenance label only).

- QBC-103. Core and tags. A small core tagged `always` (at most 10 rules) MUST apply to every item. Every other rule MUST carry `applies` tags from one closed set: messaging, network-client, http-server, database, auth, deploy, concurrency, money, time, config, dependency-change, defect. A tag outside the set MUST be refused as a catalog error.
- QBC-104. Facts decide, at 0 tokens. The program MUST derive an item's tags with no agent, from three sources: (a) the project stack (lock-file dependencies through a capability table, plus the project's `stack` declarations in config); (b) the item's contract (declared interfaces and owned paths); (c) the actual diff (imports added, file kinds). The packet MUST carry core + (a) + (b). The same inputs MUST give the same selection. Inclusion leans toward recall: a false inclusion costs one line, a false exclusion costs a defect. Recall is measured by QBC-108, not asserted in a unit test.
- QBC-105. Nobody is left without a rule.
  - (i) `bh rules --diff [BASE [REF]]` MUST print, at 0 tokens, the rules the change's facts (c) add. The packet MUST name it as the builder's self-check.
  - (ii) The review MUST judge the packet's rules plus the rules (c) adds on the item's actual diff.
  - (iii) `bh rule <id>` MUST print a rule's full text from the repo.
  - (iv) A rule is never dropped for size. The first `limits.packet_rules` rules (default 15, with an override in config) are full lines; any beyond that are listed by id and title only, for `bh rule <id>`.
- QBC-106. Agents add, owners remove. The planner MAY add rules to an item, each with a one-line reason, and MUST NOT remove any. Only the project's overlay MAY remove a rule, and only with a reason. No agent's input MAY hold the whole catalog.
- QBC-107. Same rules for every author (G2). `bh review BASE..HEAD [--item X]` MUST judge any author's diff and MUST be the one review entry point for humans and agents (QBC-16). The rules it judges are fixed by QBC-104 and QBC-105: with `--item`, that item's selection plus (c); without, core + (a) + (c).
- QBC-108. Misses are measured and corrected.
  - A finding, or a later defect, whose rule was not selected MUST be recorded as a fact `selector_miss {rule, missing_tag}` in the run result.
  - `bh run` MUST report each miss in teach form, naming the capability-table or `applies` entry that would have selected the rule, and `bh metrics` MUST count misses per run. The mapping is fixed from these facts (a ratchet).
  - Release acceptance: on a held-out replay of real history, the covering rule is selected in at least 90% of cases, and the median packet is at most 15 rule lines.
- QBC-110. No rule lost. Every rule id of the v1 base catalog (vendored as a fixture list) MUST be present in `catalog/rules.toml`. A rule that a v2 mechanism enforces keeps its text and names that mechanism in `embodied_by`.
- QBC-111. Explained in the repo. Every rule MUST have non-empty `text`, `why`, `right` and `question` in the plugin's own words. `cites` is a provenance label only, and no rule's explanation MAY be only a URL. Every `[standards.*]` entry MUST have a `summary`.
- QBC-109. Release check, requirements traceability (ISO/IEC/IEEE 29148).
  - Each of QBC-103 to QBC-108, QBC-110 and QBC-111 MUST have a plain pytest in `harness/tests` named for its id.
  - Each such test MUST include a negative control: the same assertion run on an input that breaks the property, which MUST fail. A test that cannot fail does not count.
  - One traceability test MUST read the ids in this section and assert that a test is named for each.
  - The full harness pytest is the release bar.

## 7. A self-sustained plugin

Convention over configuration. The plugin runs on day one with nothing added, and gets smarter from files a well-run project already has. It runs with presets on any repo, infers what it can, asks for the rest once, and stores answers only in standard files.

- QBC-60. The plugin MUST work in any project without plugin-specific scaffolding, and a project MUST be able to use it without setup. One capability MUST NOT be split into a plugin part and a project part.
- QBC-61. The plugin MUST be B + C + D below: infer from standard files, ship presets, ask once into a standard file.
- QBC-62. The generic checks of Plane 1 MUST ship in the plugin, filled in with inferred facts: one owner per object, each database object's owner equals its declared owner, grants match the declared roles, no polling, no naive datetimes, linter presets. The owners lookup MUST be provided by the plugin, not by a project recipe. A project supplies only standard files it already has (for example OpenAPI owner tags, database roles and the build recipe file).
- QBC-63. The plugin MUST NOT write its own scaffolding into a repo (option E) and MUST NOT require a plugin config file (option A).

| Option | How it works | Pros | Cons |
|---|---|---|---|
| A. A project config file | The project declares its test command, owners and paths in `.agent-compliance.yaml` | Simple and explicit | Plugin-specific scaffolding, rejected |
| B. Infer from standard files (convention over configuration, as buildpacks and starter workflows detect a project) | Test entry from justfile, Makefile, package.json or pyproject; stack from lockfiles; owners from CODEOWNERS and OpenAPI tags; ownership facts from the database catalog | No scaffolding when the project follows common practice; the files are useful without the plugin | Detectors per ecosystem to maintain; a project without such files gets fewer checks |
| C. Built-in presets (like shareable ESLint, ruff or tsconfig configs) | The plugin ships linter presets and pinned checkers and runs them itself | Works on any repo in a supported stack from the first run | Can't know project-only rules, such as a policy registry |
| D. Ask once, write a standard file | For a fact it can't infer, the plugin asks once and records the answer in a standard file (CODEOWNERS, an OpenAPI tag), never in a plugin file | No hand scaffolding; the result is useful without the plugin | Writes into the project, so each write needs approval; the first run costs more |
| E. The plugin writes its own scaffolding | An init step generates plugin config into the repo | Quick | The files drift as the plugin changes (create-react-app's "eject" problem) |

Recommended and decided: B + C + D.

## 8. Plugin review: what can be used

- QBC-64. Nothing in the existing plugin MUST be used before a critical review. Two read-only reviews were made on 2026-11-25:
  - Harness runtime (release 1.5.2): 8 Critical, 14 Major and 13 Minor findings, with 27 theoretical minors discarded. Its 297 tests pass, but they don't prove the claims (`evidence/review-harness.md`).
  - Skills, catalog, checks and evals: 2 Critical and 7 Major findings (`evidence/review-skills.md`).

Findings that decide what can be used:

- QBC-65. The anti-gaming protection is bypassable (Critical): a builder can delete the acceptance tests, after which measurement silently skips them. Nothing is protected by default, so a stub test with wrong code measured "met". Fix: tests laid over the build by the measurer (R4, K5) and a `--shared` clone (R2, K1).
- QBC-66. The measurer isn't fail-closed (Critical): it crashes on some inputs; two measurements can share an output folder, so a failing ref gets recorded as met; the guard that keeps failing work out of HEAD is untested. Fix: K6, K7, K8.
- QBC-67. The safeguard register's test proves nothing (Critical): it passed with a fake entry and an unrelated test listed as proof. Fix: K3.
- QBC-68. Gates by accident (Critical and Major): the rules check can never run on macOS or arm, so every item stays unmet (K2); the commit gate on targets stalls every build. These MUST become facts with teaching messages.
- QBC-69. "Reviews converge" isn't supported (Critical): three models gave three different verdicts on the same artifact, and the skills grade their own work (one agent proposes and judges). Decisions MUST be judged by a fresh agent.
- QBC-70. The vetting rule is biased against OSS (Major): an option fails if any rule is unverified, so keeping your own code wins by default. It MUST be replaced (section 9, slice f).
- QBC-71. Token cost (Major): a skill loads about 10k to 42k tokens before reading any evidence; on the test projects the plugin cost 2 to 4.7 times a run without it. Skill descriptions and loads MUST be trimmed.
- QBC-72. The catalog is mostly one earlier project's conventions (Major): 192 of 332 rules cite only "Convention". It MUST be replaced by references to maintained standards plus a short list of house rules.
- QBC-73. The checks are hand-written patterns (Major); ruff and ESLint rules cover most of them. They MUST be replaced by linter configurations.
- QBC-74. The evals grade wording, not outcomes or cost. They MUST be rebuilt.
- QBC-75. Fit for the flow: no tests-first step, no tiers, decisions never become work, and issue intake drops the issue body. These MUST be added or fixed.
- QBC-76. Size: still 8.9k lines, of which 6.9k are code; 9 of the 12 bh-* scripts are unused, and a "standard library only" rule keeps hand-written replacements for jsonschema and other OSS tools. These MUST be deleted or replaced.

Verdict per component:

| Component | Verdict | Effort |
|---|---|---|
| Orchestrator bh, set_branch, value order, bh-answer, history | Keep. The shape is right: one program runs the mechanical steps, agents do only judgement, the measurer alone decides | none |
| Measurer, protected paths, merge, safeguard register and its test | Fix the Critical findings first | M-L |
| 9 unused bh-* scripts; old workflows | Delete | S |
| Hand-written schema validator, downloader, bh-init, gaps.md renderer | Replace with jsonschema, ast-grep from PATH, inference and a template | S-M |
| compliance-review, compliance-catalog | Delete, after moving the shared lookup the other skills load from them | S-M |
| vetted-decision | Fix: slimmer, with a fresh agent as the judge | M |
| vet-oss | Replace with OpenSSF Scorecard, deps.dev and OSV-Scanner | M |
| bug-analysis | Fix: narrow the trigger; an issue form and commitlint | M |
| harness skill | Keep, adding the tests-first step | S |
| Catalog | Replace with references to maintained standards (OWASP ASVS, NIST, SLSA, Well-Architected) plus a short list of house rules | L |
| Pattern checks | Replace with ruff and ESLint configurations | S |
| Evals | Rebuild around outcomes and measured cost | M |

- QBC-77. Each component MUST receive its verdict, and every review verdict MUST map to one slice (section 9).

### 8.1 Order engine

- QBC-78. The order engine MUST be a program that runs the mechanical steps itself (git, tests, measuring, ordering) and launches agents only for judgement. No agent MAY be in the mechanical path. Workflow scripts MUST NOT be the order engine, because they need an agent to run the measurer.

## 9. Plugin v2 slices (a-h)

Every verdict of the two reviews maps to one slice. No old check is removed before its replacement passes a parity test (QBC-8).

- QBC-79. Slice a, Prune (Mechanical; depends on nothing). MUST: delete compliance-review and compliance-catalog after moving the shared lookup and judging method the other skills load from them; delete the 9 unused bh-* scripts and the old workflows (already gone upstream); keep template plan-dry-run and delete three others (bug-record waits for its issue form, slice e); trim skill descriptions so they don't load when not needed; fix the README and manifest claims the reviews didn't support.
- QBC-80. Slice b, Harness core (Design-affecting; depends on the isolation spike). MUST: Critical: a `--shared` clone of the local base (R2, K1); protected tests by default (K5); unique output folders (K6); a fail-closed measurer (K7); a tested merge-only-met guard (K8); a safeguard-register test that proves its claims (K3). Major: the commit and env_setup refusals become facts with teaching messages; the measurer's facts reach the orchestrator; a run lock for `bh run`; re-review can no longer close gaps by omission. Replace with OSS: the hand-written schema validator with jsonschema; the gaps.md renderer with a template. Keep: bh, set_branch, value order, bh-answer, history. Record the toy run as proof.
- QBC-81. Slice c, Convention over configuration (Design-affecting; depends on b). MUST: inference replaces bh-init; ruff, ESLint, oxlint and sqlfluff presets with teaching messages and ratchets replace the ast-grep pattern checks, after parity (which also removes the ast-grep downloader and the rules target's gate-by-platform (K2) and empty-scan pass (K4)); the plugin provides owners and the generic fitness functions.
- QBC-82. Slice d, Flow (Design-affecting; depends on b). MUST: keep the harness skill, adding the test-author step (tests written first by a non-builder); tiers, roles, packet fields (goal, tier, constraints, paths) and the brief template; hooks H0 to H2 (H1 at session start); the work-in-progress limit and the other caps as defaults with overrides.
- QBC-83. Slice e, Intake (Design-affecting; depends on d). MUST: issue forms for decision, slice and defect (bug-record becomes the defect form); a parent check with a teaching message, run by the program at intake (a GitHub Action MAY also run it, nothing depends on it); a bounded Known issues list with its limit set as policy; issue intake keeps the issue body (the review found it was lost).
- QBC-84. Slice f, Decisions and vetting (Design-affecting; depends on g). MUST: vetted-decision slimmer, with a fresh agent as the judge; vet-oss replaced by OpenSSF Scorecard, deps.dev and OSV-Scanner; bug-analysis narrowed so it no longer triggers on every failing test, with commitlint for fix commits.
- QBC-85. Slice g, Standards in place of the catalog (Design-affecting; depends on nothing). MUST: references to maintained standards (OWASP ASVS, NIST SSDF and SP 800-53, SLSA, Well-Architected) plus a short list of house rules; the packet's rule list and the measurer read from it (a dependency the reviewer flagged).
- QBC-86. Slice h, Evals (Design-affecting; depends on a to g, measured alongside). MUST rebuild evals around outcomes and measured cost: the plugin against a run without it, on the toy project.

## 10. Work intake

### 10.1 History

Moved to `docs/design/evidence/history.md`.

### 10.2 Industry practice adopted

- Decision, then tracking issue, then slices (the Rust RFC process): an accepted decision gets one tracking issue, and its work links under it.
- A hierarchy with nothing free-floating: goal, then decision or epic, then slice, then defect, using GitHub sub-issues. Tasks inside a slice are not issues.
- Definition of Ready and Definition of Done (Scrum): ready when the packet and its failing tests exist, done when the measurer says met.
- No infinite backlog (Shape Up): raw ideas aren't tracked as issues until they are shaped into a decision or slice.
- Kanban: a work-in-progress limit (default 5 agents) and classes of service: expedite for Critical defects, standard for slices.
- Defect triage by severity (ISTQB), with minors in one Known-issues list.
- Structure in the tracker itself: issue forms with required fields (parent, goal, acceptance).

### 10.3 Intake requirements

- QBC-87. Work MUST enter through this hierarchy:

| Level | What it is | Where it lives | Enters when |
|---|---|---|---|
| Goal | A scenario or outcome | A milestone | The owner sets it |
| Decision (epic) | One decision record (L1) and one tracking issue, each linking to the other | The decision record plus its tracking issue | New capability or owner |
| Slice | A ready work packet: goal, tier, constraints, acceptance | A sub-issue of the tracking issue, created through an issue form with required fields | The planner writes it (L2) |
| Defect | Critical or Major: wrong behaviour, a breach, a missed target | A sub-issue under the slice or decision it breaks | A test, the measurer, a review or an agent finds it |
| Minor with practical value | A small improvement | A checkbox in the single Known issues list, each line naming its parent decision or slice | Found anywhere; theoretical minors are discarded |

- QBC-88. No issue MAY exist without a parent. The issue form MUST require one. A parentless issue MUST get the message: "No parent decision. Every issue sits under a decision's tracking issue: pick one, or start a decision if this is a new capability."
- QBC-89. Agents file most issues through `gh issue create`, which bypasses form validation, so the parent check MUST also run on new issues, with a teaching message, in the program's intake step. A GitHub Action MAY run it too; nothing depends on it (§0 P12).
- QBC-90. The Known issues list MUST be a bounded backlog: at its limit (default 100, set as policy) items MUST be fixed and removed before new ones are added. There MUST never be a second list.
- QBC-91. A review finding MUST attach to the slice under review. It reopens that slice's checklist and MUST NOT start a new chain of issues.
- QBC-92. An agent that finds a bug during a slice MUST fix it in the slice if it is in scope; otherwise it MUST file a defect under the right parent.
- QBC-93. A tracking issue MUST close when its slices are done. A tracking issue with no slice activity MUST be reported to the owner as a fact.
- QBC-94. Intake MUST be the GitHub-native hierarchy (milestones, sub-issues, issue forms with required fields, a Projects board). Where issue types are not available (a personal repository), a label stands in. Alternatives rejected: flat issues and labels (already failed: chains, floods, stale tracking issues); work lists inside decision documents (churns documents meant to hold only the why); an external tracker (another tool, its cost, agent access).

## 11. Rollout, in value order

- QBC-95. The rollout MUST follow this order:
  1. Orchestrator briefs, from now on. Costs nothing.
  2. The plugin path (P3, section 13), built and proven on the toy project. Nothing from the existing plugin is used before its Critical findings are fixed.
  3. Intake structure (I2): milestones, tracking issues and sub-issues for new work. Existing open issues move under a parent when next touched.
  4. Adopt in the pilot project, with its first large epic as the first full run.
  5. Withdrawn (§0 P12): CI backstop. CI may exist; nothing depends on it.
  6. Paved-road generators, later, for the shapes that keep coming up.

## 12. History and traceability

Moved to `docs/design/evidence/history.md`. The spec holds requirements only.

## 13. Decisions and open items

- QBC-96. Decided (owner, 2026-11-25), D2, end of build: measurer retry; no blocking hook.
- QBC-97. Decided, P3 (owner, 2026-11-25), plugin path: assemble from host features and OSS, porting only what the host lacks (the measurer core and value order, after their Critical fixes). Order engine: a program, no agent in the mechanical path (QBC-78). This is the shape of the plugin's `bh` since the Workflow-tool path was removed on 2026-11-20.
- QBC-98. Decided, S: infer from standard files, ship presets, ask once into a standard file (B + C + D).
- QBC-99. Decided, I2: the GitHub-native hierarchy (section 10). Minors go in the single Known issues list, each line naming its parent. No issue without a parent.
- QBC-100. Open: the isolation spike on the toy project (`evidence/spike-order-engine.md`) MUST show: how the program launches agents headless, and at what cost; that a planted builder which edits the tests or writes its own packet has no effect on the measured result (§0 R4), by host-native or OSS mechanisms; that plugin hooks fire inside the launched agents, and that a teaching refusal is acted on.
- QBC-101. Open: an independent design review (`evidence/independent-review.md`). vetted-decision grades its own work (review finding), so this design MUST get a reader who didn't write it before slices are planned.
- Withdrawn: D1 (adoption) is answered by work intake. D3 (a project decision forbade lint as the enforcement; the design keeps structure as the wall, so nothing conflicts). D4 (tier triggers are a plugin default, started narrow and widened where scope facts show slippage). D5 (answered by the review: replace the pattern checks with linter configurations). D6 (applies forward, when a module is next touched and a check needs it). D7 (follows from P).
- QBC-102. New process MUST NOT reopen an old decision record it doesn't change.

Sources (all read-only, 2026-11-25): inventories of the plugin with the Claude Code hook docs, and of the pilot project's checks, rule coverage, defect classes and adherence; two critical reviews of the plugin; a work-intake history from git, the issues and the owner's prompts. Of these, the plugin inventory and the two reviews are in `docs/design/evidence/`; the pilot-only inventories are kept in the pilot project's own repository.
