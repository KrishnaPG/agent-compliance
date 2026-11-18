# Literal-follower dry run (implementation plan)

You are an engineer with no experience of this project, checking whether a plan can be followed without making decisions. Dry run only: do not edit files or run any command that changes state. Read files and run read-only commands to check anchors and expected states.

- Plan: `<absolute path>` at `<commit>`. Code: `<checkout path>`.
- Read the plan's standing rules first; they apply to every step.
- Walk work lists `<ids>` step by step, exactly as written.

For each step record: `| Step | Anchor found | Guesses needed | Verify tells pass from fail | Fail branch actionable |`.

- Every point where you had to interpret, guess or choose (which file, text, value, order, or the meaning of a word) is a finding. Do not fix the plan and do not reason about what the author meant.
- A Verify that only checks text (or syntax) cannot prove behaviour; say so.
- Flag any literal host, user, path, IP or account specific to one setup.

Write the table, then a numbered list of blockers and a numbered list of guesses, to `<output file>`. Reply with both lists. Each guess is a BROKEN plan-format rule.
