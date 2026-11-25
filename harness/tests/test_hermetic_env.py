"""The suite is hermetic: a BH_* or ATDD_* variable of the shell that started pytest never reaches a test."""

import os
import subprocess
import sys
from pathlib import Path

STUB = Path(__file__).resolve().parent.parent / "acceptance" / "keywords" / "stub_claude.py"


def test_a_row_stub_counter_in_the_shell_does_not_reach_a_test(tmp_path):
    assert not [n for n in os.environ if n.startswith(("BH_", "ATDD_"))]
    fx = tmp_path / "model.json"
    fx.write_text('{"replies": [{"stdout": "first"}]}')
    p = subprocess.run(
        [sys.executable, str(STUB)],
        env={**os.environ, "ATDD_MODEL_FIXTURE": str(fx)},
        capture_output=True,
        text=True,
    )
    assert (p.returncode, p.stdout) == (0, "first")
