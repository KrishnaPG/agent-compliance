"""Diff facts against the base (b4): the file lists come from git, the counts from the tools' own flags."""

import shutil
import subprocess

import bhcore
import pytest


def git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "gone.py").write_text("y = 1\n")
    (tmp_path / "notes.md").write_text("a\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "tag", "base")
    (tmp_path / "keep.py").write_text("x = 2\n")
    (tmp_path / "new.py").write_text("z = 1\n")
    (tmp_path / "notes.md").write_text("b\n")
    git(tmp_path, "rm", "-q", "gone.py")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "cand")
    return tmp_path


def test_changed_files_are_split_by_where_they_exist(repo):
    at_base, at_cand = bhcore._changed_by_glob(repo, "base", "HEAD", ["*.py"])
    assert sorted(at_base) == ["gone.py", "keep.py"]
    assert sorted(at_cand) == ["keep.py", "new.py"]


def test_one_writer_gives_every_kind_its_teaching():
    facts = []
    for kind in bhcore.DIFF_FACTS:
        bhcore.diff_fact(facts, "i", kind, "d")
    assert [f["kind"] for f in facts] == list(bhcore.DIFF_FACTS)
    assert all("->" in f["message"] and f["item"] == "i" for f in facts)


@pytest.mark.skipif(not shutil.which("ruff"), reason="ruff is not installed")
def test_inline_suppression_is_counted_with_ruffs_own_flag(tmp_path):
    (tmp_path / "a.py").write_text("import os  # noqa: F401\nimport sys\n")
    view = bhcore._lint_view(tmp_path, {"ruff": ["a.py"], "eslint": []}, dict(__import__("os").environ), [], None)
    assert view == {"suppressed": 1, "ts_comment": 0}


def test_case_ids_leave_the_canary_out_and_count_skips():
    from junitparser import Skipped, TestCase

    ok, skipped, canary = TestCase("test_a", "m"), TestCase("test_b", "m"), TestCase("test_bh_canary", "c")
    skipped.result = [Skipped()]
    assert bhcore._case_ids([ok, skipped, canary]) == ({"m::test_a", "m::test_b"}, 1)
