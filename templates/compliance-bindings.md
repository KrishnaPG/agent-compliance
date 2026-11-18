# Compliance bindings

What the agent-compliance skills read for this project. Default path `docs/agents/compliance-bindings.md`; name another path in AGENTS.md or CLAUDE.md. One line per binding; delete a line the project does not have.

| Binding | Value |
|---|---|
| Tracker | <host and repository of the issue tracker> |
| Overlay | <path of the project's overlay catalog> |
| Decision record | <where a `Decision: <question>` is posted and how an earlier one is searched> |
| Vetting record | <where a `Vetted: <tool> <tag>` is posted>; clone directory <path> |
| Review verdict | <where a compliance-review verdict table is posted>; review command <command> |
| Bug record | <how a bug issue is created: command or labels> |
| Bug ledger | <the command that lists every record, and the issues it reads> |
| Test forms | <the forms a record's `Test:` takes in this project> |
| Close | <the command that runs a record's Test and closes its issue> |
| Start and end | <commands a piece of work starts and ends with, if any> |
| Evidence environment | <the installation where a falsifying call or an install answer is taken> |
| Owner decides | <the escalation categories only the project owner rules on (catalog PR-10)> |
