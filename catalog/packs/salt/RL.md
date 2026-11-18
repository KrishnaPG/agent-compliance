# Salt pack, RL rules

Pack `salt` for base catalog 1.1.0. Scope: requisites, concurrent runs, managed directories, secrets at render. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SALT-01 | Order and re-runs come from Salt requisites (`require`, `watch`, `onchanges`) and idempotence from `unless`/`onlyif` guards; no state loops, sleeps or retries to wait for another. | Salt documentation: requisites | Does any state wait by a loop or retry instead of a requisite? |
