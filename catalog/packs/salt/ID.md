# Salt pack, ID rules

Pack `salt` for base catalog 1.0.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-04 | A template reads secrets at execution, not at render, and a converge logs changes and failures only, never file contents. | Salt documentation: pillar, `file.managed` (`show_changes`) | Is any secret read at render or written to a log? |
