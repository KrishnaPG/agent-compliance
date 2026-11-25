"""Plain pytest acceptance of the generic test generator (atdd_engine): the bootstrap, as for b1.

A tiny catalog, rows and keyword library are written to a temp dir; the engine generates tests from them and the
generated tests are run in a subprocess, so the red/error classification is checked on real JUnit XML.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
from atdd_engine import generate as g  # noqa: E402
from atdd_engine import report, teaching  # noqa: E402

CATALOG = {"given": {"thing": {}}, "when": {"act": {}}, "then": {"is_ok": {}, "boom": {}, "missing": {}, "needs_keyword": {}, "vague": {}}}
ROWS = {"slice": "z", "criteria": [
    {"id": "z1-AC1", "scenario": "green", "given": [{"thing": {"x": 1}}], "when": {"act": {}}, "then": [{"is_ok": {"v": True}}]},
    {"id": "z1-AC2", "scenario": "red by assertion", "given": [], "when": {"act": {}}, "then": [{"is_ok": {"v": False}}]},
    {"id": "z1-AC3", "scenario": "red: the tree lacks something", "given": [], "when": {"act": {}}, "then": [{"missing": {}}]},
    {"id": "z1-AC4", "scenario": "error: keyword raises", "given": [], "when": {"act": {}}, "then": [{"boom": {}}]},
    {"id": "z1-AC5", "scenario": "needs a keyword", "given": [], "when": {"act": {}}, "then": [{"needs_keyword": {"reason": "none fits"}}]},
    {"id": "z1-AC6", "scenario": "ambiguous", "given": [], "when": {"act": {}}, "then": [{"vague": {}}]},
]}
LIBRARY = '''
from atdd_engine.runtime import Missing
def thing(ctx, x): ctx.state["x"] = x
def act(ctx): ctx.last = "done"
def is_ok(ctx, v): assert v, "v is false"
def boom(ctx): raise RuntimeError("keyword is broken")
def missing(ctx): raise Missing("the tree has no such command")
GIVEN = {"thing": thing}; WHEN = {"act": act}
THEN = {"is_ok": is_ok, "boom": boom, "missing": missing}
def AMBIGUOUS(kind, key, params): return "undefined" if key == "vague" else None
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "criteria").mkdir()
    (tmp_path / "criteria" / "z.yaml").write_text(yaml.safe_dump(ROWS))
    (tmp_path / "catalog.yaml").write_text(yaml.safe_dump(CATALOG))
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "__init__.py").write_text(LIBRARY)
    (tmp_path / "fx").mkdir()
    return tmp_path


def gen(p):
    return g.generate(p / "catalog.yaml", p / "criteria", p / "lib", p / "fx", p / "out")


def test_one_test_per_row_and_manifest_maps_each(project):
    files = gen(project)
    manifest = json.loads(files["manifest.json"])["criteria"]
    assert sorted(manifest) == ["z1-AC1", "z1-AC2", "z1-AC3", "z1-AC4"]
    assert len({m["node"] for m in manifest.values()}) == 4
    assert files["test_z.py"].count("@pytest.mark.criterion(") == 4
    skipped = json.loads(files["not_generated.json"])
    assert skipped["z1-AC5"]["reason"].startswith("needs_keyword") and skipped["z1-AC6"]["reason"].startswith("ambiguous")


def test_regeneration_is_identical_bytes(project):
    assert gen(project) == gen(project)


def test_check_reports_stale_hand_edited_and_extra_with_teaching_shape(project):
    files = gen(project)
    g.write(files, project / "out")
    assert g.check(files, project / "out") == []
    (project / "out" / "test_z.py").write_text("# hand edit\n")
    (project / "out" / "test_extra.py").write_text("def test_x(): pass\n")
    (project / "out" / "manifest.json").unlink()
    report_lines = g.check(files, project / "out")
    assert len(report_lines) == 3
    for line in report_lines:
        assert len(line) <= teaching.MAX_CHARS
        assert teaching.parse(line)["right"]


def test_teach_is_at_most_300_chars_and_keeps_the_lesson():
    m = teaching.teach("R-1", "w" * 500, "do the right thing", "docs/x.md")
    assert len(m) <= 300 and "do the right thing" in m and m.endswith("docs/x.md")


def test_teaching_match_binds_identifier_tokens():
    msg = "[R-1] file tests/x.py was edited -> restore it . docs/spec.md"
    assert teaching.match(msg, "tests/x.py edited", "restore it", "keep tests/x.py") is None
    assert "docs/other.md" in teaching.match(msg, "x", "y", "see docs/other.md")
    assert teaching.match("no shape here", "a", "b", "c")


def test_red_by_assertion_versus_error_in_junit(project, tmp_path):
    g.write(gen(project), project / "out")
    xml = tmp_path / "j.xml"
    subprocess.run([sys.executable, "-m", "pytest", str(project / "out"), "--tree", str(project), "-p", "no:cacheprovider", "-q", f"--junitxml={xml}"], capture_output=True)
    res = report.outcomes(xml, project / "out" / "manifest.json")
    assert {k: v["outcome"] for k, v in res.items()} == {"z1-AC1": "green", "z1-AC2": "red", "z1-AC3": "red", "z1-AC4": "error"}


def test_a_missing_tree_is_an_error_not_a_failure(project, tmp_path):
    g.write(gen(project), project / "out")
    xml = tmp_path / "j.xml"
    subprocess.run([sys.executable, "-m", "pytest", str(project / "out"), "-p", "no:cacheprovider", "-q", f"--junitxml={xml}"], capture_output=True, env={"PATH": "/usr/bin:/bin"})
    assert {v["outcome"] for v in report.outcomes(xml, project / "out" / "manifest.json").values()} == {"error"}


def test_duplicate_row_ids_are_refused_with_teaching(project):
    rows = dict(ROWS, criteria=ROWS["criteria"] + [ROWS["criteria"][0]])
    (project / "criteria" / "z.yaml").write_text(yaml.safe_dump(rows))
    with pytest.raises(g.Refusal) as e:
        gen(project)
    assert teaching.parse(str(e.value))
