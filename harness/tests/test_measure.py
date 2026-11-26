"""Measurer unit tests: every failure mode fails closed and records raw numbers."""

import json
import os
import subprocess
import sys
from pathlib import Path

import bhcore
import pytest

PY = sys.executable
JUNIT_OK = '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>'


def project(
    tmp_path: Path, test_run: str, targets: list, bench: dict | None = None, timeout: float = 30
) -> bhcore.Config:
    (tmp_path / "bricks.json").write_text(json.dumps({"bricks": [{"id": "a", "job": "x"}]}))
    (tmp_path / "targets.json").write_text(json.dumps({"targets": targets}))
    cmds = {"test": {"run": test_run, "junit": "{out}/junit.xml"}, "timeout_s": timeout}
    if bench:
        cmds["bench"] = bench
    cfg = {
        "paths": {
            "targets": "targets.json",
            "bricks": "bricks.json",
            "catalogue": "cat.json",
            "scoreboard": "sb.json",
            "scoreboard_md": "sb.md",
        },
        "commands": cmds,
        "ecosystems": ["python"],
    }
    (tmp_path / "c.json").write_text(json.dumps(cfg))
    commit(tmp_path)
    return bhcore.Config(tmp_path / "c.json")


GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.invalid",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.invalid",
)


def commit(path: Path) -> None:
    """Measuring is at a commit (HEAD): the project's files are committed before each call."""
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A", "--", "."],
        ["commit", "-qm", "p", "--allow-empty"],
    ):
        subprocess.run(
            ["git", "-C", str(path), *args], check=True, capture_output=True, env=GIT_ENV
        )


def write(text: str) -> str:
    """A shell command that writes `text` to {out}/junit.xml (or a given file)."""
    return f"{PY} -c \"import sys,pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])\" {{out}}/junit.xml '{text}'"


T_OK = [
    {"item": "a", "metric": "tests.failed", "op": "==", "value": 0},
    {"item": "a", "metric": "tests.passed", "op": ">=", "value": 3},
]


def run(cfg):
    """Measure item a at HEAD."""
    return bhcore.measure(cfg, [("a", "HEAD")])["items"]["a"]


MET = "met"


def test_met_when_numbers_meet_targets(tmp_path):
    r = run(project(tmp_path, write(JUNIT_OK), T_OK))
    assert r["status"] == MET, r
    assert r["metrics"]["tests.passed"] == 3


def test_failed_tests_unmet(tmp_path):
    r = run(
        project(tmp_path, write('<testsuite tests="3" failures="1" errors="0" skipped="0"/>'), T_OK)
    )
    assert r["status"] == "unmet"
    assert r["metrics"]["tests.failed"] == 1


def test_zero_tests_collected_unmet(tmp_path):
    r = run(
        project(
            tmp_path, write('<testsuite tests="0" failures="0" errors="0" skipped="0"/>'), [T_OK[0]]
        )
    )
    assert r["status"] == "unmet"
    assert "test: zero tests collected" in r["errors"]


def test_nonzero_exit_unmet_even_with_good_junit(tmp_path):
    r = run(project(tmp_path, write(JUNIT_OK) + " && exit 3", T_OK))
    assert r["status"] == "unmet"
    assert "test: exit 3" in r["errors"]


def test_timeout_unmet(tmp_path):
    r = run(project(tmp_path, f'{PY} -c "import time; time.sleep(5)"', T_OK, timeout=1))
    assert r["status"] == "unmet"
    assert "test: timeout" in r["errors"]


def test_unparseable_junit_unmet(tmp_path):
    r = run(project(tmp_path, write("<not-xml"), T_OK))
    assert r["status"] == "unmet"
    assert any("junit" in e for e in r["errors"])


def test_no_targets_unmet(tmp_path):
    r = run(project(tmp_path, write(JUNIT_OK), []))
    assert r["status"] == "unmet"
    assert "no targets for this item" in r["errors"]


def bench(tmp_path, content, metrics, fmt="json"):
    """A bench command that writes `content` as its result (the measurer unlinks old results)."""
    run = f"{PY} -c \"import sys,pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])\" {{out}}/b.{fmt} '{content}'"
    return {"run": run, "results": f"{{out}}/b.{fmt}", "format": fmt, "metrics": metrics}


def test_bench_json_and_csv_extractors(tmp_path):
    b = bench(tmp_path, json.dumps({"r": [{"p50": 7.5}]}), {"p50_ms": "r.0.p50"})
    t = T_OK + [{"item": "a", "metric": "bench.p50_ms", "op": "<=", "value": 10}]
    assert run(project(tmp_path, write(JUNIT_OK), t, b))["metrics"]["bench.p50_ms"] == 7.5
    csv_path = tmp_path / "b.csv"
    csv_path.write_text("lat,rps\n3,10\n1,30\n2,20\n")
    assert bhcore.extract(csv_path, "csv", "lat:median") == 2
    assert bhcore.extract(csv_path, "csv", "rps:max") == 30
    assert bhcore.extract(csv_path, "csv", "rps") == 10


def test_missing_bench_metric_unmet(tmp_path):
    b = bench(tmp_path, json.dumps({"other": 1}), {"p50_ms": "p50"})
    t = T_OK + [{"item": "a", "metric": "bench.p50_ms", "op": "<=", "value": 10}]
    r = run(project(tmp_path, write(JUNIT_OK), t, b))
    assert r["status"] == "unmet"
    assert "metric bench.p50_ms not measured" in r["errors"]


def test_non_numeric_bench_metric_unmet(tmp_path):
    b = bench(tmp_path, json.dumps({"p50": "fast"}), {"p50_ms": "p50"})
    t = [{"item": "a", "metric": "bench.p50_ms", "op": "<=", "value": 10}]
    r = run(project(tmp_path, write(JUNIT_OK), t, b))
    assert r["status"] == "unmet"


def test_bench_target_without_bench_command_unmet(tmp_path):
    t = T_OK + [{"item": "a", "metric": "bench.p50_ms", "op": "<=", "value": 10}]
    r = run(project(tmp_path, write(JUNIT_OK), t))
    assert "bench targets but no bench command" in r["errors"]


def test_scoreboard_written_and_an_unreadable_board_is_never_overwritten(tmp_path):
    cfg = project(tmp_path, write(JUNIT_OK), T_OK)
    run(cfg)
    sb = tmp_path / "sb.json"
    board, problem = bhcore.read_board(sb)
    assert problem is None and board["items"]["a"]["status"] == MET
    sb.write_text("{not json")
    board, problem = bhcore.read_board(sb)
    assert board["items"] == {} and "unreadable" in problem
    assert bhcore.state(cfg)["bricks"][0]["status"] == "unmeasured"
    with pytest.raises(bhcore.HarnessError, match="unreadable"):
        bhcore.measure(cfg, [("a", "HEAD")])
    with pytest.raises(bhcore.HarnessError, match="unreadable"):
        bhcore.write_scoreboard(cfg, {"a": {"status": "met"}})
    assert sb.read_text() == "{not json"


def test_changed_targets_make_item_stale(tmp_path):
    cfg = project(tmp_path, write(JUNIT_OK), T_OK)
    run(cfg)
    st = bhcore.state(cfg)
    assert st["bricks"][0]["status"] == MET and st["all_met"] is True
    (tmp_path / "targets.json").write_text(json.dumps({"targets": T_OK[:1]}))
    assert bhcore.state(cfg)["bricks"][0]["status"] == "stale"


def test_changed_commands_make_item_stale(tmp_path):
    cfg = project(tmp_path, write(JUNIT_OK), T_OK)
    run(cfg)
    cfg = project(tmp_path, write(JUNIT_OK) + " && true", T_OK)
    assert bhcore.state(cfg)["bricks"][0]["status"] == "stale"


def test_cli_exit_codes(tmp_path, capsys, load_bin):
    m = load_bin("bh-measure")
    project(tmp_path, write(JUNIT_OK), T_OK)
    sys.argv = ["bh-measure", "--config", str(tmp_path / "c.json")]
    assert m.main() == 0
    run_ = json.loads(capsys.readouterr().out)
    assert run_["ok"] is True and run_["items"]["a"]["status"] == MET
    sys.argv = ["bh-measure", "--config", str(tmp_path / "c.json"), "--item", "nope"]
    assert m.main() == 2


def test_unknown_template_braces_left_alone():
    assert bhcore._render("echo {item} {json}", {"item": "a"}) == "echo a {json}"


def test_validator_rejects_bad_config():
    errs = bhcore.schema_errors(
        {"paths": {}, "commands": {}, "ecosystems": [], "bogus": 1},
        bhcore.load_schema("harness.config"),
    )
    assert any("bogus" in e for e in errs)
    assert any("test" in e for e in errs)  # commands.test is required
    assert any("non-empty" in e for e in errs)


@pytest.mark.parametrize("op,a,b,ok", [(">=", 2, 2, True), ("<", 2, 2, False), ("!=", 1, 2, True)])
def test_ops(op, a, b, ok):
    assert bhcore.OPS[op](a, b) is ok


def test_stale_results_from_an_earlier_run_are_not_reused(tmp_path):
    t = T_OK + [{"item": "a", "metric": "bench.p50_ms", "op": "<=", "value": 10}]
    cfg = project(
        tmp_path, write(JUNIT_OK), t, bench(tmp_path, json.dumps({"p50": 1}), {"p50_ms": "p50"})
    )
    assert run(cfg)["status"] == MET
    cfg = project(tmp_path, "true", t, {**bench(tmp_path, "{}", {"p50_ms": "p50"}), "run": "true"})
    r = run(cfg)
    assert r["status"] == "unmet"
    assert "tests.passed" not in r["metrics"] and "bench.p50_ms" not in r["metrics"]


def test_timeout_kills_child_processes(tmp_path):
    import time

    t0 = time.monotonic()
    cmd = f'{PY} -c "import time; time.sleep(30)" & {PY} -c "import time; time.sleep(30)"; wait'
    r = run(project(tmp_path, cmd, T_OK, timeout=1))
    assert "test: timeout" in r["errors"]
    assert time.monotonic() - t0 < 10


def test_pending_command_fails_closed_without_running(tmp_path):
    cfg = project(tmp_path, write(JUNIT_OK) + " && touch ran", T_OK)
    cfg.commands["test"]["pending"] = "runner script not written yet"
    r = run(cfg)
    assert r["status"] == "unmet"
    assert any("not yet present" in e for e in r["errors"])
    assert not (tmp_path / "ran").exists() and r["runs"] == []


# ---- scoring bypasses and crash paths


@pytest.mark.parametrize(
    "content,fmt", [('{"p50": NaN}', "json"), ('{"p50": Infinity}', "json"), ("p50\nnan\n", "csv")]
)
def test_non_finite_bench_metric_unmet(tmp_path, content, fmt):
    b = bench(tmp_path, content, {"p50_ms": "p50"}, fmt)
    t = T_OK + [{"item": "a", "metric": "bench.p50_ms", "op": "!=", "value": 1}]
    r = run(project(tmp_path, write(JUNIT_OK), t, b))
    assert r["status"] == "unmet" and "bench.p50_ms" not in r["metrics"]


def test_non_finite_target_value_rejected(tmp_path):
    cfg = project(tmp_path, write(JUNIT_OK), T_OK)
    (tmp_path / "targets.json").write_text(
        '{"targets": [{"item": "a", "metric": "tests.failed", "op": "!=", "value": NaN}]}'
    )
    with pytest.raises(bhcore.HarnessError, match="non-finite"):
        run(cfg)


def test_nested_testsuites_are_not_double_counted(tmp_path):
    xml = (
        '<testsuites tests="3" failures="0"><testsuite tests="3" failures="0">'
        '<testsuite tests="2" failures="0"/><testsuite tests="1" failures="0"/>'
        "</testsuite></testsuites>"
    )
    p = tmp_path / "j.xml"
    p.write_text(xml)
    assert bhcore.parse_junit(p)["total"] == 3


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="three"/>',
        '<testsuite tests="2.5"/>',
        '<testsuite tests="1" failures="2"/>',
        "<report/>",
    ],
)
def test_odd_junit_is_an_error_not_a_crash(tmp_path, xml):
    p = tmp_path / "j.xml"
    p.write_text(xml)
    with pytest.raises(bhcore.HarnessError):
        bhcore.parse_junit(p)
    r = run(project(tmp_path, write(xml), T_OK))
    assert r["status"] == "unmet" and any("junit" in e for e in r["errors"])


@pytest.mark.parametrize("doc", ["[]", '{"items": []}', "not json"])
def test_malformed_scoreboard_is_a_problem_not_a_crash(tmp_path, doc):
    cfg = project(tmp_path, write(JUNIT_OK), T_OK)
    (tmp_path / "sb.json").write_text(doc)
    assert bhcore.read_board(tmp_path / "sb.json")[1]
    assert bhcore.state(cfg)["problems"]
    with pytest.raises(bhcore.HarnessError):
        run(cfg)


# ---- status table: one record's facts, then current vs candidate

R_MET = {"status": "met", "ref": "a" * 40, "measured_at": "2026-01-01T00:00:01"}
R_UNMET = {"status": "unmet", "ref": "b" * 40, "measured_at": "2026-01-01T00:00:02"}


@pytest.mark.parametrize(
    "r,facts,want",
    [
        (None, {}, None),
        (R_MET, {"digest_ok": False}, "stale"),
        (R_MET, {"resolvable": False}, "stale"),
        ({**R_MET, "status": "conflict"}, {}, "conflict"),
        (R_UNMET, {}, "unmet"),
        (R_MET, {"in_head": False}, "met-unmerged"),
        (R_MET, {"same_tree": False}, "stale"),
        (R_MET, {}, "met"),
    ],
)
def test_record_status_table(r, facts, want):
    assert bhcore.record_status(r, **{"digest_ok": True, **facts}) == want


def test_failed_candidate_never_replaces_a_met_current():
    assert bhcore.pick_status((R_MET, "met"), (R_UNMET, "unmet")) == ("met", R_MET)


def test_newer_record_decides_when_current_is_not_met():
    older_cur = {**R_UNMET, "measured_at": "2026-01-01T00:00:00"}
    assert bhcore.pick_status((older_cur, "unmet"), (R_MET, "met-unmerged"))[0] == "met-unmerged"
    newer_cur = {**R_UNMET, "measured_at": "2026-01-01T00:00:09"}
    assert bhcore.pick_status((newer_cur, "unmet"), (R_MET, "met"))[0] == "unmet"
    assert bhcore.pick_status((None, None), (None, None)) == ("unmeasured", None)


def test_merged_sarif_is_checked_against_the_official_schema(tmp_path):
    ok = tmp_path / "a.sarif"
    ok.write_text(
        json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "ruff"}}}]})
    )
    assert len(bhcore.merge_sarif([ok, ok])["runs"]) == 2
    bad = tmp_path / "b.sarif"
    bad.write_text(json.dumps({"runs": [{"tool": {}}]}))
    with pytest.raises(bhcore.HarnessError, match="SARIF log invalid"):
        bhcore.merge_sarif([bad])


def test_junit_counts_the_cases_a_reporter_writes_under_testsuites(tmp_path):
    """node's test runner writes a test outside a describe straight under <testsuites>: it counts,
    as ``_cases`` lists it (one definition of a report's cases); a suite's own counts still count."""
    node = tmp_path / "node.xml"
    node.write_text('<testsuites><testcase name="a" classname="test"/><testcase name="b" classname="test"><failure message="x"/></testcase></testsuites>')
    assert bhcore.parse_junit(node) == {"total": 2, "failed": 1, "errors": 0, "skipped": 0, "passed": 1}
    empty = tmp_path / "empty.xml"  # negative control: no case anywhere is zero tests
    empty.write_text("<testsuites></testsuites>")
    assert bhcore.parse_junit(empty)["total"] == 0
