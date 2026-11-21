# Reviewer brief (compliance review)

Read-only review: do not edit, commit or post.

- Base catalog (version `<v>`): `<absolute path to catalog/index.md>`, and for your domains `<absolute paths to catalog/base/<DOMAIN>.md>` and `<absolute paths to catalog/packs/<pack>/<DOMAIN>.md>` for the packs the overlay names.
- Project overlay: `<absolute path>` at `<commit>` (or "none").
- Artifact: `<path>` at `<commit>`.
- Your domains: `<ids>`.

For every rule of your domains, return one row: `| Rule | HELD/BROKEN/NA | Artifact location | Evidence | Fix |`.

- Judge each rule from its catalog row alone; the row is the whole rule. Read the artifact and the code or documents it names to find evidence.
- HELD: cite where the artifact satisfies the rule.
- BROKEN: a runtime rule needs a concrete failing input or reachable state; a document, plan or process rule needs the location that breaks its text. Give the fix by the right standard, pattern or reuse of existing code.
- NA: one sentence why the rule does not apply.
- Life and death (when LC is among your domains): list every acquisition and every termination effect the artifact adds or changes: any runtime, data or access effect that ends, removes or destroys something (not an edit of a document or source file) (delete, revoke, disable, prune, offboarding, credit or reversal, cleanup, reset, session, token, grant or membership end). For each acquisition judge its level, parents and readiness (LC-01, LC-02, LC-04). For each termination judge: its termination tier with a number and a native mechanism (LC-39, LC-41); a T0 effect checked at the action and placed after every refusal (LC-40); the person's account and the data kept as the policy states (LC-42, DS-01, DS-04); child-first release (LC-02); the rule ids in the comment at the code site (LC-43). The overlay rows that tighten these give the project's numbers. A termination you found and none of these rows covers is listed, not skipped.
- Anything that is not a catalog rule goes only under "Possible missing rules"; it is not a finding.
- Mark anything you could not verify as UNVERIFIED with the reason; never mark a rule HELD on assumption.

On a re-review, check only the rules listed as previously BROKEN and the rules whose evidence locations the fix touched.

Write the result to `<output file>` and reply with the verdict (PASS if no rule is BROKEN), the BROKEN rows and the possible missing rules.
