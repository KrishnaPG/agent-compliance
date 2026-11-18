# Salt pack, DS rules

Pack `salt` for base catalog 1.0.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-03 | A directory managed with `clean: True` holds only files declared by states; nothing is placed there by hand, because the next converge deletes it. | Salt documentation: `file.directory` | Is any file expected to survive in a cleaned directory without a state? |
