"""A real uv project measured sealed: its lockfile install runs before the seal, so its own recipe
(`uv run pytest`) runs in the jail, while the network and every path outside the checkout stay shut."""

import shutil
import subprocess
from pathlib import Path

import bhcore
import pytest

PLUGIN = Path(__file__).resolve().parents[2]
TESTS = '''import socket
from pathlib import Path


def test_plain() -> None:
    assert 1 + 1 == 2


def test_network() -> None:
    socket.create_connection(("1.1.1.1", 443), timeout=5)


def test_write_home() -> None:
    (Path.home() / "bh-seal-probe").write_text("x")
'''


def git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


@pytest.mark.skipif(
    not all(shutil.which(t) for t in ("uv", "just", "bwrap")), reason="needs uv, just and bwrap"
)
def test_a_uv_project_runs_its_own_recipe_sealed(tmp_path, monkeypatch):
    monkeypatch.setenv("MISE_GLOBAL_CONFIG_FILE", str(PLUGIN / ".tool-versions"))
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "0"\nrequires-python = "==3.14.*"\n'
        '[dependency-groups]\ndev = ["pytest==9.0.2"]\n[tool.uv]\npackage = false\n'
    )
    (tmp_path / "justfile").write_text("test:\n    uv run pytest -q\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_p.py").write_text(TESTS)
    (tmp_path / ".gitignore").write_text(".brick-harness/\n.venv/\n")
    subprocess.run(["uv", "lock", "-q"], cwd=tmp_path, check=True)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")

    res = bhcore.measure_ref(bhcore.Config(tmp_path / ".brick-harness" / "config.json", partial=True))

    junit = tmp_path / res["items"][0]["out"] / "junit.xml"
    failed = {c.name for s in bhcore._suites(bhcore.read_junit(junit)) for c in s if c.result}
    assert failed == {"test_network", "test_write_home", "test_bh_canary"}
    suites = bhcore._suites(bhcore.read_junit(junit))  # each check is its own testsuite, named after it
    assert [s.name for s in suites if any(c.name == "test_bh_canary" for c in s)] == ["canary"]
    assert not (Path.home() / "bh-seal-probe").exists()
