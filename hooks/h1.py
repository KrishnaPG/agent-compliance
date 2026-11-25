#!/usr/bin/env python3
"""H1, SessionStart: deliver the builder's registered packet once, as additionalContext (QBC-46, QBC-49).

The one delivery channel: the launch prompt names no goal, and the packet text comes only from here.
The rendering is the program's (`bh step render_packet`), so this hook holds no packet format.
A session that already received this packet (same bytes, session and source) gets nothing again.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c

data = c.load_input()
root = c.project_dir(data)
files = c.packet_files(root)
if not c.is_builder(data) or data.get("source", "startup") == "resume" or not files:
    c.emit()  # resume replays a transcript that already holds the packet
packet = files[0]
key = hashlib.sha256(packet.read_bytes() + f"|{data.get('session_id', '')}|{data.get('source', 'startup')}".encode()).hexdigest()
mark = root / ".brick-harness" / "h1-delivered" / key
if mark.exists():
    c.emit()
bh = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", "")) / "bin" / "bh"
p = subprocess.run([str(bh), "step", "render_packet", "--item", packet.stem], cwd=root, capture_output=True, text=True, timeout=30)
if p.returncode != 0:
    fact, rec = c.record_fact(root, "h1_undelivered", (p.stderr or "the packet did not render").strip()[:400])
    print(json.dumps({"facts": [rec], "run_report": str(fact)}))
    sys.exit(0)
mark.parent.mkdir(parents=True, exist_ok=True)
mark.write_text("")
print(json.dumps({"facts": [], "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": p.stdout}}))
sys.exit(0)
