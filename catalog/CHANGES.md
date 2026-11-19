# Base catalog changes

- 1.0.0: initial base.
- 1.1.0: DS-07 defines a clean (generated, run-scoped state, no confirmation) and covers scheduled jobs; every seed, migrate, clean or reset still prints its target.
- 1.1.0: DS-08 covers every destructive automation, each named with its limit.
- 1.1.0: ID-09 states its NA condition (no inbound surface).
- 1.1.0: ID-05, ID-07, ID-10, ID-14, CI-05, CI-07, CI-08 test questions ask for the concrete failing input or location, with the NA condition where one exists.
- 1.1.0: index.md readings: an absence is BROKEN only when the rule requires the artifact to state it.
- 1.2.0: PF-12 and scenario 2: no "no-change release" (a commit already released does not start a release; a release runs only the stages its commit changed, each skip on the owner's recorded state).
- 1.3.0: ID-15 added: authentication, signature and authorization checks run once, where material enters the trust boundary; blocks behind it act on the verified result.
- 1.3.0: HO-40 added: a non-durable wake-up signal (e.g. LISTEN/NOTIFY) is only a hint; the consumer drains the durable backlog on start, restart and reconnection.
- 1.3.0: CI-14 added: every row, event and message carries its placement key (tenant, cell or shard) where data is placed by one.
- 1.3.0: NO-28 added: a generic capability is its own package with a documented interface, data configuration, standalone tests, acceptance tests, benchmark and README, and imports no product code.
- 1.3.0: NO-29 added: stack-shaping choices are decided once, centrally, before dependent components; later choices prefer the chosen or compatible stack.
- 1.3.0: scenarios 16, 28, 30, 31, 39, 46, 52, 60, 61 and 63 list the new rules that decide them.
- 1.3.0: `checks/` added: static check packs (ast-grep 0.51.3) for RL-08 and LC-17, HO-02 and ID-15 in Python and TypeScript, indexed by `checks/index.json`.
