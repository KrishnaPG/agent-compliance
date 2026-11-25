# 0001. Quality by Construction

Status: accepted 2026-11-25 (P3, S, I and the order-engine and end-of-build rulings); the isolation spike and an independent review are still open. Requirements: `docs/spec/quality-by-construction.md` (QBC-n).

## Context

In the pilot project (a private project using this plugin), agents skipped the decision step in most commits, reviews after the build caused most reopens, and most written rules were prose with no check. The first review of this plugin found its anti-gaming protections bypassable, its skills grading their own work, and its catalog mostly one project's conventions. Quality has to come from the build and the flow, not from more prose or more agents.

## Decisions and why

1. **P3: assemble from host features and OSS.** Port only what the host lacks (the measurer core and value order, after their Critical fixes); replace hand-written validators, downloaders and pattern checks with jsonschema, ruff, ESLint, oxlint, sqlfluff, OpenSSF Scorecard, deps.dev and OSV-Scanner. Why: less code to maintain and review, and the review found hand-written replacements for OSS tools. Standard: reuse before write (the adopted-tool-first practice).

2. **S: self-sustained, convention over configuration.** The plugin infers facts from standard files (justfile, Makefile, package.json, CODEOWNERS, OpenAPI tags, lockfiles, the database catalog), ships presets, and asks once into a standard file. Why: a plugin part plus a project part drifts, and plugin scaffolding drifts as the plugin changes (the create-react-app "eject" problem). Follows the buildpacks and shareable-config pattern. Not: a plugin config file, or an init step that writes plugin files.

3. **I: GitHub-native intake (I2).** Goal (milestone), decision with one tracking issue, slices and defects as sub-issues, issue forms with required fields, no issue without a parent. Why: in the pilot, 57% of issues cited no decision, chains ran five deep and tracking issues went stale. Follows the Rust RFC process, Scrum Definitions of Ready and Done, Shape Up (no infinite backlog) and Kanban work-in-progress limits. Not: flat labels, work lists inside decision documents, an external tracker.

4. **The order engine is a program; no agent in the mechanical path.** Git, tests, measuring and ordering run in code; agents launch only for judgement. Why: an agent in the mechanical path costs tokens, can be argued with, and workflow scripts need an agent to run the measurer. Not: workflow scripts as the engine.

5. **End of build is a measurer retry, not a blocking hook.** The measurer runs the same checks a human's build runs and returns the missed ones, with their messages, for another round within a round limit. Why: a blocking stop hook refuses, invites working around it, and its worktree target is undocumented.

6. **Every rejection teaches.** Every check, hook, linter, verifier and retry says what is wrong, the right way concretely, and how to prevent it, in about 300 characters, through one helper whose arguments are all required. Why: a bare "this is wrong" is how gaming starts. Not: a bare rejection anywhere; third-party rules with fixed messages get a one-line right way keyed by rule code.

7. **No pass/fail quality gates; refusals for order only.** Facts are recorded, limits cap rounds, only measured targets move an item on. The one refusal is H0 (a builder edit with no packet), because a note alone would let the builder carry on, and the packet lives in a protected path. Why: gates invite gaming. Not: a hook that lets the agent decide whether a rule applies to it (self-grading), or hooks that match code patterns; a pattern worth catching becomes structure, a fitness function or a configured linter rule where it also catches humans. Mechanism kinds (structure, fact, order, limit) and gaming routes are in the spec. Standards: fitness functions (Ford, Parsons, Kua), least privilege (NIST SP 800-53 AC-6), ATDD, mission command.

8. **The Known issues list is a bounded backlog.** One list for minors with practical value, each line naming its parent; at the limit (default 100, set as policy) items are fixed and removed before new ones are added. Why: Agile and Kanban backlogs are bounded, and unbounded minors churned in the pilot (34 filed and reversed in 3 hours). Defect triage by severity follows ISTQB. Not: a second list, or filing theoretical minors.

9. **Standards, OSS and reuse; no hard-coding; no excess.** Every choice cites a named standard or best practice. Every limit (work-in-progress, packet cap, message cap, model per role, tier triggers, project conventions) is a default with an override in a standard place, never a constant. Build only for a measured need. Replace the plugin's own catalog with maintained standards (OWASP ASVS, NIST SSDF and SP 800-53, SLSA, Well-Architected) plus a short house list. Delete before adding; replace a check only after a parity test on planted violations; new checks start from a ratchet.

## Also decided

- A builder starts only from an approved work packet; the orchestrator sets the tier from facts at launch; the builder never does. The packet has no design field and is capped. Tests are written first by someone who is not the builder, in protected paths. One agent never both designs and builds.
- A decision record is at most two pages, one per epic, never per issue.
- Existing plugin parts are used only after review: keep the orchestrator, delete 9 unused scripts and two skills, fix the measurer first.

## What not to do

- Do not add a check that only agents face, or a hook that matches patterns.
- Do not let a builder write its packet, edit protected tests, or pick its own tier.
- Do not refuse anything except out-of-order steps, and never refuse without teaching.
- Do not add plugin config files or scaffolding to a project, or a second backlog.
- Do not hand-write what a maintained OSS tool or linter already does.
- Do not remove an old check before its replacement passes parity.
- Do not put a limit or business value in code as a constant.

## Open

The isolation spike on the toy project (how agents launch headless and at what cost; that a planted tampering builder is stopped; that hooks fire inside launched agents) and an independent design review (the decision skill grades its own work, so the design needs a reader who did not write it). Evidence: `docs/design/evidence/`.
