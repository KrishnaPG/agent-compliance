# Base catalog changes

Current base version 1.5.2. One line per added or changed rule id; the git tag of each release holds its own state, so a reader finds what changed since a recorded version with `git diff <tag> -- catalog`.

- initial base.
- DS-07 defines a clean (generated, run-scoped state, no confirmation) and covers scheduled jobs; every seed, migrate, clean or reset still prints its target.
- DS-08 covers every destructive automation, each named with its limit.
- ID-09 states its NA condition (no inbound surface).
- ID-05, ID-07, ID-10, ID-14, CI-05, CI-07, CI-08 test questions ask for the concrete failing input or location, with the NA condition where one exists.
- index.md readings: an absence is BROKEN only when the rule requires the artifact to state it.
- PF-12 and scenario 2: no "no-change release" (a commit already released does not start a release; a release runs only the stages its commit changed, each skip on the owner's recorded state).
- ID-15 added: authentication, signature and authorization checks run once, where material enters the trust boundary; blocks behind it act on the verified result.
- HO-40 added: a non-durable wake-up signal (e.g. LISTEN/NOTIFY) is only a hint; the consumer drains the durable backlog on start, restart and reconnection.
- CI-14 added: every row, event and message carries its placement key (tenant, cell or shard) where data is placed by one.
- NO-28 added: a generic capability is its own package with a documented interface, data configuration, standalone tests, acceptance tests, benchmark and README, and imports no product code.
- NO-29 added: stack-shaping choices are decided once, centrally, before dependent components; later choices prefer the chosen or compatible stack.
- scenarios 5, 11, 16, 26, 28, 30, 31, 37, 38, 39, 46, 52, 56, 57, 60, 61 and 63 list the new rules that decide them.
- `checks/` added: static check packs (ast-grep, pinned in `checks/index.json`) for RL-08 and LC-17, HO-02 and ID-15 in Python and TypeScript, indexed by `checks/index.json`.
- overlay check opt-outs: one line per rule under `## Check opt-outs`, exactly `- <RULE-ID> not-applicable: <reason>`; a line without a reason opts nothing out.
- pack `agent-jobs` (AJ) added for designs that start AI agent jobs.
- AJ-01 added: work a program or adopted tool can do runs as code; an agent job is started only for judgement and returns its result to the program.
- AJ-02 added: an agent job loads only the instructions, tools and files it uses; judged from its start record.
- AJ-03 added: a job kind's model, effort, tools, turn limit and instructions live in the host's agent definition, never in program code; the program sets only the spend cap.
- AJ-04 added: jobs of one kind share a byte-identical prompt prefix with job-specific data last; cache reads are measured.
- AJ-05 added: every agent job has a host-enforced turn limit and a spend cap besides its deadline; the CLI's spend cap is a backstop, PF-14 governs metered budgets.
- AJ-06 added: an agent result a program consumes is schema-checked structured data; free text is never parsed.
- AJ-07 added: a loop of agent rounds has a round bound and stops, reported as without a result, when a round moved no measured number.
- PR-14 added: owner questions from unattended runs, agent jobs included, are batched per run, recorded with their answers and never asked again while their inputs hold.
- scenarios 64 (a program starts AI agent jobs) and 65 (a loop of agent rounds repeats) added; index term "Agent job".
- termination tiers (T0 irreversible or liability, T1 costly but capped, T2 harmless) defined in `base/LC.md` beside the L0-L6 levels; index terms "Termination tier", "Recovery tier", "Life site, death site".
- LC-39 added: every termination effect declares its termination tier, its bound ("at the action" for T0; a number for T1 and T2, with the spend cap for T1) and the native mechanism that meets it.
- LC-40 added: a T0 effect is checked at the action against the owner's current state and runs after every reversible step and refusal; an uncheckable one is a named, measured gap.
- LC-41 added: T1 and T2 bounds are met by a native mechanism paid per change, never a timer of ours or a shortened cache or token lifetime; each bound is measured and alerted.
- LC-42 added: ending a membership, affiliation, seat, grant or tenant ends access only; the person's account, links, authorship and history stay, and data follows the organisation's policy and retention; the person is removed only on their own erasure request (DS-15) or a guarded exception the overlay names.
- LC-43 added: a life site names its level and a death site its termination tier, mechanism and what it keeps, as a one-line comment of rule ids at the site.
- ID-05 changed: a person's own account is not a duty account; the end of one membership ends its access, never the account (LC-42).
- ID-03 changed: a person's own account is excepted from the removal path at a duty's end (LC-42).
- scenarios 9, 11, 20 and 39 list the new rules that decide them; scenarios 66 (a member leaves, or a seat, grant or membership ends) and 67 (a change adds or alters a termination) added.
- LC-41 changed: the last preference is ending running work by the owner's own end of the object that owns it (one stop, shutdown, cancel or delete, whose cascade ends the children; one call for one named child); never listing an owner's children to end each, never ending a parent whose cascade reaches retained data; the test question asks whether any step enumerates an owner's children.
- scenarios 66 and 67 list NO-01, NO-06 and NO-09 (67 also RL-24), so the review skill's Scope step takes the NO domain from them; the scenario index rows 66 and 67 add NO.
