#!/usr/bin/env -S uv run --script --managed-python
# /// script
# requires-python = "==3.14.*"
# dependencies = []
# ///
"""SG-01, PreToolUse on Edit and Write: the builder's one write guard. It refuses, with one teaching line (P5),
a change to a protected acceptance test or to any path outside the clone. The protected list is the packet's own
(the list the sandbox's denyWrite is made from); no deny rule is set on it. The host's scoped file tools stay
underneath as the backstop (R4): the builder meets this hook first and is taught."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c
data = c.load_input()
root = c.project_dir(data)
path = c.target_path(data, root)
if not c.is_builder(data) or not path:
    c.emit()
if c.outside(root, path):
    reason = c.outside_pre(path)
elif c.inside(path, c.acceptance_globs(root)):
    reason = c.sg01_pre(path)
else:
    c.emit()
print(json.dumps({
    "facts": [],
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    },
}))
sys.exit(0)
