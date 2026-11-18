# Catalog weakness audit

Read-only. Run as a fresh agent that shares no context with the catalog's author (a new session or subagent, given only this brief and the files).

- Catalog: `<absolute path>` at `<commit>`; base version `<v>` if this is an overlay.
- Sources: `<the project's binding documents>`; external standards named in the provenance column.

Find where the catalog is too weak to judge a design:

1. **Missing rules:** every binding must or never in the sources that no row covers (proposed id, rule, provenance, test question).
2. **Weak rules:** untestable or vague rows, rows weaker or stricter than their source, rows missing the source's number or allowed exception (corrected text).
3. **Provenance:** sample at least 40 rows; check the source states the rule. Fetch external standards where possible; mark CONFIRMED, WRONG (with the correct reference) or UNVERIFIED.
4. **Scenarios:** for each scenario, can a design be judged with its listed rules? Name missing scenarios with the rules that would decide them.
5. **Self-containment:** sample rows across domains; can each be judged from the row alone? Is any external text reproduced verbatim?
6. **Conflicts:** source lines that contradict each other or the owner's rulings.

Verdict ADEQUATE or WEAK. Write the result to `<output file>` and reply with counts per section and the verdict. A re-audit checks only the sections of the previous audit.
