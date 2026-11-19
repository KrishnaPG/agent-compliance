# Check packs

Static checks that find, in code, a few catalog rules a review would otherwise judge by reading. A check is evidence for its rule; it never replaces the rule's review, and a rule without a check is still reviewed.

## What the packs cover

| Rule | Ecosystems | Flags | Binds |
|---|---|---|---|
| RL-08 (and LC-17) no polling | python, typescript | a sleep or `setTimeout` inside a loop (a `while True` / `while (true)` loop that sleeps is reported at its sleep), `setInterval`, and a polling-interval setting named like `poll*interval*` or `polling_interval*` | none |
| HO-02 publish only after commit | python, typescript | a direct broker publish: NATS or JetStream `publish`, Kafka `produce`, `send` on a producer | `outbox_modules` |
| ID-15 verify once at entry | python, typescript | token or signature verification: `jwt.decode`, `jws.verify`, jose and jwcrypto verify calls, `jwtVerify`, node `crypto.verify`, `verify_signature` | `entry_modules` |

`base/` holds the checks of base catalog rules; a technology pack's checks go in `checks/<pack>/`. The rules are written for ast-grep 0.51.3.

## Index contract

`index.json` lists every check:

```json
{"version": 1, "checks": [{"rule": "RL-08", "pack": "base", "ecosystem": "python", "tool": "ast-grep", "file": "checks/base/RL-08.python.yml", "binds": []}]}
```

- `rule`: the catalog rule id the check is evidence for.
- `pack`: `base` or the pack name.
- `ecosystem`: `python`, `typescript` or `sql`.
- `tool`: the tool that runs `file`.
- `file`: path from the plugin root.
- `binds`: project facts the check needs, read from the project's bindings. Each bind names module paths where the flagged call is the rule's one allowed place (`outbox_modules`: the outbox relay; `entry_modules`: where material enters the trust boundary). The harness runs the check on every module except those paths. Rule files hold no project paths.

## From a check to its rule

A check file is `<pack>/<RULE-ID>.<ecosystem>.yml`, its ast-grep `id` is `<RULE-ID>.<ecosystem>`, and its `metadata.catalog` lists every catalog id it is evidence for (RL-08 checks also cover LC-17). A finding cites that id, and its message names the rule and the fix.

## Running

Checks run by default in the harness: every check whose ecosystem the project uses runs on every change. A project opts a rule out only in its overlay, under the heading `## Check opt-outs`, one line per rule in exactly this form:

```
- RL-08 not-applicable: <reason>
```

The line holds the rule id, the word `not-applicable` and a reason after the colon. A line without a reason opts nothing out. Opting out a rule skips every check whose `rule` is that id.

Each rule file runs on its own as `ast-grep scan --rule <file> --json` (ast-grep 0.51.3). Every rule has severity `error`, so a scan with a finding exits 1; findings carry the ast-grep `id` as `ruleId`, and line numbers in the JSON are 0-based.

Each check has its own test, in ast-grep's rule-test format: `tests/<id>-test.yml` with `valid` cases that must not match (near misses included) and `invalid` cases that must, plus their recorded snapshots in `tests/__snapshots__/`. From this directory:

```
ast-grep test
```

The tests exercise code snippets; the path exclusions from `binds` are applied by the harness and are not covered by them.
