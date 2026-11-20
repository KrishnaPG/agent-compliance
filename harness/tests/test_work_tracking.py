"""SG-15: work hierarchy (mechanisms M1 to M4 of decision 0001).

No gates: an item moves on only when its targets are measured met. Limits bound what is
printed; facts change no status. The tracker mechanisms (M5 to M8) are not built here.
"""

import json
import subprocess
import sys
from pathlib import Path

import bhcore
import pytest
from scale_fixture import make_project
from test_rank import edit_json
from test_toy import BIN, ENV, cli, commit_all, copy_toy, git

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
    p = subprocess.run(
        [sys.executable, str(BIN / name), "--config", str(conf(repo)), *a],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=repo,
        env=ENV,
    )
    return p.returncode, json.loads(p.stdout)


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


# ---------------------------------------------------------------- M1: capped decision part


def test_decision_lists_only_items_not_met_in_build_order_with_counts_and_paging(toy):
    cfg_edit(toy, limits={"decision_items": 1})
    measure_and_commit(toy, "csv-reader")
    _, p = cli("bh-state", toy, "--part", "decision")
    d = p["decision"]
    assert [x["id"] for x in d["pending"]] == ["json-writer"] and d["more"] == 1
    assert d["after"] == "json-writer" and "--after ID" in d["paging"]
    assert d["counts"]["status"] == {"met": 1, "unmeasured": 2}
    assert "csv-reader" not in json.dumps(d["pending"] + list(d["commands"]) + list(d["last"]))
    assert set(d["commands"]) <= {"json-writer"}
    code, nxt = cli("bh-state", toy, "--part", "pending", "--after", "json-writer")
    assert code == 0 and [x["id"] for x in nxt["pending"]["items"]] == ["csv2json"]
    assert nxt["pending"]["more"] == 0 and nxt["pending"]["next"] is None
    code, bad = cli("bh-state", toy, "--part", "pending", "--after", "nope")
    assert code == 2 and "unknown item" in bad["problems"][0]
    assert cli("bh-state", toy, "--part", "branches", "--after", "x")[0] == 2


def test_branches_are_listed_for_listed_items_only(toy):
    cfg_edit(toy, limits={"decision_items": 1})
    for item in ("csv-reader", "json-writer"):
        git(toy, "branch", f"bh/{item}")
    _, p = cli("bh-state", toy, "--part", "decision")
    assert set(p["decision"]["branches"]) == {"csv-reader"}  # json-writer is on page two
    _, p = cli("bh-state", toy, "--part", "branches")
    assert set(p["branches"]) == {"csv-reader", "json-writer"}  # tools read everything


def test_decision_size_does_not_grow_with_the_items_met(tmp_path):
    sizes = []
    for n in (20, 60):
        cfg = make_project(tmp_path / f"p{n}", n)
        _, p = cli("bh-state", cfg.parent.parent, "--part", "decision", config=cfg)
        d = p["decision"]
        assert [x["id"] for x in d["pending"]] == [f"i{k:04d}" for k in range(n - 5, n)]
        assert d["counts"]["status"]["met"] == n - 5 and d["more"] == 0
        sizes.append(len(json.dumps(d)))
    assert sizes[0] == sizes[1]


# ---------------------------------------------------------------- M2: stuck from the files


def test_every_item_not_met_is_stuck_in_gaps_json_with_reason_and_errors(toy):
    """SG-08, moved from the workflow to the tool: the run passes what it attempted; bh-gaps
    derives the rest from the files, writes all of them and reports a capped list."""
    cfg_edit(toy, limits={"decision_items": 2})
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
    assert [s["item"] for s in out["stuck"]] == ["csv-reader", "json-writer"]
    assert out["stuck_more"] == 1  # csv2json: the report is capped, gaps.json is not
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


def test_features_part_rolls_up_items_met_of_total_and_caps_ids(toy):
    cfg_edit(toy, limits={"decision_items": 2})
    _, p = cli("bh-state", toy, "--part", "features")
    f = p["features"]["items"]
    assert f == [
        {"feature": "F1", "met": 0, "total": 3, "ids": ["csv-reader", "json-writer"], "more_ids": 1}
    ]
    measure_and_commit(toy, "csv-reader")
    _, p = cli("bh-state", toy, "--part", "features")
    assert p["features"]["items"][0]["met"] == 1


def test_merged_part_lists_items_met_since_the_last_harvest_with_their_commands(toy):
    measure_and_commit(toy, "csv-reader")
    _, p = cli("bh-state", toy, "--part", "merged")
    m = p["merged"]
    assert m["since"] is None and [x["id"] for x in m["items"]] == ["csv-reader"]
    assert m["commands"]["csv-reader"]["test"]["run"] and m["more"] == 0
    git(toy, "commit", "-q", "--allow-empty", "-m", "brick-harness: harvest gaps")
    _, p = cli("bh-state", toy, "--part", "merged")
    assert p["merged"]["since"] and p["merged"]["items"] == []


# ---------------------------------------------------------------- M3: kinds, refs, split, tracker source


def test_change_items_refs_and_split_from_are_optional_and_validated():
    jsonschema = pytest.importorskip("jsonschema")
    s = bhcore.load_schema("bricks")
    item = change("gh-1", refs=["#1"], split_from="gh-0", path="src/a.py")
    plain = {"id": "a", "job": "j"}
    ok = {"bricks": [item, plain]}
    assert jsonschema.Draft202012Validator(s).is_valid(ok) and bhcore.validate(ok, s) == []
    for bad in ({**item, "kind": "epic"}, {**item, "refs": "#1"}, {**item, "split_from": 3}):
        d = {"bricks": [bad]}
        assert not jsonschema.Draft202012Validator(s).is_valid(d) and bhcore.validate(d, s), bad


def test_a_split_parent_waits_for_its_children_and_is_measured_after_them(toy):
    def add(d):
        d["bricks"].append(change("cr-a", path="src/csv_reader.py", split_from="csv-reader"))

    plan_edit(toy, "bricks.json", add)
    plan_edit(toy, "targets.json", lambda d: d["targets"].extend(default_targets("cr-a")))
    s = cli("bh-state", toy)[1]
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
    s = cli("bh-state", toy)[1]
    g = [g for g in s["gaps"] if "split from unknown nope" in g["summary"]]
    assert g and g[0]["blocks"] == ["x"] and g[0]["kind"] == "missing-dependency"
    assert {b["id"]: b["status"] for b in s["bricks"]}["x"] == "blocked"


# ---------------------------------------------------------------- M4: roll-up and facts


def test_gaps_report_carries_the_rollup_and_structure_facts_and_changes_no_status(toy):

    def add(d):
        d["bricks"].append(change("cr-a", path="src/csv_reader.py", split_from="csv-reader"))

    plan_edit(toy, "bricks.json", add)
    plan_edit(toy, "targets.json", lambda d: d["targets"].extend(default_targets("cr-a")))
    before = {b["id"]: b["status"] for b in cli("bh-state", toy)[1]["bricks"]}
    out = run("bh-gaps", toy)[1]
    assert out["rollup"]["F1"] == {"met": 0, "total": 4}
    kinds = {f["kind"] for f in out["facts"]}
    assert kinds >= {
        "split-parent-without-child-dependency",
        "shared-path",
        "never-scored",
    }
    sp = [f for f in out["facts"] if f["kind"] == "split-parent-without-child-dependency"][0]
    assert sp["item"] == "csv-reader" and sp["children"] == ["cr-a"]
    sh = [f for f in out["facts"] if f["kind"] == "shared-path"][0]
    assert sh["path"] == "src/csv_reader.py" and sh["items"] == ["cr-a", "csv-reader"]
    assert {b["id"]: b["status"] for b in cli("bh-state", toy)[1]["bricks"]} == before
    run("bh-gaps", toy, "--write")
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    assert "## Facts" in md and "## Features in the horizon" in md


# ---------------------------------------------------------------- workflows read capped data


def test_workflows_read_the_capped_decision_and_derive_their_lists_from_it():
    prelude = (ROOT / "lib" / "prelude.js").read_text()
    assert "function fromDecision(s)" in prelude and "s.bricks = d.pending.map" in prelude
    assert "return fromDecision(s)" in prelude  # every state load is derived from the capped part
    assert "'cycle'" in prelude and "--brief" in prelude  # the cycle report is not copied whole
    assert "required: ['received', 'accepted']" in prelude
    for name in ("harness-build", "harness-measure"):
        text = (ROOT / "workflows" / f"{name}.js").read_text()
        assert "d.status[" not in text, name
    for p in (ROOT / "workflows").glob("*.js"):
        assert "state.bricks.map(b => ({ id: b.id, status: b.status }))" not in p.read_text()
