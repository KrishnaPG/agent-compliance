"""SG-16 (learning from the owner's answers) and SG-18 (the self-contained work packet).

No gates: a covered question stops blocking because a recorded fact says so, never because
an agent decided; a packet is assembled from the plan's citations, never retyped.
"""

import hashlib
import json

import bhcore
import pytest
from test_toy import EMPTY_CATALOG, cli, commit_all, copy_toy, full_state, git
from test_work_tracking import cfg_edit, plan_edit

KIND = "no-numeric-target"
AREA = ".brick-harness/bricks.json"


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def question(repo):
    """An owner question: an item without targets; returns its gap id."""
    plan_edit(
        repo,
        "bricks.json",
        lambda d: d["bricks"].append({"id": "nt", "job": "no targets", "kind": "change"}),
    )
    _, g = cli("bh-gaps", repo, "--write")
    return next(x["id"] for x in g["gaps"] if x["kind"] == KIND)


def answer(repo, gap, text="use 3 retries", kinds=KIND, areas=AREA, source="features.md:1"):
    return cli(
        "bh-answer", repo, "--gap", gap, "--answer", text, "--source", source,
        "--kinds", kinds, "--areas", areas, "--date", "2026-11-19", "--write",
    )  # fmt: skip


def status_of(repo, item):
    return {b["id"]: b for b in full_state(repo)[1]["bricks"]}[item]


# ---------------------------------------------------------------- SG-16


def test_bh_answer_writes_a_numbered_record_once_and_bh_commit_commits_it(toy):
    gap = question(toy)
    code, a = answer(toy, gap)
    assert code == 0 and a["created"] and a["decision"]["id"] == "D-1"
    rec = json.loads((toy / ".brick-harness" / "decisions" / "D-1.json").read_text())
    assert rec == {**a["decision"]} and rec["question"] and rec["date"] == "2026-11-19"
    assert answer(toy, gap)[1]["created"] is False  # same gap and answer: the record that exists
    assert answer(toy, gap, "another answer")[1]["decision"]["id"] == "D-2"
    _, c = cli("bh-commit", toy)
    assert ".brick-harness/decisions/D-1.json" in c["files"]


def test_bh_answer_without_write_writes_nothing_and_refuses_bad_input(toy):
    gap = question(toy)
    code, a = cli("bh-answer", toy, "--gap", gap, "--answer", "x", "--source", "features.md:1",
                  "--kinds", KIND, "--areas", AREA)  # fmt: skip
    assert code == 0 and a["dry_run"] and not (toy / ".brick-harness" / "decisions").exists()
    assert answer(toy, "nope")[0] == 2
    assert answer(toy, gap, source="features.md:999")[0] == 2
    assert answer(toy, gap, kinds="not-a-kind")[0] == 2


def test_a_covered_question_that_cites_nothing_is_re_asked_and_blocks_nothing(toy):
    gap = question(toy)
    assert status_of(toy, "nt")["status"] == "blocked"
    answer(toy, gap)
    assert (
        status_of(toy, "nt")["status"] != "blocked"
    )  # facts, not a verdict: the question is settled
    _, g = cli("bh-gaps", toy, "--write")
    assert [r["covered_by"] for r in g["re_asked"]] == [["D-1"]]
    assert all(x["kind"] != KIND for x in g["gaps"])
    assert g["learning"]["opened"] == 1 and g["learning"]["re_asked"] == 1
    assert g["learning"]["answered"] == 0 and g["counts"]["owner-decides"] == 0
    assert "## Re-asked" in (toy / ".brick-harness" / "gaps.md").read_text()


def review_gap(by, area=AREA):
    return [{"kind": KIND, "summary": "retries not stated", "tag": "owner-decides", "answered_by": by,
             "evidence": [{"file": area, "line": 2}]}]  # fmt: skip


def add_review(repo, gaps):
    p = repo / "review.json"
    p.write_text(json.dumps(gaps))
    return cli("bh-gaps", repo, "--source", "review", "--add", str(p), "--write")[1]


def test_a_gap_citing_a_covering_decision_is_listed_answered_by_it_not_blocking(toy):
    answer(toy, question(toy))
    g = add_review(toy, review_gap("D-1"))
    assert [r["answered_by"] for r in g["answered"]] == ["D-1"] and g["answered"][0][
        "date"
    ] == "2026-11-19"
    assert g["learning"]["answered"] == 1 and g["rejected"] == []
    again = cli("bh-gaps", toy, "--source", "plan", "--write")[
        1
    ]  # still listed on the next run, not dropped
    assert [r["answered_by"] for r in again["answered"]] == ["D-1"]
    assert "## Answered by a decision" in (toy / ".brick-harness" / "gaps.md").read_text()


@pytest.mark.parametrize(
    ("cite", "why"), [("D-9", "no such record"), ("D-1", "does not cover the gap's kind and area")]
)
def test_a_cite_that_is_missing_or_does_not_cover_is_bad_cite_and_the_gap_stays(toy, cite, why):
    answer(toy, question(toy), kinds="no-contract")  # D-1 covers another kind
    g = add_review(toy, review_gap(cite))
    bad = [f for f in g["facts"] if f["kind"] == "bad-cite"]
    assert len(bad) == 1 and bad[0]["answered_by"] == cite and bad[0]["why"] == why
    assert any(x["source"] == "review" for x in g["gaps"]) and g["answered"] == []
    assert g["learning"]["bad_cites"] == 1


def test_a_decision_covers_a_directory_of_areas(toy):
    answer(toy, question(toy), areas=".brick-harness")
    assert [r["covered_by"] for r in cli("bh-gaps", toy)[1]["re_asked"]] == [["D-1"]]


def test_state_learning_carries_every_overlay_candidate_and_the_overlay_path(toy):
    gap = question(toy)
    for n in range(3):
        answer(toy, gap, f"answer {n}")
    s = full_state(toy)[1]
    assert set(s["learning"]) == {"overlay_candidates", "overlay"}
    (cand,) = s["learning"]["overlay_candidates"]
    assert cand["decisions"] == ["D-1", "D-2", "D-3"]
    assert s["learning"]["overlay"] == bhcore.overlay_path(
        bhcore.Config(toy / ".brick-harness" / "config.json")
    )
    assert len(sorted((toy / ".brick-harness" / "decisions").glob("D-*.json"))) == 3


def overlay(repo, line=None):
    (repo / "docs" / "agents").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agents" / "design-compliance.md").write_text(
        "# Overlay\n" + (line or "") + "\n"
    )
    cfg_edit(repo, standards={"catalog": str(EMPTY_CATALOG)})


def test_an_area_answered_often_is_an_overlay_candidate_until_the_overlay_holds_a_rule(toy):
    gap = question(toy)
    overlay(toy)
    for n in range(2):
        answer(toy, gap, f"answer {n}")
    assert cli("bh-gaps", toy)[1]["learning"]["overlay_candidates"] == []
    answer(toy, gap, "answer 2")
    cand = cli("bh-gaps", toy)[1]["learning"]["overlay_candidates"]
    assert cand[0]["area"] == AREA and cand[0]["decisions"] == ["D-1", "D-2", "D-3"]
    assert full_state(toy)[1]["learning"]["overlay_candidates"] == cand
    assert "## Learning from answers" in (
        cli("bh-gaps", toy, "--write") and (toy / ".brick-harness" / "gaps.md").read_text()
    )
    overlay(toy, f"- RL-01 Retries are three. covers: {AREA}")
    g = cli("bh-gaps", toy)[1]
    assert g["learning"]["overlay_candidates"] == []
    assert [r["covered_by"][-1] for r in g["re_asked"]] == [
        "RL-01"
    ]  # the rule covers like a decision


def test_the_threshold_comes_from_config_learning_overlay_after(toy):
    gap = question(toy)
    cfg_edit(toy, learning={"overlay_after": 1})
    answer(toy, gap)
    assert len(cli("bh-gaps", toy)[1]["learning"]["overlay_candidates"]) == 1


def test_decision_schema_and_config_accept_the_new_fields():
    schema = bhcore.load_schema("decision")
    rec = {"id": "D-1", "gap": "g", "question": "q", "answer": "a", "source": "f:1", "kinds": ["other"],
           "areas": ["x"], "date": "2026-11-19"}  # fmt: skip
    assert bhcore.validate(rec, schema) == []
    assert bhcore.validate({**rec, "id": "1", "kinds": []}, schema)


def test_missing_context_is_a_finding_kind_that_bh_rank_records(toy):
    f = [
        {
            "summary": "csv-reader lacks the delimiter rule",
            "kind": "missing-context",
            "source": "build",
            "impact": ["csv-reader"],
        }
    ]
    p = toy / "f.json"
    p.write_text(json.dumps(f))
    code, out = cli("bh-rank", toy, "--add", str(p), "--write")
    assert code == 0
    g = json.loads((toy / ".brick-harness" / "gaps.json").read_text())["gaps"]
    assert [x["kind"] for x in g if x["source"] == "finding"] == ["missing-context"]
    assert cli("bh-gaps", toy)[1]["learning"]["missing_context"] == 1


# ---------------------------------------------------------------- SG-18


def with_context(repo, rules=("RL-01",)):
    def edit(d):
        for b in d["bricks"]:
            if b["id"] == "csv-reader":
                b["context"] = [{"path": "PLAN.md", "lines": "5-6"}]
                b["rules"] = list(rules)

    plan_edit(repo, "bricks.json", edit)


def brief(repo, item, *a):
    from test_toy import call

    return call("bh-brief", ["--config", str(repo / ".brick-harness" / "config.json"), item, *a], cwd=repo)


def test_bh_brief_assembles_the_packet_from_citations_with_digest_and_dependency_contracts(toy):
    with_context(toy)
    overlay(toy, "- RL-01 Name the delimiter. covers: x")
    code, text = brief(toy, "csv-reader")
    lines = (toy / "PLAN.md").read_text().splitlines()[4:6]
    assert code == 0 and "\n".join(lines) in text
    assert f"sha256 {hashlib.sha256(chr(10).join(lines).encode()).hexdigest()}" in text
    for part in ("## Job", "## Contract", "## Targets", "tests.passed >= 1", "## Commands", "- test: ",
                 "## Owned paths", "- src/csv_reader.py", "## Stack pins (python)", "- RL-01: Name the delimiter"):  # fmt: skip
        assert part in text, part
    _, sysbrief = brief(toy, "csv2json")
    assert "### csv-reader" in sysbrief and "### json-writer" in sysbrief
    assert "def " not in sysbrief and "import " not in sysbrief  # contracts, never code
    code, js = brief(toy, "csv-reader", "--json")
    pk = json.loads(js)
    assert code == 0 and pk["tokens"] == -(-len(pk["text"]) // 4) and pk["stale"] == []
    assert brief(toy, "nope")[0] == 2


def test_packet_rules_is_the_one_function_that_chooses_the_rules(toy):
    with_context(toy, ("RL-01", "RL-02"))
    overlay(toy, "- RL-01 Name the delimiter. covers: x")
    cfg = bhcore.Config(toy / ".brick-harness" / "config.json")
    assert bhcore.packet_rules(cfg, "csv-reader") == [
        {"id": "RL-01", "text": "Name the delimiter."},
        {"id": "RL-02", "text": ""},
    ]
    assert bhcore.packet_rules(cfg, "json-writer") == []


def test_a_passage_whose_lines_changed_since_the_plan_commit_is_stale_context(toy):
    with_context(toy)
    assert not [f for f in cli("bh-gaps", toy)[1]["facts"] if f["kind"] == "stale-context"]
    (toy / "PLAN.md").write_text(
        (toy / "PLAN.md").read_text().replace("1. csv-reader", "1. csv-rdr")
    )
    commit_all(toy, "spec moved on", "PLAN.md")
    facts = [f for f in cli("bh-gaps", toy)[1]["facts"] if f["kind"] == "stale-context"]
    assert [(f["item"], f["path"], f["lines"]) for f in facts] == [("csv-reader", "PLAN.md", "5-6")]
    _, text = brief(toy, "csv-reader")
    assert "1. csv-reader" in text  # the packet is the plan commit's passage


def test_a_cited_line_range_that_does_not_exist_is_reported_not_invented(toy):
    plan_edit(
        toy,
        "bricks.json",
        lambda d: d["bricks"][0].update(context=[{"path": "PLAN.md", "lines": "500-600"}]),
    )
    f = [x for x in cli("bh-gaps", toy)[1]["facts"] if x["kind"] == "stale-context"]
    assert f and "does not exist" in f[0]["why"]


def test_a_packet_over_the_configured_size_is_a_sizing_note_and_sizes_are_listed(toy):
    cfg_edit(toy, sizing={"packet_tokens": 20})
    _, g = cli("bh-gaps", toy)
    notes = [n for n in g["sizing_notes"] if "work packet" in n["note"]]
    assert {n["item"] for n in notes} == {"csv-reader", "json-writer", "csv2json"}
    assert set(g["packets"]["tokens"]) == {"csv-reader", "json-writer", "csv2json"}


def test_the_default_packet_limit_is_1600_tokens(toy):
    assert bhcore.SIZING_DEFAULT["packet_tokens"] == 1600
    _, g = cli("bh-gaps", toy)
    assert not [n for n in g["sizing_notes"] if "work packet" in n["note"]]


def test_bricks_schema_context_and_rules_are_optional_and_typed():
    schema = bhcore.load_schema("bricks")
    one = {"id": "a", "job": "j"}
    assert bhcore.validate({"bricks": [one]}, schema) == []
    ok = {**one, "context": [{"path": "p.md", "lines": "1-9"}], "rules": ["RL-01"]}
    assert bhcore.validate({"bricks": [ok]}, schema) == []
    assert bhcore.validate(
        {"bricks": [{**one, "context": [{"path": "p.md", "lines": "1"}]}]}, schema
    )
    assert bhcore.validate(
        {"bricks": [{**one, "context": [{"path": "p.md", "lines": "1-2", "text": "x"}]}]}, schema
    )
