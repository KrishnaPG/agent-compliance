# systemd pack, CI rules

Pack `systemd` for base catalog 1.0.0. Scope: unit timeouts and results, ordering, drop-ins, timers. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SD-03 | A per-installation or per-tenant change to a shared unit is a drop-in file, never an edit of the shared unit file. | systemd.unit(5) | How does one installation change a shared unit? |
| SD-05 | A run is one named unit instance per installation; starting it while it runs is refused, not queued. | systemd-run(1); systemd.unit(5) | What happens when the same run is started twice? |
