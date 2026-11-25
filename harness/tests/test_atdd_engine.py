"""Plain pytest acceptance of the row plugin (atdd_engine.plugin): the bootstrap, as for b1.

A tiny set of rows and a keyword library are written to a temp dir and collected by the plugin in a subprocess,
so the red/error classification and the row ids are checked on real JUnit XML.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
from atdd_engine import report, teaching  # noqa: E402

ROWS = {"slice": "z", "acceptance": [
    {"id": "z1-AC1", "scenario": "green", "given": [{"thing": {"x": 1}}], "when": {"act": {}}, "then": [{"is_ok": {"v": True}}]},
    {"id": "z1-AC2", "scenario": "red by assertion", "given": [], "when": {"act": {}}, "then": [{"is_ok": {"v": False}}]},
    {"id": "z1-AC3", "scenario": "red: the tree lacks something", "given": [], "when": {"act": {}}, "then": [{"missing": {}}]},
    {"id": "z1-AC4", "scenario": "error: keyword raises", "given": [], "when": {"act": {}}, "then": [{"boom": {}}]},
    {"id": "z1-AC5", "scenario": "needs a keyword", "given": [], "when": {"act": {}}, "then": [{"needs_keyword": {"reason": "none fits"}}]},
    {"id": "z1-AC6", "scenario": "ambiguous", "given": [], "when": {"act": {}}, "then": [{"vague": {}}]},
    {"id": "z1-AC7", "scenario": "approved output", "given": [], "when": {"act": {}}, "then": [{"snap": {}}]},
]}
LIBRARY = '''
from atdd_engine.runtime import Missing
def thing(ctx, x): ctx.state["x"] = x
def act(ctx): return "done"
def is_ok(ctx, v): assert v, "v is false"
def boom(ctx): raise RuntimeError("keyword is broken")
def missing(ctx): raise Missing("the tree has no such command")
def snap(ctx): assert ctx.snapshot(name="out") == ctx.last.encode()
GIVEN = {"thing": thing}; WHEN = {"act": act}
THEN = {"is_ok": is_ok, "boom": boom, "missing": missing, "snap": snap}
def AMBIGUOUS(kind, key, params): return "undefined" if key == "vague" else None
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "criteria").mkdir()
    (tmp_path / "criteria" / "z.yaml").write_text(yaml.safe_dump(ROWS))
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "__init__.py").write_text(LIBRARY)
    (tmp_path / "fx").mkdir()
    return tmp_path


def run(p, *extra, tree=True):
    xml = p / "j.xml"
    cmd = [sys.executable, "-m", "pytest", "-p", "atdd_engine.plugin", str(p / "criteria"), "-p", "no:cacheprovider", "-q",
           "--atdd-keywords", str(p / "lib"), "--atdd-fixtures", str(p / "fx"), f"--junitxml={xml}", *extra]
    if tree:
        cmd += ["--tree", str(p)]
    r = subprocess.run(cmd, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(LIB)}, cwd=p)
    return {k: v["outcome"] for k, v in report.outcomes(xml, p / "criteria").items()}, r


def test_one_test_per_row_with_its_id_in_the_node_id_and_property(project):
    outcomes, r = run(project, "--collect-only")
    assert sorted(outcomes) == [f"z1-AC{i}" for i in range(1, 8)]
    assert all(f"z.yaml::z1-AC{i}\n" in r.stdout for i in range(1, 8))


def test_red_by_assertion_versus_error_in_junit(project):
    outcomes, _ = run(project)
    assert {k: outcomes[k] for k in ("z1-AC1", "z1-AC2", "z1-AC3", "z1-AC4")} == {"z1-AC1": "green", "z1-AC2": "red", "z1-AC3": "red", "z1-AC4": "error"}


def test_rows_that_cannot_run_as_written_are_skipped_with_the_reason(project):
    outcomes, r = run(project, "-rs")
    assert outcomes["z1-AC5"] == outcomes["z1-AC6"] == "skipped"
    assert "needs_keyword: none fits" in r.stdout and "ambiguous" not in outcomes.values()


def test_a_missing_tree_is_an_error_not_a_failure(project):
    outcomes, _ = run(project, tree=False)
    assert {outcomes[k] for k in ("z1-AC1", "z1-AC2", "z1-AC3", "z1-AC4", "z1-AC7")} == {"error"}


def test_snapshot_is_red_until_approved_and_never_recorded_automatically(project):
    assert run(project)[0]["z1-AC7"] == "red"
    assert not (project / "fx" / "snapshots").exists()
    run(project, "--snapshot-update")  # the owner's explicit approval
    assert (project / "fx" / "snapshots" / "z" / "z1-AC7[out].txt").read_bytes() == b"done"
    assert run(project)[0]["z1-AC7"] == "green"


def test_teach_is_at_most_300_chars_and_keeps_the_lesson():
    m = teaching.teach("R-1", "w" * 500, "do the right thing", "docs/x.md")
    assert len(m) <= 300 and "do the right thing" in m and m.endswith("docs/x.md")


def test_teaching_match_binds_identifier_tokens():
    msg = "[R-1] file tests/x.py was edited -> restore it . docs/spec.md"
    assert teaching.match(msg, "tests/x.py edited", "restore it", "keep tests/x.py") is None
    assert "docs/other.md" in teaching.match(msg, "x", "y", "see docs/other.md")
    assert teaching.match("no shape here", "a", "b", "c")
