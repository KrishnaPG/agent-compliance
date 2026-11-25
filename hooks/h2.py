#!/usr/bin/env python3
"""H2, PreToolUse on Edit and Write: one owner line on the first touch outside the packet's paths (QBC-50). Never blocks."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c

data = c.load_input()
root = c.project_dir(data)
globs = c.declared_globs(root) if c.is_builder(data) else []
path = c.target_path(data, root)
if not globs or not path or c.inside(path, globs):
    c.emit()
mark = c.seen_marker(root, path)
if mark.exists():
    c.emit()
mark.parent.mkdir(parents=True, exist_ok=True)
mark.touch()
line = f"{path} belongs to owner {c.owner_of(root, path)}, outside your packet. Call its published interface, or ask the orchestrator to widen the packet."
line = line[: c.h2_chars(root)]
fact, rec = c.record_fact(root, "scope", f"{path} touched outside the packet")
print(json.dumps({
    "facts": [rec],
    "run_report": str(fact),
    "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": line},
}))
sys.exit(0)
