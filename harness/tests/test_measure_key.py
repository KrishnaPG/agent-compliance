"""b2 (R3, QBC-66): the measurement key holds the plan commit's protected files, so a changed plan file
is measured again for the same ref, and a change outside them reuses the result. Row b2-AC9 cannot hold
the measured sha fixed (its plan commit rebases the candidate), so the key itself is checked here."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import bhcore
from test_measure import GIT_ENV, commit

CFG = SimpleNamespace(protected=bhcore.DEFAULT_PROTECTED)


def _head(top: Path, path: str, text: str) -> str:
    (top / path).parent.mkdir(parents=True, exist_ok=True)
    (top / path).write_text(text)
    commit(top)
    return subprocess.run(["git", "-C", str(top), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def test_a_changed_plan_file_changes_the_key_for_the_same_ref(tmp_path):
    sha = _head(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    other_plan = _head(tmp_path, "tests/test_a.py", "def test_a():\n    assert 1 == 1\n")
    assert bhcore._measure_key(tmp_path, sha, sha, CFG, None) != bhcore._measure_key(tmp_path, other_plan, sha, CFG, None)


def test_a_change_outside_the_plan_files_keeps_the_key(tmp_path):
    sha = _head(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    other_base = _head(tmp_path, "src/a.py", "A = 1\n")
    assert bhcore._measure_key(tmp_path, sha, sha, CFG, None) == bhcore._measure_key(tmp_path, other_base, sha, CFG, None)
