#!/usr/bin/env -S uv run --script --managed-python
# /// script
# requires-python = "==3.14.*"
# dependencies = []
# ///
"""SG-01, PostToolUse on Bash: when the sandbox answered a builder's command with its read-only error, add one note
saying the tests are protected. It reads the sandbox's own error, never the command."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c
data = c.load_input()
resp = data.get("tool_response")
text = json.dumps(resp).lower() if resp is not None else ""
if not c.is_builder(data) or "read-only file system" not in text:
    c.emit()
print(json.dumps({"facts": [], "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": c.SG01_NOTE}}))
sys.exit(0)
