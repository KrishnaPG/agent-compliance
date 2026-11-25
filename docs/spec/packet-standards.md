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
