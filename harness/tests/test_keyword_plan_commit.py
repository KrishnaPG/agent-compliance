"""git `path_in_plan_commit`: the plan commit is the one whose Packet trailer names the row's packet,
not the branch tip (a later scoreboard or report commit is not the plan commit)."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from then import then_git  # noqa: E402


def _commit(repo: Path, env: dict, path: str, message: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(message + "\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, env=env, check=True)


def test_the_plan_commit_is_found_by_its_packet_trailer_under_later_commits(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.invalid"}
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], env=env, check=True)
    _commit(tmp_path, env, "src/a.py", "base")
    _commit(tmp_path, env, "tests/acceptance/test_item.py", "acceptance item\n\nPacket: item@abc")
    _commit(tmp_path, env, ".brick-harness/gaps.md", "unmet items reported")
    ctx = SimpleNamespace(state={"repo": tmp_path, "env": env, "packet": {"id": "item"}})
    then_git(ctx, **{"assert": "path_in_plan_commit", "path": "tests/acceptance/**"})
    with pytest.raises(AssertionError):
        then_git(ctx, **{"assert": "path_in_plan_commit", "path": "src/**"})


def test_before_the_program_plans_the_plan_commit_is_the_base_tag(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.invalid"}
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], env=env, check=True)
    _commit(tmp_path, env, "tests/acceptance/test_item.py", "base")
    subprocess.run(["git", "tag", "base"], cwd=tmp_path, env=env, check=True)
    _commit(tmp_path, env, "src/a.py", "later")
    ctx = SimpleNamespace(state={"repo": tmp_path, "env": env, "packet": {"id": "item"}})
    then_git(ctx, **{"assert": "path_in_plan_commit", "path": "tests/acceptance/**"})
    with pytest.raises(AssertionError):
        then_git(ctx, **{"assert": "path_in_plan_commit", "path": "src/**"})
