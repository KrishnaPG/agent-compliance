# The L2 packet: standards applied and standards left out

The packet is the single contract. The test author (L3), the builder (L4) and the measurer (L5) all read it, so there is one definition of success (owner, 2026-11-25). Plan task d0 builds it.

## Applied

| Packet part | Standard or practice | Why |
|---|---|---|
| Schema and validation | JSON Schema draft 2020-12, validated with the `jsonschema` library | Machine-checkable, so validation is mechanical (P3); OSS (P2) |
| Requirement wording in the spec | RFC 2119 / RFC 8174 (MUST, SHOULD) | One meaning per keyword |
| Ids, traceability, verification method per criterion | ISO/IEC/IEEE 29148:2018 | Every criterion traces to its G, P, R or QBC item and states how it is verified (test, lint, fitness, measure). Requirements engineering standard |
| Acceptance criteria | Gherkin Given/When/Then (ATDD; Specification by Example) | Criteria a non-builder can write and a test can implement |
| Goal without method | Commander's intent (mission command, US Army ADP 6-0) | States the goal, why and end state, with no pre-chosen design |
| Definition of Done | Scrum Guide 2020; Definition of Ready as common practice | Done = every criterion met by the measurer |
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

## Left out, and why

| Standard | Why it is left out |
|---|---|
| IEEE 829 / ISO/IEC/IEEE 29119-3 test documentation (test plans, design and case specs) | A heavyweight document set. The Gherkin criteria plus 29148 traceability carry what this flow needs (P10, no excess) |
| EARS requirement syntax | It would add a third syntax beside RFC 2119 in the spec and Gherkin in criteria, for no measured gain (P10) |
| A Cucumber runtime that executes Gherkin directly | It adds a runtime dependency in every stack. Criteria are implemented in the project's own test framework (convention over configuration, P9); pytest-bdd and similar are used only where a project already has them |
| SAFe and full Scrum ceremonies | Team-coordination overhead with no role for agents (P10) |
| Hidden holdout tests (benchmark practice) | ATDD tests are visible (R3, owner ruling). Added only for a measured need |
| Mutation testing (mutmut, Stryker) in the Definition of Done | Costly per item. Vacuous tests are countered by red-on-main and the review trigger; an option once a measured need appears |
| SLSA provenance for packets and builds | No measured need yet. Kept as a later extension |
| Formal verification of the order engine (TLA+) | Excess for a sequential program with tested steps (P10) |

## Every stage's output format (owner question, 2026-11-25)

Each stage writes one standard format. Every output carries the packet's id and its sha256, so all of them refer to the same contract.

| Stage | Output | Standard | Checked by the program |
|---|---|---|---|
| L1 Epic design | A decision record plus a tracking issue that links to it | MADR 4.0 (Markdown Architectural Decision Records, based on Nygard), with front matter for status, date and deciders. Its constraints cite the §0 items, and its falsifying calls become L2 criteria | The front matter and the required sections are present; every constraint cites a G, P, R or QBC id |
| L2 Plan | The work packet (JSON) and its Markdown rendering | JSON Schema 2020-12 (see the table above). Acceptance criteria are keyword-driven rows from `docs/atdd/catalog.yaml` | Schema-valid; closed catalogs as enums; every §0 item that applies is traced |
| L3 Tests | Tests generated from the packet's rows, a manifest (criterion id → test node id), and the red-on-main run | Generated pytest (or the project's own framework), with each test marked by its criterion id; the run in JUnit XML | One test per criterion and one criterion per test; every test fails on main with an assertion failure, not an error |
| L4 Build | A commit on the builder's branch | Conventional Commits 1.0, with git trailers `Packet: <id>@<sha256>` and `Criteria: <ids>` | The trailer's sha256 matches the packet; the diff's paths are compared with the packet's declared paths (a fact) |
| L5 Verify | The measurement: per-criterion met or unmet, plus facts | JUnit XML for tests; SARIF 2.1.0 (OASIS) for lint and fitness findings, with the teaching message in `message`, `help` and `fixes`; a result JSON, schema-validated, that names the packet sha256 | Only the measurer writes it; it reads the packet and tests from the base commit, never from the builder's copy |
| Review (triggered) | Findings | SARIF 2.1.0, with triage severity mapped to `level` (error = Critical or Major, warning = Minor with value) | Findings are facts that never change "met"; each cites the packet sha256 |

### How "one packet, one definition of success" is enforced

These are mechanisms, not agent discipline.
1. **One file.** The packet is one schema-valid file at a path only the planner or orchestrator writes. Its sha256 identifies it.
2. **L3 is generated from it.** Tests are produced by the generator from the packet's rows, so the tests can't differ from the criteria, and the manifest maps each one.
3. **L4 receives the same bytes.** The builder's session-start context is the packet's rendering. The builder's `bh check` reads the same packet and runs the same verifier list.
4. **L5 reads it from the base.** The measurer takes the packet and the generated tests from the base commit by their sha256, never from the builder's clone. A packet or test that changed in the build is recorded as tampering and has no effect.
5. **Every output names the sha256.** The commit trailer, the result JSON and the SARIF properties do. A mismatch is recorded as a fact and the item is re-run against the right packet; the outputs are never judged against two contracts.
