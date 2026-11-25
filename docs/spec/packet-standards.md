# Stage outputs: standards applied and standards left out

Every stage of the flow writes one output in a standard format. This file names, for each stage, the standards it applies and those it leaves out, with the reason. The L2 packet is the single contract: the test author (L3), the builder (L4) and the measurer (L5) all read it, so there is one definition of success (owner, 2026-11-25). Plan task d0 builds the schemas and checks.

## Common to every stage

| Concern | Standard | Why |
|---|---|---|
| Any JSON output | JSON Schema 2020-12, validated by the `jsonschema` library | Mechanical validation (P3), OSS (P2) |
| Every refusal, finding or note | ISO 9241-110:2020, user-error robustness and suitability for learning: what is wrong, the right way, how to prevent it | Every rejection teaches (P5) |
| Reference to the contract | The packet id plus its sha256 in every output | One contract, never two |

## L1 Epic design: decision record

### Applied

| Part | Standard | Why |
|---|---|---|
| Decision record | MADR 4.0 (Markdown Architectural Decision Records) | The most widely used ADR template, with tooling (adr-tools, log4brains); it has sections for context, options, the outcome and its consequences |
| Lineage and size | Nygard ADR: one decision per record, short | Records stay readable and current |
| Front matter | MADR's status, date and deciders | Checkable by the program |
| Option judgement | The project's vetted-decision method, with a fresh agent as the judge | Nobody grades themselves (P6) |
| Link to the work | The decision record links its tracking issue, and the issue links back (as in the Rust RFC process) | Intake I2, nothing free-floating |
| Hand-off to L2 | Each constraint cites §0 or QBC ids; its falsifying calls become L2 acceptance criteria | Traceability (ISO/IEC/IEEE 29148) |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| A full ISO/IEC/IEEE 42010 architecture description (viewpoints, models) | Heavyweight for per-epic decisions (P10); MADR keeps the rationale that matters |
| arc42 | It documents a whole architecture, not one decision |
| Y-statements (Zimmermann) | Compact, but less structure than MADR for options and consequences, and no front matter to check |
| C4 diagrams as a requirement | Optional; a decision may include one, but nothing depends on it |

## L2 Plan: the packet

### Applied

| Packet part | Standard or practice | Why |
|---|---|---|
| Schema and validation | JSON Schema draft 2020-12, validated with the `jsonschema` library | Machine-checkable, so validation is mechanical (P3); OSS (P2) |
| Requirement wording in the spec | RFC 2119 / RFC 8174 (MUST, SHOULD) | One meaning per keyword |
| Ids, traceability, verification method per `acceptance[*]` item | ISO/IEC/IEEE 29148:2018 | Every `acceptance[*]` item traces to its G, P, R or QBC item and states how it is verified (test, lint, fitness, measure). Requirements engineering standard |
| Acceptance criteria | Gherkin Given/When/Then (ATDD; Specification by Example) | Acceptance criteria a non-builder can write and a test can implement |
| Goal without method | Commander's intent (mission command, US Army ADP 6-0) | States the goal, why and end state, with no pre-chosen design |
| Definition of Done | Scrum Guide 2020; Definition of Ready as common practice | Done = every `acceptance[*]` item met by the measurer |
| Slice size | INVEST (Wake) | Independent, small, testable slices |
| Tier of a pin change | Semantic Versioning 2.0.0 | Patch and minor are mechanical; major is design-affecting |
| Architecture checks in the verifier list | Fitness functions (Ford, Parsons and Kua) | Properties declared once, checked in the build |
| Teaching messages | ISO 9241-110:2020, user-error robustness and suitability for learning | An error says what is wrong and how to do it right |
| Measured results | JUnit XML (de facto test-report format) | Every test runner can emit it |
| Security-review trigger | NIST SSDF SP 800-218 PW.7; OWASP SAMM | Independent review of security-sensitive diffs |
| Isolation of the measuring run | Least privilege, NIST SP 800-53 AC-6 | The measured code can't write outside its checkout |
| Commit messages (as facts) | Conventional Commits 1.0 via commitlint | Lint for fix and feature records, never blocking |
| Success of the whole flow | DORA metrics (change-failure rate, lead time) | Industry delivery metrics, against a pre-v2 baseline |
| Ratchet baselines | Baseline-file practice (ruff `--add-noqa`, detekt and PHPStan baselines) | No formal standard; established practice for applying new rules forward (P11) |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| IEEE 829 / ISO/IEC/IEEE 29119-3 test documentation (test plans, design and case specs) | A heavyweight document set. The Gherkin acceptance criteria plus 29148 traceability carry what this flow needs (P10, no excess) |
| EARS requirement syntax | It would add a third syntax beside RFC 2119 in the spec and Gherkin in acceptance criteria, for no measured gain (P10) |
| A Cucumber runtime that executes Gherkin directly | It adds a runtime dependency in every stack. Acceptance criteria are implemented in the project's own test framework (convention over configuration, P9); pytest-bdd and similar are used only where a project already has them |
| SAFe and full Scrum ceremonies | Team-coordination overhead with no role for agents (P10) |
| Hidden holdout tests (benchmark practice) | ATDD tests are visible (R3, owner ruling). Added only for a measured need |
| Mutation testing (mutmut, Stryker) in the Definition of Done | Costly per item. Vacuous tests are countered by red-on-main and the review trigger; an option once a measured need appears |
| SLSA provenance for packets and builds | No measured need yet. Kept as a later extension |
| Formal verification of the order engine (TLA+) | Excess for a sequential program with tested steps (P10) |

## L3 Tests: generated acceptance tests

### Applied

| Part | Standard | Why |
|---|---|---|
| Acceptance criteria to tests | Keyword-driven testing (ISTQB; FIT/FitNesse tables): rows from closed catalogs, turned into tests by a generator | No agent judgement; consistent results |
| Test code | The project's own framework (pytest for the plugin), each test marked with its acceptance id | Convention over configuration (P9) |
| Results | JUnit XML | Every runner emits it |
| Traceability | A manifest from acceptance id to test node id (ISO/IEC/IEEE 29148) | One test per `acceptance[*]` item, one id per test |
| Model calls in tests | Record and replay (the VCR pattern) | Deterministic and free (R3) |
| Messages and renderings | Approval (snapshot) testing | Cheap checks on teaching messages and the rendered packet |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| TAP (Test Anything Protocol) | Less tool support than JUnit XML for structured attributes such as the acceptance id |
| CTRF (Common Test Report Format) | Newer and less widely adopted; JUnit XML is the common denominator |
| A Cucumber runtime | Adds a runtime in every stack; see the L2 section |
| IEEE 829 / ISO/IEC/IEEE 29119-3 test documents | Heavyweight; the manifest and the acceptance criteria carry what is needed (P10) |
| Allure and similar reporting tools | Presentation only; there is no measured need |

## L4 Build: the commit

### Applied

| Part | Standard | Why |
|---|---|---|
| Commit message | Conventional Commits 1.0 (checked by commitlint as a fact, never blocking) | Machine-readable type and scope |
| Contract reference | git trailers (`git interpret-trailers`): `Packet: <id>@<sha256>`, `Acceptance: <ids>` | A standard git feature that ties the commit to the one contract |
| Tier of version changes | Semantic Versioning 2.0.0 | Patch and minor are mechanical; major is design-affecting (R6) |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| Signed commits (GPG, SSH, Sigstore gitsign) | They prove identity, but agents have no identity of their own: bot accounts are out of our control (P12) |
| DCO sign-off | Contributor licensing, which doesn't apply here |
| Keep a Changelog | Release-level, not commit-level; it belongs to a release step |

## L5 Verify: the measurement

### Applied

| Part | Standard | Why |
|---|---|---|
| Test results | JUnit XML | Every runner emits it |
| Lint and fitness findings | SARIF 2.1.0 (OASIS), with the teaching message in `message`, `help` and `fixes` | The industry exchange format for analysis results; ruff, ESLint and semgrep emit it |
| Verdict for each `acceptance[*]` id, and facts | A result JSON (`command` `measure`) validated by JSON Schema, naming the packet sha256 | Only the measurer writes it |
| Isolation of the run | Least privilege (NIST SP 800-53 AC-6): a bwrap jail plus a canary | Builder code can't write outside its checkout |
| Success of the flow | DORA metrics (change-failure rate, lead time), plus tokens per met slice (summed from `jobs[*].tokens`) | Industry delivery metrics (R11) |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| in-toto attestations and SLSA provenance for results | No measured need yet; a later extension |
| OpenTelemetry for facts | Excess for facts written as files by one program (P10) |
| Checkstyle XML, Code Climate JSON | SARIF covers both, and Code Climate is platform-specific |

## Review (triggered): findings

### Applied

| Part | Standard | Why |
|---|---|---|
| Trigger | NIST SSDF SP 800-218 PW.7; OWASP SAMM design and implementation review | Independent review of security-sensitive diffs (P6) |
| Findings | SARIF 2.1.0; triage severity maps to `level` (error = Critical or Major, warning = Minor with value) | Same format as L5 |
| Severity | ISTQB severity; CVSS 4.0 when a finding is a vulnerability | Standard triage |

### Left out, and why

| Standard | Why it is left out |
|---|---|
| GitHub pull-request review comments as the store | Platform lock-in. They can be rendered from SARIF where wanted |
| A mandatory review for every diff | Not a standard requirement (SSDF targets risk), and it costs every item (P10) |

## Overview: every stage's output

Each stage writes one standard format. Every output carries the packet's id and its sha256, so all of them refer to the same contract.

| Stage | Output | Standard | Checked by the program |
|---|---|---|---|
| L1 Epic design | A decision record plus a tracking issue that links to it | MADR 4.0 (Markdown Architectural Decision Records, based on Nygard), with front matter for status, date and deciders. Its constraints cite the §0 items, and its falsifying calls become L2 acceptance criteria | The front matter and the required sections are present; every constraint cites a G, P, R or QBC id |
| L2 Plan | The work packet (JSON) and its Markdown rendering | All the standards in the L2 section above (JSON Schema 2020-12 is only the container). Acceptance criteria are keyword-driven rows from `docs/atdd/catalog.yaml` | Schema-valid; closed catalogs as enums; every §0 item that applies is traced |
| L3 Tests | Tests generated from the packet's rows, a manifest (acceptance id → test node id), and the red-on-main run | Generated pytest (or the project's own framework), with each test marked by its acceptance id; the run in JUnit XML | One test per `acceptance[*]` item and one id per test; every test fails on main with an assertion failure, not an error |
| L4 Build | A commit on the builder's branch | Conventional Commits 1.0, with git trailers `Packet: <id>@<sha256>` and `Acceptance: <ids>` | The trailer's sha256 matches the packet; the diff's paths are compared with the packet's declared paths (a fact) |
| L5 Verify | The measurement: met or unmet for each `acceptance[*]` id, plus facts | JUnit XML for tests; SARIF 2.1.0 (OASIS) for lint and fitness findings, with the teaching message in `message`, `help` and `fixes`; a result JSON (`command` `measure`), schema-validated, that names the packet sha256 | Only the measurer writes it; it reads the packet and tests from the base commit, never from the builder's copy |
| Review (triggered) | Findings | SARIF 2.1.0, with triage severity mapped to `level` (error = Critical or Major, warning = Minor with value) | Findings are facts that never change "met"; each cites the packet sha256 |

## How "one packet, one definition of success" is enforced

These are mechanisms, not agent discipline.
1. **One file.** The packet is one schema-valid file at a path only the planner or orchestrator writes. Its sha256 identifies it.
2. **L3 is generated from it.** Tests are produced by the generator from the packet's rows, so the tests can't differ from the acceptance criteria, and the manifest maps each one.
3. **L4 receives the same bytes.** The builder's session-start context is the packet's rendering. The builder's `bh check` reads the same packet and runs the same verifier list.
4. **L5 reads it from the base.** The measurer takes the packet and the generated tests from the base commit by their sha256, never from the builder's clone. A packet or test that changed in the build is recorded as tampering and has no effect.
5. **Every output names the sha256.** The commit trailer, the result JSON and the SARIF properties do. A mismatch is recorded as a fact and the item is re-run against the right packet; the outputs are never judged against two contracts.
