# Reviewer brief (compliance review)

Read-only review: do not edit, commit or post.

- Base catalog: `<absolute path to catalog/base.md>` (version `<v>`).
- Project overlay: `<absolute path>` at `<commit>` (or "none").
- Artifact: `<path>` at `<commit>`.
- Your domains: `<ids>`.

For every rule of your domains, return one row: `| Rule | HELD/BROKEN/NA | Artifact location | Evidence | Fix |`.

- Judge each rule from its catalog row alone; the row is the whole rule. Read the artifact and the code or documents it names to find evidence.
- HELD: cite where the artifact satisfies the rule.
- BROKEN: a runtime rule needs a concrete failing input or reachable state; a document, plan or process rule needs the location that breaks its text. Give the fix by the right standard, pattern or reuse of existing code.
- NA: one sentence why the rule does not apply.
- Anything that is not a catalog rule goes only under "Possible missing rules"; it is not a finding.
- Mark anything you could not verify as UNVERIFIED with the reason; never mark a rule HELD on assumption.

On a re-review, check only the rules listed as previously BROKEN and the rules whose evidence locations the fix touched.

Write the result to `<output file>` and reply with the verdict (PASS if no rule is BROKEN), the BROKEN rows and the possible missing rules.
