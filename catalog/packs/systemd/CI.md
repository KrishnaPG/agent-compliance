# systemd pack, CI rules

Pack `systemd` for base catalog 1.0.0. Scope: unit timeouts and results, ordering, drop-ins, timers. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SD-03 | A per-installation or per-tenant change to a shared unit is a drop-in file, never an edit of the shared unit file. | systemd.unit(5) | How does one installation change a shared unit? |
| SD-05 | A run is a transient unit created by `systemd-run --unit=<name>` with one name per installation; creating it while a unit of that name is still loaded fails, so a second run is refused, not queued or merged. | systemd-run(1) `--unit`; systemd D-Bus `StartTransientUnit` (fails if the unit name is already loaded) | What happens when the same run is started twice? |
