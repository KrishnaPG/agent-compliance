"""Ranking, report and limit safeguards (SG-03, SG-04, SG-08, SG-11 to SG-14).

None of them gates: ranking orders and drops nothing, facts change no status, limits list
what is left. The toy project is the fixture.
"""

import json
import subprocess
import sys
from pathlib import Path

import bhcore
import pytest
from test_toy import BIN, ENV, cli, commit_all, copy_toy, full_state, git, status

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def rank(args, stdin=None, cwd=None):
    p = subprocess.run(
        [sys.executable, str(BIN / "bh-rank"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=ENV,
    )
    return p.returncode, json.loads(p.stdout)


def cfg_of(repo):
    return bhcore.Config(repo / ".brick-harness" / "config.json")


def edit_json(path, fn):
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d, indent=1))


# ---------------------------------------------------------------- SG-12: ranking


def test_rank_sorts_by_impact_then_severity_then_evidence_and_drops_nothing():
    f = [
        {"id": "a", "summary": "no fields"},
        {"id": "b", "severity": "S1", "evidence": "theoretical", "impact": []},
        {"id": "c", "severity": "S4", "evidence": "reproduced", "impact": ["t1"]},
        {"id": "d", "severity": "S2", "evidence": "theoretical", "impact": ["t1"]},
        {"id": "e", "severity": "S2", "evidence": "reproduced", "impact": ["t1"]},
        {"id": "f", "severity": "S4", "evidence": "trigger", "impact": ["t1", "t2"]},
        {"id": "g", "severity": "S2", "evidence": "reproduced", "impact": ["t1", "t1"]},
    ]
    code, out = rank(["--input", "-"], json.dumps(f))
    assert code == 0
    assert [x["id"] for x in out["findings"]] == ["f", "e", "g", "d", "c", "b", "a"]
    assert [x["rank"] for x in out["findings"]] == list(range(1, 8))
    assert "impact" in out["key"]


def test_rank_input_forms_and_errors():
    code, out = rank(["--input", "-"], json.dumps({"findings": [{"id": "x", "summary": "s"}]}))
    assert code == 0 and len(out["findings"]) == 1
    code, out = rank(["--input", "-"], json.dumps({"gaps": [{"id": "y"}]}))
    assert code == 0 and out["findings"][0]["id"] == "y"
    code, out = rank(["--input", "-"], "")
    assert code == 0 and out["findings"] == []
    code, out = rank(["--input", "-"], '"not a list"')
    assert code == 2 and "list" in out["error"]


def test_a_gap_ranks_by_its_proof_like_a_finding_ranks_by_its_evidence():
    key = bhcore.rank_key
    assert key({"id": "1", "proof": "reproduced"}) < key({"id": "1", "proof": "theoretical"})
    assert key({"id": "1", "evidence": "trigger"}) < key({"id": "1", "evidence": "theoretical"})
    # a gap's evidence is a list of file:line, which is not an evidence level
    assert key({"id": "1", "evidence": [{"file": "x", "line": 1}], "proof": "trigger"}) == key(
        {"id": "1", "proof": "trigger"}
    )


def test_findings_are_recorded_in_gaps_json_apart_from_spec_gaps(toy):
    cfgp = str(toy / ".brick-harness" / "config.json")
    found = [
        {
            "summary": "overflow on empty input",
            "severity": "S2",
            "evidence": "reproduced",
            "impact": ["json-writer.tests"],
            "rule": "PR-01",
            "where": "features.md:8",
        },
        {"summary": "naming", "severity": "S4"},
    ]
    code, r = rank(["--config", cfgp, "--add", "-"], json.dumps(found))
    assert code == 0 and r["written"] == [] and r["dry_run"]
    assert not (toy / ".brick-harness" / "gaps.json").exists()  # printing writes nothing
    code, r = rank(["--config", cfgp, "--add", "-", "--write"], json.dumps(found))
    assert r["written"] == [".brick-harness/gaps.json", ".brick-harness/gaps.md"]
    assert [f["severity"] for f in r["findings"]] == ["S2", "S4"]
    assert not (toy / ".brick-harness" / "findings.json").exists()  # one place, no second file
    doc = json.loads((toy / ".brick-harness" / "gaps.json").read_text())
    assert bhcore.validate(doc, bhcore.load_schema("gaps")) == []
    stored = [g for g in doc["gaps"] if g["source"] == "finding"]
    assert (
        len(stored) == 2
        and stored[0]["proof"] == "reproduced"
        and stored[0]["evidence"] == [{"file": "features.md", "line": 8}]
    )
    assert doc["counts"] == {"owner-decides": 0, "fixable": 0}  # spec gap counts exclude findings
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    assert "## Findings" in md and "overflow on empty input" in md.split("## Findings")[1]
    assert "overflow" not in md.split("## Findings")[0]
    _, ranked = rank(["--config", cfgp])
    assert [f["summary"] for f in ranked["findings"]] == ["overflow on empty input", "naming"]
    # a bh-gaps run keeps them and recomputes the mechanical gaps around them
    _, g = cli("bh-gaps", toy, "--write")
    assert len([x for x in g["gaps"] if x["source"] == "finding"]) == 2
    _, s = full_state(toy)
    assert ".brick-harness/gaps.json" in s["uncommitted"]
    code, c = cli("bh-commit", toy, "--message", "findings")
    assert ".brick-harness/gaps.json" in c["files"]


def test_a_repeated_finding_replaces_itself_so_a_re_review_can_close_it(toy):
    args = ["--config", str(toy / ".brick-harness" / "config.json")]
    f = {"id": "r:1", "summary": "x", "severity": "S3"}
    rank([*args, "--add", "-", "--write"], json.dumps([f]))
    rank(
        [*args, "--add", "-", "--write"],
        json.dumps([{**f, "state": "closed"}, {"id": "r:2", "summary": "y"}]),
    )
    _, allf = rank(args)
    _, opn = rank([*args, "--open"])
    assert {x["id"] for x in allf["findings"]} == {"r:1", "r:2"}  # nothing dropped
    assert [x["id"] for x in opn["findings"]] == ["r:2"]


def test_a_malformed_finding_is_an_error_and_writes_nothing(toy):
    args = ["--config", str(toy / ".brick-harness" / "config.json")]
    code, r = rank(
        [*args, "--add", "-", "--write"], json.dumps([{"summary": "x", "severity": "S9"}])
    )
    assert code == 2 and "S9" in r["error"]
    assert not (toy / ".brick-harness" / "gaps.json").exists()


def test_findings_schema_agrees_with_jsonschema():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("finding")
    jsonschema.Draft202012Validator.check_schema(s)
    good = {
        "findings": [{"summary": "x", "severity": "S1", "evidence": "trigger", "impact": ["t"]}]
    }
    bad = {"findings": [{"summary": "x", "evidence": "sure"}]}
    assert jsonschema.Draft202012Validator(s).is_valid(good) and bhcore.validate(good, s) == []
    assert not jsonschema.Draft202012Validator(s).is_valid(bad) and bhcore.validate(bad, s)


def test_build_rounds_work_only_on_items_with_unmet_measured_targets(toy):
    """A finding is never work by itself: only items the measurer reports unmet are ready."""
    _, s = full_state(toy)
    assert {b["id"]: b["status"] for b in s["bricks"]}["csv-reader"] == "unmeasured"
    cli("bh-measure", toy, "--item", "csv-reader")
    cli("bh-commit", toy, "--message", "scoreboard")
    cli("bh-measure", toy, "--item", "json-writer")
    cli("bh-commit", toy, "--message", "scoreboard")
    st, s = status(toy)
    assert st["csv-reader"] == "met" and st["json-writer"] == "unmet"
    assert s["ready"] == ["json-writer"]
    assert s["bricks"][1]["last"]["unmet"], "an item is rebuilt with the numbers it missed"
    # findings change nothing about what is ready
    args = ["--config", str(toy / ".brick-harness" / "config.json"), "--write"]
    rank(
        [*args, "--add", "-"],
        json.dumps(
            [
                {
                    "summary": "csv-reader is ugly",
                    "severity": "S1",
                    "evidence": "reproduced",
                    "impact": ["csv-reader.tests"],
                }
            ]
        ),
    )
    st2, s2 = status(toy)
    assert st2 == st and s2["ready"] == ["json-writer"]


# ---------------------------------------------------------------- SG-13: re-review input


GAP = {
    "kind": "contradiction",
    "summary": "rows/s stated twice",
    "tag": "owner-decides",
    "severity": "S2",
    "proof": "trigger",
    "impact": ["json-writer.rows_per_s"],
    "rule": "PR-01",
    "evidence": [{"file": "features.md", "line": 8, "quote": "20,000 rows/s"}],
}


def test_re_review_is_given_the_diff_since_the_last_review_and_the_open_findings(toy):
    args = ["--config", str(toy / ".brick-harness" / "config.json")]
    _, first = rank([*args, "--review-input"])
    assert (
        first["since"] is None
        and first["changed"] == []
        and first["diff"] == ""
        and first["open"] == []
    )
    src = toy / "found.json"
    src.write_text(json.dumps([GAP]))
    _, r = cli("bh-gaps", toy, "--add", str(src), "--write")  # a review's write records its head
    assert r["written"] == [".brick-harness/gaps.json", ".brick-harness/gaps.md"]
    reviewed = git(toy, "rev-parse", "HEAD")
    assert (
        json.loads((toy / ".brick-harness" / "gaps.json").read_text())["reviewed_head"] == reviewed
    )
    (toy / "features.md").write_text((toy / "features.md").read_text() + "\nNew paragraph.\n")
    (toy / "stack.json").write_text((toy / "stack.json").read_text())  # unchanged document
    commit_all(toy, "docs", "features.md")
    _, second = rank([*args, "--review-input"])
    assert second["since"] == reviewed and second["head"] == git(toy, "rev-parse", "HEAD")
    assert second["changed"] == ["features.md"] and "+New paragraph." in second["diff"]
    assert "stack.json" not in second["diff"] and "PLAN.md" not in second["diff"]
    assert [o["summary"] for o in second["open"]] == ["rows/s stated twice"]
    assert second["open"][0]["severity"] == "S2" and second["open"][0]["where"] == "features.md:8"
    assert not second["diff_truncated"]


def test_re_review_diff_is_capped_and_says_so(toy, monkeypatch):
    args = ["--config", str(toy / ".brick-harness" / "config.json")]
    cli("bh-gaps", toy, "--add", "/dev/null", "--write")
    (toy / "features.md").write_text((toy / "features.md").read_text() + "x" * 500 + "\n")
    monkeypatch.setattr(bhcore, "REVIEW_DIFF_CAP", 100)
    got = bhcore.review_input(cfg_of(toy))
    assert len(got["diff"]) == 100 and got["diff_truncated"] and got["changed"] == ["features.md"]
    assert rank([*args, "--review-input"])[1]["since"] == got["since"]


def test_sg13_is_met_by_the_input_not_by_asking_the_reviewer_to_behave():
    s = json.loads((ROOT / "safeguards.json").read_text())["safeguards"]
    sg13 = next(e for e in s if e["id"] == "SG-13")
    assert {m["kind"] for m in sg13["mechanism"]} == {"structure"}


# ---------------------------------------------------------------- SG-11: gaps in rank order


def test_gaps_report_lists_every_gap_in_rank_order(toy):
    ev = [{"file": "features.md", "line": 8, "quote": "20,000 rows/s"}]
    found = [
        {"kind": "other", "summary": "zz unranked", "tag": "fixable", "evidence": ev},
        {
            "kind": "other",
            "summary": "aa minor",
            "tag": "fixable",
            "evidence": ev,
            "severity": "S4",
            "proof": "reproduced",
        },
        {
            "kind": "other",
            "summary": "mm touches targets",
            "tag": "owner-decides",
            "evidence": ev,
            "severity": "S3",
            "proof": "theoretical",
            "impact": ["t1"],
        },
        {
            "kind": "other",
            "summary": "bb severe",
            "tag": "fixable",
            "evidence": ev,
            "severity": "S1",
            "proof": "trigger",
        },
    ]
    src = toy / "found.json"
    src.write_text(json.dumps(found))
    _, r = cli("bh-gaps", toy, "--add", str(src), "--write")
    assert r["accepted"] == 4 and r["rejected"] == []
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    order = [md.index(s) for s in ("mm touches targets", "bb severe", "aa minor", "zz unranked")]
    assert order == sorted(order)
    assert all(g["summary"] in md for g in r["gaps"])  # nothing dropped
    on_disk = json.loads((toy / ".brick-harness" / "gaps.json").read_text())
    assert bhcore.validate(on_disk, bhcore.load_schema("gaps")) == []


# ---------------------------------------------------------------- SG-03: settled decisions


def test_reopens_are_listed_in_their_own_section_and_nothing_is_decided(toy):
    edit_json(
        toy / ".brick-harness" / "config.json",
        lambda c: c.setdefault("standards", {}).update(
            {"decisions": ["decisions/0001-python-stdlib.md"]}
        ),
    )
    ev = [{"file": "features.md", "line": 8, "quote": "20,000 rows/s"}]
    found = [
        {
            "kind": "contradiction",
            "summary": "stdlib-only is too strict",
            "tag": "owner-decides",
            "evidence": ev,
            "reopens": "decisions/0001-python-stdlib.md",
        },
        {"kind": "other", "summary": "ordinary gap", "tag": "fixable", "evidence": ev},
    ]
    src = toy / "found.json"
    src.write_text(json.dumps(found))
    before = status(toy)[0]
    _, r = cli("bh-gaps", toy, "--add", str(src), "--write")
    assert r["accepted"] == 2 and r["rejected"] == []  # no tool accepts or rejects a reopen
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    head, _, reopens = md.partition("## Reopens")
    assert "stdlib-only is too strict" in reopens and "decisions/0001-python-stdlib.md" in reopens
    assert "features.md:8" in reopens  # its evidence
    assert "ordinary gap" in head and "stdlib-only" not in head
    assert status(toy)[0] == before  # a fact: no status moved
    assert "## Reopens" not in bhcore.render_gaps_md(
        {"counts": {"owner-decides": 0, "fixable": 0}, "gaps": []}
    )


def test_config_standards_decisions_validate():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("harness.config")
    c = json.loads((ROOT / "examples" / "toy" / ".brick-harness" / "config.json").read_text())
    c["standards"] = {"decisions": ["docs/adr/0001.md"]}
    assert jsonschema.Draft202012Validator(s).is_valid(c) and bhcore.validate(c, s) == []
    c["standards"] = {"decisions": "docs/adr"}
    assert not jsonschema.Draft202012Validator(s).is_valid(c)


# ---------------------------------------------------------------- SG-14: sizing notes


def test_the_toy_without_sizing_fields_has_no_sizing_notes_and_stays_valid(toy):
    _, r = cli("bh-gaps", toy)
    assert r["sizing_notes"] == [] and r["problems"] == []
    assert "## Sizing notes" not in bhcore.render_gaps_md({**r, "gaps": r["gaps"]})


def test_bricks_schema_sizing_fields_are_optional_and_typed():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("bricks")
    ok = {
        "bricks": [
            {
                "id": "a",
                "job": "j",
                "purpose": "p",
                "hides": "h",
                "interface": "i",
                "consumers": ["b"],
                "est_loc": 200,
                "oss_checked": [{"tool": "t", "version": "1", "fits": False, "lacks": "x"}],
            }
        ]
    }
    assert jsonschema.Draft202012Validator(s).is_valid(ok) and bhcore.validate(ok, s) == []
    ok["bricks"][0]["est_loc"] = -1
    assert not jsonschema.Draft202012Validator(s).is_valid(ok) and bhcore.validate(ok, s)


# ---------------------------------------------------------------- SG-04: target history


def res(status, **targets):
    return {
        "status": status,
        "ref": "r",
        "targets": [
            {"metric": k, "op": ">=", "value": 1, "actual": 0, "met": v} for k, v in targets.items()
        ],
    }


def feed(cfg, steps):
    for item, r in steps:
        bhcore.record_history(cfg, {item: r})


def test_measuring_records_each_targets_result_per_item_in_out(toy):
    cli("bh-measure", toy, "--item", "csv-reader")
    cli("bh-measure", toy, "--item", "json-writer")
    rows = bhcore.read_history(cfg_of(toy))
    assert [r["item"] for r in rows] == ["csv-reader", "json-writer"] and [
        r["seq"] for r in rows
    ] == [1, 2]
    assert rows[0]["current"] and rows[0]["status"] == "met" and rows[0]["targets"]
    assert all(isinstance(v, bool) for r in rows for v in r["targets"].values())
    assert (toy / ".brick-harness" / "out" / "history.json").exists()  # ignored out/, not committed
    assert git(toy, "check-ignore", ".brick-harness/out/history.json")


def test_a_target_that_went_met_to_unmet_after_another_items_change_twice_is_oscillating(toy):
    cfg = cfg_of(toy)
    feed(
        cfg,
        [
            ("a", res("met", t=True)),
            ("b", res("unmet", u=False)),
            ("b", res("met", u=True)),
            ("a", res("unmet", t=False)),  # regression 1, after b went met
            ("a", res("met", t=True)),
            ("b", res("unmet", u=False)),
            ("b", res("met", u=True)),
            ("a", res("unmet", t=False)),  # regression 2
        ],
    )
    osc = bhcore.oscillating(bhcore.read_history(cfg))
    assert osc == [{"item": "a", "target": "t >= 1", "regressions": 2, "changed_by": ["b"]}]
    assert bhcore.state(cfg)["oscillating"] == osc


def test_one_regression_or_a_regression_after_no_other_change_is_not_oscillation(toy):
    cfg = cfg_of(toy)
    feed(
        cfg,
        [
            ("a", res("met", t=True)),
            ("a", res("unmet", t=False)),
            ("a", res("met", t=True)),
            ("a", res("unmet", t=False)),
        ],
    )
    assert bhcore.oscillating(bhcore.read_history(cfg)) == []  # nothing else changed in between
    feed(
        cfg,
        [
            ("b", res("met", u=True)),
            ("a", res("met", t=True)),
            ("b", res("unmet", u=False)),
            ("b", res("met", u=True)),
            ("a", res("unmet", t=False)),
        ],
    )
    assert (
        bhcore.oscillating(bhcore.read_history(cfg)) == []
    )  # one regression after b's change only


def test_candidates_do_not_count_and_history_is_bounded_and_survives_a_bad_file(toy):
    cfg = cfg_of(toy)
    for _ in range(bhcore.HISTORY_CAP + 5):
        bhcore.record_history(cfg, {"a": res("met", t=True)})
    assert len([r for r in bhcore.read_history(cfg) if r["item"] == "a"]) == bhcore.HISTORY_CAP
    bhcore.history_path(cfg).write_text("not json")
    assert bhcore.read_history(cfg) == [] and bhcore.oscillating([]) == []
    bhcore.record_history(cfg, {"a": res("met", t=True)}, current=False)  # no error
    assert bhcore.oscillating(bhcore.read_history(cfg)) == []


def test_oscillating_items_are_derived_by_bh_gaps_with_both_items_named(toy):
    """SG-04 with SG-15 M2: stuck is computed by the tool from the files and the target
    history; the workflow passes only what the run attempted."""
    cfg = cfg_of(toy)
    both = [("csv-reader", res("met", t=True)), ("json-writer", res("unmet", u=False))]
    again = [("json-writer", res("met", u=True)), ("csv-reader", res("unmet", t=False))]
    feed(cfg, both + again + [("csv-reader", res("met", t=True))] + both[1:] + again)
    rows = {r["item"]: r for r in bhcore.stuck_rows(cfg, ["csv-reader:unmet"], every=True)}
    assert rows["csv-reader"]["reason"] == "oscillating"
    assert rows["csv-reader"]["oscillating_with"] == ["json-writer"]
    assert rows["json-writer"]["reason"] == "not-attempted"
    assert rows["csv2json"]["reason"] == "not-attempted"
    # a run that ended on its budget before the rebuild says so, whatever the history shows
    rows = {r["item"]: r for r in bhcore.stuck_rows(cfg, ["csv-reader:budget"], every=True)}
    assert rows["csv-reader"]["reason"] == "budget"
    gaps = bhcore.unmet_gaps(cfg, ["csv-reader:unmet"], every=True)
    assert "json-writer" in [g for g in gaps if " csv-reader " in g["summary"]][0]["summary"]
    assert "oscillating" in bhcore.STUCK_REASONS and "budget" in bhcore.STUCK_REASONS


# ---------------------------------------------------------------- SG-08: budgets and the round limit


def test_config_budgets_and_sizing_validate():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("harness.config")
    c = json.loads((ROOT / "examples" / "toy" / ".brick-harness" / "config.json").read_text())
    c.update(
        {
            "budgets": {
                "run_tokens": 2000000,
                "run_usd": 50,
                "job_usd": {"build": 5, "default": 2},
                "job_timeout_s": 900,
            },
            "sizing": {"min_loc": 100, "max_loc": 3000},
        }
    )
    assert jsonschema.Draft202012Validator(s).is_valid(c) and bhcore.validate(c, s) == []
    for bad in (
        {"budgets": {"run_tokens": 0}},
        {"budgets": {"x": 1}},
        {"budgets": {"job_usd": 0}},
        {"sizing": {"max_loc": 0}},
    ):
        d = {**c, **bad}
        assert not jsonschema.Draft202012Validator(s).is_valid(d) and bhcore.validate(d, s), bad


def test_a_stuck_reason_reaches_the_unmet_gap(toy):
    for why in ("budget", "oscillating"):
        gaps = bhcore.unmet_gaps(cfg_of(toy), [f"csv-reader:{why}"])
        assert why in gaps[0]["summary"] and bhcore.STUCK_REASONS[why] in gaps[0]["summary"]
