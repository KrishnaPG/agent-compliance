# History and traceability

Moved out of `docs/spec/quality-by-construction.md` because the spec holds requirements only (section 0 governs). Nothing here is a requirement.

## How work entered the pilot project

From git, all 124 issues and the owner's prompts since 2026-11-20:

- Decisions came first. On the first day there were decisions and specs only, with no issues. The first issue (a tracker) appeared on day 2.
- The tracker exploded on day 4: 85 issues were created that day, 69% of all issues so far, and issue-queue mode started that afternoon.
- Only 43 of 124 issues follow up a decision or spec. 56% came from checking agent work: 25 test or gate failures, 20 minors, 12 review findings and 12 bugs agents found during other work.
- Links are missing. 57% of issues cite no decision or spec. 56% cite another issue instead, in chains up to five deep. No decision lists its issues. There are no milestones or sub-issues, and the tracking issues had been stale for days.
- What churned: 34 minor issues filed in 3 hours and then reversed; 10 of the 16 reopened issues came from compliance-review sweeps.
- What worked: batches tied to one decision closed cleanly and weren't reopened.


## Design history: earlier proposals and where they went

| Earlier proposal | Where it is now | Changed? |
|---|---|---|
| Hooks only enforce order, are silent unless they block, and run the same checks as a human's build | Order comes from the flow; H0 is silent unless the flow was bypassed, and then refuses with a teaching message; H1 and H2 add small capped context, asked for as just-in-time context | Capped context added |
| A note that only says "this is wrong" is how gaming starts; every rejection must teach | QBC-12; section 6.4; H0 and H2 texts | New |
| Decision before the first code edit: refuse until a decision record or a "mechanical" exemption exists | Superseded by the next row | Yes |
| Correction: that hook let the agent decide whether the rule applied to it (self-grading) and was close to a gate. Order comes from the flow: a builder is only launched with an approved packet | Section 6 banner; the mechanisms table; H0 records a bypass as a fact | No |
| The tier is decided from facts by the orchestrator at launch, never by the builder | Section 6; levels per tier; tier triggers | No |
| Every agent-side mechanism is labelled structure, fact, order or limit, with how it could be gamed | Levels table; mechanisms table; each hook | No |
| The generic process (levels, packets, hooks, briefs) in the plugin, the fitness functions in the project repo | Superseded by a self-sustained plugin: everything ships in the plugin, and a project supplies only standard files | Yes |
| No "done" until the build is green: a hook runs the fast checks when the agent tries to finish | End of build: the measurer runs the same checks and returns misses for a retry | Yes: no refusal |
| CI stays the backstop | Section 5; rollout step 5 | No |
| No pattern hooks; a pattern worth catching becomes structure, a fitness function or a configured linter rule | QBC-5; the ladder | No |
| Briefs: goal, constraints, acceptance tests from another agent, no pre-chosen design; design work starts with a design agent | Section 6.2; L1 to L3 | No |
| Fitness functions generated from the owner map and contracts | Ownership row; QBC-7 | No |
| Paved-road generators, later | Ladder rung 1; rollout step 6 | No |
| The plugin must be self-sustained; no plugin part plus project part | Section 7; QBC-10 | Yes |
| Critically review all existing plugin skills, workflows and harness scripts before use | Section 8 | New |
| Work entered as decisions first, then their issues; the tracker became a dumping place | Section 10 | New |
| Don't raise decisions about old decision-record wording that new work doesn't need to change | Process lives in the plugin's own documents; new process never reopens an old decision record it doesn't change | Yes |
