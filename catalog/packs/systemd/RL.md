# systemd pack, RL rules

Pack `systemd` for base catalog 1.1.0. Scope: unit timeouts and results, ordering, drop-ins, timers. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| SD-01 | Every oneshot or start-bounded unit carries `TimeoutStartSec`; its result and exit status are the run's one verdict. | systemd.service(5) | Which unit can hang without a timeout, and what reads its result? |
| SD-02 | A unit that needs a dependency is ordered on it with `Requires=` and `After=` and the dependency's readiness notification; a longer `RestartSec` or a raised start limit is never the fix for an ordering gap. | systemd.unit(5); systemd.service(5) | Is any restart setting changed to get past an ordering gap? |
| SD-04 | No timer unit is a repair, re-apply or drift-correction path: work a timer would start is started by the event that makes it necessary; a timer is allowed only for a schedule that is itself the requirement. | Convention: event-driven reconciliation; systemd.timer(5) for what a timer is | Does any timer unit start work that an event should start? |
