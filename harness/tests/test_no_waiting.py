"""No timer or waiting loop of the plugin's own: a wait blocks on the producer's event or a
task's completion (a process exit, a flock, an agent or workflow result), never on sleep,
polling or a retry loop. Any exception must be named here with its reason."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIRS = ("bin", "harness/lib", "harness/workflows", "skills/harness")  # from the plugin root
BANNED = [
    r"\bsleep\b",
    r"\buntil ",
    r"while\s*\(?\s*true",
    r"setTimeout",
    r"setInterval",
    r"watch -n",
    r"time\.sleep",
]
# Named boundaries: text matching one of these is allowed, with the reason.
ALLOWED = {
    r"never sleep(?:,| or) poll": "the instruction to agents that forbids sleeping and polling",
}


@pytest.mark.parametrize("pat", BANNED)
def test_no_sleep_poll_or_wait_loop(pat):
    found = []
    for d in DIRS:
        for p in (ROOT.parent / d).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = str(p.relative_to(ROOT.parent))
                for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                    bare = line
                    for ok in ALLOWED:
                        bare = re.sub(ok, "", bare, flags=re.I)
                    if re.search(pat, bare, re.I):
                        found.append(f"{rel}:{n}: {line.strip()[:80]}")
    assert found == []
