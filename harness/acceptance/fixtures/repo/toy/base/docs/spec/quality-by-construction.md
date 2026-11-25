# Toy project: quality by construction

## 0. Goals, principles and requirements

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
- [ ] **R3.** Acceptance tests are visible (ATDD) and written by someone other than the builder.
- [ ] **R5.** The packet is written only by the orchestrator or planner, and arrives at session start.

## 6. Plane 2: agent guidance

- QBC-24. A builder MUST be launched only with an approved work packet as input. That launch order is what puts design before code.
