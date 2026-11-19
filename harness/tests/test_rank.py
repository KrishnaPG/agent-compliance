"""Ranking, report and limit safeguards (SG-03, SG-04, SG-08, SG-11 to SG-14).

None of them gates: ranking orders and drops nothing, facts change no status, limits list
what is left. The toy project is the fixture; workflows are run under node with mocked
agents, never against a model.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import bhcore
import pytest
from test_toy import BIN, ENV, cli, commit_all, copy_toy, git, status

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "workflows"
NODE = shutil.which("node")
PRELUDE = (ROOT / "lib" / "prelude.js").read_text()


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
    _, s = cli("bh-state", toy)
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
    _, s = cli("bh-state", toy)
    assert {b["id"]: b["status"] for b in s["bricks"]}["csv-reader"] == "unmeasured"
    cli("bh-measure", toy, "--item", "csv-reader")
    cli("bh-commit", toy, "--message", "scoreboard")
    cli("bh-measure", toy, "--item", "json-writer")
    cli("bh-commit", toy, "--message", "scoreboard")
    st, s = status(toy)
    assert st["csv-reader"] == "met" and st["json-writer"] == "unmet"
    assert s["ready"] == ["json-writer"] and s["decision"]["ready"] == ["json-writer"]
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


def test_build_workflow_measures_before_it_builds_and_never_builds_a_met_item():
    b = (FLOWS / "harness-build.js").read_text().replace(PRELUDE, "")
    assert (
        "REMEASURE.indexOf(bStatus(id)) >= 0" in b
    )  # code that may already exist is measured first
    assert "metAtHead.indexOf(id) < 0 && stillReady.indexOf(id) >= 0" in b
    assert "bh-rank" not in b and "gaps.json" not in b, "a build round takes no finding as work"


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


def test_gaps_workflow_hands_a_re_review_only_the_diff_and_open_findings():
    g = (FLOWS / "harness-gaps.js").read_text().replace(PRELUDE, "")
    assert "--review-input" in g and "RE-REVIEW" in g and "ri.diff" in g and "ri.open" in g
    assert "Judge only what changed" in g
    assert g.index("--review-input") < g.index("const review = await agent(")
    assert "--write" not in g  # still writes only through the guarded helpers


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


def test_gaps_and_plan_prompts_hand_over_the_recorded_decisions_as_settled_inputs():
    g = (FLOWS / "harness-gaps.js").read_text()
    p = (FLOWS / "harness-plan.js").read_text()
    for t in (g, p):
        assert "standards.decisions" in t or "(state.config.standards || {}).decisions" in t
        assert "settled inputs" in t and "do not re-argue" in t.lower()
    assert "reopens" in g and "Look for gaps in what they do not settle" in g
    assert "reopens: STR" in PRELUDE  # the reviewer's output schema carries the field


# ---------------------------------------------------------------- SG-14: sizing notes


def sized_toy(toy, **sizing):
    def bricks(d):
        by = {b["id"]: b for b in d["bricks"]}
        by["csv-reader"].update(
            {
                "est_loc": 10,
                "consumers": ["csv2json"],
                "purpose": "read CSV",
                "hides": "dialects",
                "interface": "read_rows(text) -> list[dict]",
                "oss_checked": [{"tool": "csv", "version": "stdlib", "fits": True}],
            }
        )
        by["json-writer"].update({"est_loc": 5000})
        by["csv2json"].update({"purpose": "read the CSV and write the JSON"})

    edit_json(toy / ".brick-harness" / "bricks.json", bricks)
    if sizing:
        edit_json(toy / ".brick-harness" / "config.json", lambda c: c.update({"sizing": sizing}))


def test_sizing_notes_list_facts_against_config_thresholds_and_change_no_status(toy):
    before = status(toy)[0]
    sized_toy(toy)
    _, r = cli("bh-gaps", toy, "--write")
    notes = {(n["item"], n["note"].split(":")[0].split(" (")[0]) for n in r["sizing_notes"]}
    text = " | ".join(n["note"] for n in r["sizing_notes"])
    assert "est_loc 10 below sizing.min_loc 150" in text  # defaults 150 and 2000
    assert "est_loc 5000 above sizing.max_loc 2000" in text
    assert "purpose may join two jobs" in text and "a single consumer (csv2json)" in text
    assert "OSS tool csv stdlib fits" in text and notes
    assert r["counts"] == cli("bh-gaps", toy)[1]["counts"]
    assert not any(g["kind"] == "other" for g in r["gaps"])  # notes are not gaps
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    assert "## Sizing notes" in md and "est_loc 5000" in md
    assert status(toy)[0] == before  # a fact: no status moved
    on_disk = json.loads((toy / ".brick-harness" / "gaps.json").read_text())
    assert bhcore.validate(on_disk, bhcore.load_schema("gaps")) == []


def test_sizing_thresholds_come_from_config_and_lines_are_measured(toy):
    sized_toy(toy, min_loc=5, max_loc=1)
    _, r = cli("bh-gaps", toy)
    text = " | ".join(n["note"] for n in r["sizing_notes"])
    assert "est_loc 10 below" not in text  # 10 >= min_loc 5
    assert "est_loc 10 above sizing.max_loc 1" in text
    assert re.search(r"measured lines \d+ above sizing.max_loc 1", text)


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
    d = bhcore.state(cfg)["decision"]
    assert d["oscillating"] == osc


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
            "budgets": {"run_tokens": 2000000, "round_reserve_tokens": 300000},
            "sizing": {"min_loc": 100, "max_loc": 3000},
        }
    )
    assert jsonschema.Draft202012Validator(s).is_valid(c) and bhcore.validate(c, s) == []
    for bad in ({"budgets": {"run_tokens": 0}}, {"budgets": {"x": 1}}, {"sizing": {"max_loc": 0}}):
        d = {**c, **bad}
        assert not jsonschema.Draft202012Validator(s).is_valid(d) and bhcore.validate(d, s), bad


def body(name):
    text = (FLOWS / f"{name}.js").read_text()
    return text[text.index("\n}\n") + 2 :]


HARNESS_JS = r"""
const AsyncFunction = (async () => {}).constructor;
const { checksum } = new Function(PRE_FNS + '\nreturn { checksum }')();
const STATE = %(state)s;
const T = %(total)s;
const budget = { _s: 0, spent() { return this._s }, remaining() { return T === null ? Infinity : T - this._s }, total: T };
const calls = [], UNMET = [];
const agent = async (prompt, o) => {
  calls.push(o && o.label)
  if (o && o.schema && o.schema.required && o.schema.required.includes('checksums')) {
    const parts = o.schema.required.filter(k => k !== 'checksums'), out = { checksums: {} }
    for (const p of parts) { out[p] = JSON.parse(JSON.stringify(STATE[p])); out.checksums[p] = checksum(STATE[p]) }
    return out
  }
  if (o.label.startsWith('gaps')) {
    const m = /--unmet (.*?) --brief/.exec(prompt), unmet = m ? m[1].split(' ').map(x => ({ item: x.slice(0, x.lastIndexOf(':')), reason: x.slice(x.lastIndexOf(':') + 1) })) : []
    UNMET.push(...unmet) // what the run passes to bh-gaps; the tool derives the rest from the files
    return { gaps_total: 0, received: 0, accepted: 0, stuck: unmet, stuck_more: 0 }
  }
  if (o.label === 'commit plan') return { committed: false }
  if (/tracker/.test(o.label)) return { tracker: 'files', closed: [], reopened: [], mismatches: [], facts: [] }
  throw new Error('unexpected agent ' + o.label)
}
const workflow = async (name) => {
  budget._s += 100
  if (name.endsWith('harness-build')) return { refs: [{ ref: 'x', items: ['csv-reader'] }] }
  return { measured: [], merged: [] }
}
const f = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', BODY)
f(agent, undefined, undefined, () => {}, () => {}, { configPath: 'c.json', skip: ['gaps', 'plan', 'harvest'], state: STATE }, budget, workflow)
  .then(r => console.log(JSON.stringify({ rounds: r.rounds.length, stopped: r.stopped, stuck: r.stuck, passed: UNMET, error: r.error, spent: budget._s })))
"""


def run_harness(toy, total=None, config=None, decision=None):
    if config:
        edit_json(toy / ".brick-harness" / "config.json", lambda c: c.update(config))
    st = bhcore.state(cfg_of(toy))
    if decision:
        st["decision"].update(decision)
    parts = PRELUDE[PRELUDE.index("function canon(") : PRELUDE.index("let state = ")]
    js = (
        f"const PRE_FNS = {json.dumps(parts)};\nconst BODY = {json.dumps(body('harness-run'))};\n"
        + HARNESS_JS
        % {
            "state": json.dumps(st),
            "total": "null" if total is None else total,
        }
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_without_budgets_the_run_stops_only_at_max_rounds(toy):
    r = run_harness(toy)
    assert r["rounds"] == 3 and r["stopped"] is None and r.get("error") is None
    assert {s["item"]: s["reason"] for s in r["stuck"]}["csv-reader"] == "unmet"
    assert {s["item"] for s in r["passed"]} == {"csv-reader"}  # only what the run attempted


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_run_tokens_ends_the_run_before_a_round_that_does_not_fit_and_lists_what_is_left(toy):
    # a round costs 200 here; 250 allows one round, then 50 is below one round's reserve
    r = run_harness(toy, config={"budgets": {"run_tokens": 250}})
    assert r["rounds"] == 1 and r["stopped"] == "budget"
    stuck = {s["item"]: s["reason"] for s in r["stuck"]}
    assert stuck["csv-reader"] == "budget" and stuck["json-writer"] == "budget"
    assert "csv2json" not in stuck  # not ready: the tool derives it as not-attempted from the files
    r = run_harness(toy, config={"budgets": {"run_tokens": 1000}})
    assert r["rounds"] == 3 and r["stopped"] is None  # three rounds fit


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_workflow_budget_bounds_the_run_even_without_a_config_cap(toy):
    r = run_harness(toy, total=450)  # remaining 450, 250, then 50 < 200
    assert r["rounds"] == 2 and r["stopped"] == "budget"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_the_configured_reserve_applies_before_the_first_round(toy):
    r = run_harness(toy, config={"budgets": {"run_tokens": 900, "round_reserve_tokens": 1000}})
    assert r["rounds"] == 0 and r["stopped"] == "budget"
    assert {s["item"]: s["reason"] for s in r["stuck"]}["csv-reader"] == "budget"


def test_a_stuck_reason_reaches_the_unmet_gap(toy):
    for why in ("budget", "oscillating"):
        gaps = bhcore.unmet_gaps(cfg_of(toy), [f"csv-reader:{why}"])
        assert why in gaps[0]["summary"] and bhcore.STUCK_REASONS[why] in gaps[0]["summary"]
