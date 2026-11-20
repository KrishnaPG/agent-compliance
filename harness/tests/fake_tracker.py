"""A stateful stand-in tracker for tests (not a test module): a JSON store and the six
operations the harness calls, printing entries in the harness's own shape.

    fake_tracker.py STORE ready LIMIT [PARENT] | show REF | list LIMIT
                          | claim REF ACTOR | close REF REASON | reopen REF REASON
"""

import json
import sys
from pathlib import Path

store, op, *a = sys.argv[1:]
p = Path(store)
db: dict = json.loads(p.read_text()) if p.exists() else {}


def done(code: int = 0, msg: str = "") -> None:
    p.write_text(json.dumps(db))
    if msg:
        print(msg, file=sys.stderr)
    sys.exit(code)


if op != "list" and op != "ready" and a[0] not in db:
    done(1, f"no entry {a[0]}")
if op == "show":
    print(json.dumps(db[a[0]]))
elif op == "list":
    print(json.dumps([e for e in db.values() if e["state"] != "closed"][: int(a[0])]))
elif op == "ready":
    parents = {e["parent"] for e in db.values() if e.get("parent")}
    ok = [
        e
        for e in db.values()
        if e["state"] == "open"
        and e["type"] == "item"
        and not e.get("assignee")
        and e["ref"] not in parents
        and all(db.get(d, {}).get("state") == "closed" for d in e["deps"])
        and (len(a) < 2 or e["parent"] == a[1])
    ]
    print(json.dumps(ok[: int(a[0])]))
elif op == "claim":
    e = db[a[0]]
    if e.get("assignee") not in (None, a[1]):
        done(1, "already claimed")
    e.update(assignee=a[1], state="in_progress")
elif op == "close":
    db[a[0]].update(state="closed", note=a[1])
elif op == "reopen":
    db[a[0]].update(state="open", note=a[1])
done()
