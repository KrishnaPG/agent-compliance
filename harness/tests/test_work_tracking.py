"""SG-15: work hierarchy (mechanisms M1 to M4 of decision 0001).

No gates: an item moves on only when its targets are measured met. Limits bound what is
printed; facts change no status. The tracker mechanisms (M5 to M8) are not built here.
"""

import json
from pathlib import Path

import bhcore
import pytest
from scale_fixture import make_project
from test_rank import edit_json
from test_toy import call, cli, commit_all, copy_toy, full_state, git

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def conf(repo):
    return repo / ".brick-harness" / "config.json"


def cfg_of(repo):
    return bhcore.Config(conf(repo))


def cfg_edit(repo, **kw):
    edit_json(conf(repo), lambda c: c.update(kw))
    commit_all(repo, "config", ".brick-harness")


def plan_edit(repo, name, fn):
    edit_json(repo / ".brick-harness" / name, fn)
    commit_all(repo, f"edit {name}", ".brick-harness")


def run(name, repo, *a, stdin=None):
    code, out = call(name, ["--config", str(conf(repo)), *a], cwd=repo, stdin=stdin)
    return code, json.loads(out)


def measure_and_commit(repo, item="csv-reader"):
    cli("bh-measure", repo, "--item", item)
    return cli("bh-commit", repo, "--message", "scoreboard")[1]


def change(i, **kw):
    return {"id": i, "job": f"change {i}", "kind": "change", "features": ["F1"], **kw}


def default_targets(i):
    return [
        {"item": i, "metric": "tests.failed", "op": "==", "value": 0},
        {"item": i, "metric": "tests.passed", "op": ">=", "value": 1},
    ]


# ---------------------------------------------------------------- M1: the full state, a file for big output


def test_state_lists_items_not_met_in_value_order_with_counts(toy):
    measure_and_commit(toy, "csv-reader")
    s = full_state(toy)[1]
    assert s["queue"] == ["json-writer", "csv2json"]
    assert s["counts"]["bricks"] == 3
    assert {b["id"]: b["status"] for b in s["bricks"]} == {
        "csv-reader": "met",
        "json-writer": "unmeasured",
        "csv2json": "unmeasured",
    }


def test_branches_are_listed_for_every_item(toy):
    for item in ("csv-reader", "json-writer"):
        git(toy, "branch", f"bh/{item}")
    assert set(full_state(toy)[1]["branches"]) == {"csv-reader", "json-writer"}


def test_state_does_not_cut_the_lists_the_orchestrator_reads(tmp_path):
    cfg = make_project(tmp_path / "p", 60)
    s = bhcore.state(bhcore.Config(cfg))
    assert s["queue"] == [f"i{k:04d}" for k in range(55, 60)]
    assert sum(b["status"] == "met" for b in s["bricks"]) == 55
    assert len(s["bricks"]) == 60


def test_a_thousand_item_state_is_written_to_the_file_intact_and_the_summary_stays_small(tmp_path):
    """Rule 5: big output never crosses an agent; the CLI prints ids and counts and a path."""
    cfg = make_project(tmp_path / "p", 1000, ready=500)
    code, summary = cli("bh-state", cfg.parent.parent, config=cfg)
    assert code == 0 and len(json.dumps(summary)) < 3000
    assert summary["counts"] == {"met": 500, "unmeasured": 500}
    cap = bhcore.SUMMARY_CAP
    assert len(summary["ready"]) == cap and summary["ready_more"] == 500 - cap
    assert len(summary["unmet"]) == cap and summary["unmet_more"] == 500 - cap
    on_disk = json.loads(Path(summary["file"]).read_text())
    assert [b["id"] for b in on_disk["bricks"]] == [f"i{k:04d}" for k in range(1000)]
    assert on_disk == json.loads(json.dumps(bhcore.state(bhcore.Config(cfg))))  # nothing cut
    assert not list(Path(summary["file"]).parent.glob(".state.*.tmp"))  # atomic write left none


# ---------------------------------------------------------------- M2: stuck from the files


def test_every_item_not_met_is_stuck_in_gaps_json_with_reason_and_errors(toy):
    """SG-08, moved from the workflow to the tool: the run passes what it attempted; bh-gaps
    derives the rest from the files, writes all of them and reports a capped list."""
    cli("bh-measure", toy, "--item", "json-writer")  # unbuilt: unmet with errors
    code, out = run(
        "bh-gaps",
        toy,
        "--source",
        "cycle",
        "--unmet",
        "json-writer:no-change",
        "--brief",
        "--write",
        "--add",
        "-",
        stdin="[]",
    )
    assert code == 0 and "gaps" not in out and out["gaps_total"] >= 3
    assert [s["item"] for s in out["stuck"]] == ["csv-reader", "json-writer", "csv2json"]
    assert out["stuck_more"] == 0  # the report is capped at SUMMARY_CAP, gaps.json is not
    assert all("errors" in s for s in out["stuck"])
    doc = json.loads((toy / ".brick-harness" / "gaps.json").read_text())
    by = {g["summary"].split()[1]: g for g in doc["gaps"] if g["kind"] == "unmet-after-rounds"}
    assert set(by) == {"csv-reader", "json-writer", "csv2json"}
    assert (
        "no-change" in by["json-writer"]["summary"]
        and "last errors" in by["json-writer"]["summary"]
    )
    assert (
        "not-attempted" in by["csv-reader"]["summary"]
        and "not-attempted" in by["csv2json"]["summary"]
    )
    # a repeat replaces the list; an item that is met leaves it
    measure_and_commit(toy, "csv-reader")
    run("bh-gaps", toy, "--source", "cycle", "--brief", "--write", "--add", "-", stdin="[]")
    doc = json.loads((toy / ".brick-harness" / "gaps.json").read_text())
    stuck = {g["summary"].split()[1] for g in doc["gaps"] if g["kind"] == "unmet-after-rounds"}
    assert stuck == {"json-writer", "csv2json"}


def test_features_part_rolls_up_items_met_of_total(toy):
    f = full_state(toy)[1]["features"]["items"]
    assert f == [
        {
            "feature": "F1",
            "met": 0,
            "total": 3,
            "ids": ["csv-reader", "json-writer", "csv2json"],
            "more_ids": 0,
        }
    ]
    measure_and_commit(toy, "csv-reader")
    assert full_state(toy)[1]["features"]["items"][0]["met"] == 1


def test_merged_part_lists_items_met_since_the_last_harvest_with_their_commands(toy):
    measure_and_commit(toy, "csv-reader")
    m = full_state(toy)[1]["merged"]
    assert m["since"] is None and [x["id"] for x in m["items"]] == ["csv-reader"]
    assert m["commands"]["csv-reader"]["test"]["run"] and m["more"] == 0
    git(toy, "commit", "-q", "--allow-empty", "-m", "brick-harness: harvest gaps")
    m = full_state(toy)[1]["merged"]
    assert m["since"] and m["items"] == []


# ---------------------------------------------------------------- M3: kinds, refs, split, tracker source


def test_change_items_refs_and_split_from_are_optional_and_validated():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("bricks")
    item = change("gh-1", refs=["#1"], split_from="gh-0", path="src/a.py")
    plain = {"id": "a", "job": "j"}
    ok = {"bricks": [item, plain]}
    assert jsonschema.Draft202012Validator(s).is_valid(ok) and bhcore.schema_errors(ok, s) == []
    for bad in ({**item, "kind": "epic"}, {**item, "refs": "#1"}, {**item, "split_from": 3}):
        d = {"bricks": [bad]}
        assert not jsonschema.Draft202012Validator(s).is_valid(d) and bhcore.schema_errors(d, s), bad


def test_a_split_parent_waits_for_its_children_and_is_measured_after_them(toy):
    def add(d):
        d["bricks"].append(change("cr-a", path="src/csv_reader.py", split_from="csv-reader"))

    plan_edit(toy, "bricks.json", add)
    plan_edit(toy, "targets.json", lambda d: d["targets"].extend(default_targets("cr-a")))
    s = full_state(toy)[1]
    by = {b["id"]: b for b in s["bricks"]}
    assert by["csv-reader"]["depends_on"] == ["cr-a"]  # structure: the parent depends on its child
    assert not by["csv-reader"]["ready"] and by["cr-a"]["ready"]
    assert s["waves"][0].index("cr-a") >= 0 and "csv-reader" not in s["waves"][0]
    assert (
        "csv-reader" not in s["ready"] and "cr-a" in s["ready"]
    )  # a change item is built like a brick
    assert by["csv-reader"]["status"] == "unmeasured"  # no status is set, only the order


def test_a_split_from_an_unknown_item_is_a_blocking_gap(toy):
    plan_edit(toy, "bricks.json", lambda d: d["bricks"].append(change("x", split_from="nope")))
    plan_edit(toy, "targets.json", lambda d: d["targets"].extend(default_targets("x")))
    s = full_state(toy)[1]
    g = [g for g in s["gaps"] if "split from unknown nope" in g["summary"]]
    assert g and g[0]["blocks"] == ["x"] and g[0]["kind"] == "missing-dependency"
    assert {b["id"]: b["status"] for b in s["bricks"]}["x"] == "blocked"


# ---------------------------------------------------------------- M4: roll-up and facts


def test_gaps_report_carries_the_shared_path_fact_and_changes_no_status(toy):

    def add(d):
        d["bricks"].append(change("cr-a", path="src/csv_reader.py", split_from="csv-reader"))

    plan_edit(toy, "bricks.json", add)
    plan_edit(toy, "targets.json", lambda d: d["targets"].extend(default_targets("cr-a")))
    before = {b["id"]: b["status"] for b in full_state(toy)[1]["bricks"]}
    out = run("bh-gaps", toy)[1]
    assert "rollup" not in out
    sh = [f for f in out["facts"] if f["kind"] == "shared-path"][0]
    assert sh["path"] == "src/csv_reader.py" and sh["items"] == ["cr-a", "csv-reader"]
    assert {b["id"]: b["status"] for b in full_state(toy)[1]["bricks"]} == before
    run("bh-gaps", toy, "--write")
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    assert "## Facts" in md and "## Features in the horizon" not in md
