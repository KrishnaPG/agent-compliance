#!/usr/bin/env python3
"""H0, PreToolUse on Edit and Write: refuse a builder's edit while no packet is registered (QBC-46, QBC-47)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c

data = c.load_input()
root = c.project_dir(data)
if not c.is_builder(data) or c.has_packet(data, root):
    c.emit()
fact, rec = c.record_fact(root, "h0_bypass", c.H0_TO_ORCHESTRATOR.format(id=data.get("agent_id", "?")))
print(json.dumps({
    "facts": [rec],
    "run_report": str(fact),
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": c.H0_TO_BUILDER,
    },
}))
sys.exit(0)
