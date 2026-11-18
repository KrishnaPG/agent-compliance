# Salt pack, CI rules

Pack `salt` for base catalog 1.1.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-02 | No second salt-ssh call targets a host while a converge of it runs: calls to one host share its thin directory, and where wiping (`--wipe`, `ssh_wipe`) is on, the first to exit removes it under the other; a probe uses its own thin directory (`--rand-thin-dir`), never the converge's. | Salt documentation: salt-ssh (`--wipe`, `--rand-thin-dir`), roster `thin_dir` | Can a probe or second run reach a target mid-converge? |
