"""d3: ``bh check`` is the measurer's code on a snapshot of the working tree, inside the builder's own sandbox."""

import json
import os
import subprocess
import sys
from pathlib import Path

import bhcore
import pytest

BH = Path(__file__).resolve().parents[2] / "bin" / "bh"
ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.invalid",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.invalid",
)
PACKET = {
    "id": "item",
    "acceptance": [{"id": "item-AC1"}],
    "verifier": {
        "checks": ["pytest -q tests/acceptance", "python3 lint.py"],
        "rules": [
            {"id": "LNT-1", "message": "[LNT-1] bad value -> use a good value . run bh check"}
        ],
    },
}


def git(repo, *a):
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tests" / "acceptance").mkdir(parents=True)
    (tmp_path / "tests" / "acceptance" / "test_item.py").write_text(
        "def test_item_AC1():\n    assert True\n"
    )
    (tmp_path / "lint.py").write_text("print('fine')\n")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    packets = tmp_path / ".brick-harness" / "packets"
    packets.mkdir(parents=True)
    (packets / "item.json").write_text(json.dumps(PACKET))
    return tmp_path


def check(repo):
    env = {k: v for k, v in ENV.items() if k != "BH_ORCHESTRATOR_DIR"}
    p = subprocess.run(
        [sys.executable, str(BH), "check"], cwd=repo, capture_output=True, text=True, env=env
    )
    return p.returncode, p.stdout.splitlines()[:-1], json.loads(p.stdout.splitlines()[-1])


def test_snapshot_holds_the_working_tree_and_touches_no_ref_or_index(repo):
    (repo / "new.py").write_text("x = 1\n")
    (repo / "lint.py").write_text("print('changed')\n")
    (repo / ".brick-harness" / "out").mkdir()
    (repo / ".brick-harness" / "out" / "noise").write_text("n")
    before = (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"))
    sha = bhcore.snapshot_working_tree(repo)
    assert (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")) == before
    files = git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
    assert "new.py" in files and "lint.py" in files
    assert not [f for f in files if f.startswith((".brick-harness/out", ".brick-harness/packets"))]
    assert git(repo, "show", f"{sha}:lint.py") == "print('changed')"


def test_check_runs_exactly_the_packet_list_and_states_what_it_skips(repo):
    code, lines, res = check(repo)
    assert code == 0
    assert res["command"] == "check"
    assert res["checks_run"] == PACKET["verifier"]["checks"] and res["checks_missed"] == []
    assert any("fresh-stack" in ln for ln in lines)


def test_a_missed_check_prints_the_rules_message_named_in_its_output(repo):
    (repo / "lint.py").write_text("print('LNT-1 here')\nraise SystemExit(1)\n")
    code, lines, res = check(repo)
    assert code == 1
    assert res["checks_missed"] == ["python3 lint.py"]
    assert PACKET["verifier"]["rules"][0]["message"] in lines


def test_check_takes_no_lock_and_does_not_read_the_run_lock(repo):
    (repo / ".brick-harness" / "run.lock").write_text("held\n")
    assert check(repo)[0] == 0
