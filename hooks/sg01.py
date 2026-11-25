#!/usr/bin/env -S uv run --script --managed-python
# /// script
# requires-python = "==3.14.*"
# dependencies = []
# ///
"""SG-01, PreToolUse on Edit and Write: refuse a builder's change to a protected acceptance test with one teaching line.
The path list is the packet's own (the list the sandbox's denyWrite is made from); no deny rule is set on it."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c
data = c.load_input()
root = c.project_dir(data)
path = c.target_path(data, root)
if not c.is_builder(data) or not path or not c.inside(path, c.acceptance_globs(root)):
    c.emit()
print(json.dumps({
    "facts": [],
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": c.SG01_PRE.format(path=path),
    },
}))
sys.exit(0)
