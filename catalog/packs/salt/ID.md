# Salt pack, ID rules

Pack `salt` for base catalog 1.1.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-04 | A secret reaches a minion only through pillar (compiled on the master, readable only by the targeted minion) and is never written to the state tree or version control; every `file.managed` state (and `file.append` from Salt 3008.0) that holds a secret sets `show_changes: False`, and a secret is never written by a file state that lacks that option, so the run output reports that the file changed, never its contents. | Salt documentation: pillar (storing sensitive data); `file.managed` `show_changes` | Is any secret in the state tree, or shown in a state's diff output? |
