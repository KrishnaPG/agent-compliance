# Salt pack, CI rules

Pack `salt` for base catalog 1.0.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-02 | No second salt-ssh call targets a host while a converge of it runs: both share the host's thin directory, and the first to exit wipes it. | Salt documentation: salt-ssh (`ssh_wipe`, thin directory) | Can a probe or second run reach a target mid-converge? |
