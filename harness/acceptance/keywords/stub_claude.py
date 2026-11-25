#!/usr/bin/env python3
"""Stub `claude`: replays recorded replies in order; no network, no model, no cost.

Fixture ($ATDD_MODEL_FIXTURE): JSON {"replies": [{"events": [...stream-json objects...] | "stdout": "raw text", "exit": 0}]}.
Reply N answers the Nth launch. Every launch is logged to $ATDD_MODEL_LOG as one JSON line {argv, cwd, stdin}.
With no fixture, or with the replies used up, it exits 3 and says so (a launch the row did not expect).
"""

import json
import os
import sys
from pathlib import Path

stdin = "" if sys.stdin.isatty() else sys.stdin.read()
log = os.environ.get("ATDD_MODEL_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": stdin}) + "\n")
fx = os.environ.get("ATDD_MODEL_FIXTURE")
state = Path(os.environ.get("ATDD_MODEL_STATE", "/dev/null"))
n = int(state.read_text()) if state.is_file() else 0
if state.parent.is_dir():
    state.write_text(str(n + 1))
if not fx:
    print("[ATDD-MODEL] no recorded model reply is given for this row -> add a recorded_model given . harness/acceptance/fixtures/README.md", file=sys.stderr)
    sys.exit(3)
replies = json.loads(Path(fx).read_text())["replies"]
if n >= len(replies):
    print(f"[ATDD-MODEL] launch {n + 1} has no recorded reply (the fixture holds {len(replies)}) -> the program launched more jobs than recorded . harness/acceptance/fixtures/README.md", file=sys.stderr)
    sys.exit(3)
r = replies[n]
if "stdout" in r:
    sys.stdout.write(r["stdout"])
for ev in r.get("events", []):
    print(json.dumps(ev))
sys.exit(r.get("exit", 0))
