"""SG-17: value order. Slice and value are the owner's data with a cited source; the order,
the finish-before-start limit and the sellable facts are derived, never scored, and no status
moves except by measurement.
"""

import json

import bhcore
import pytest
from test_toy import cli, commit_all, copy_toy, full_state, git
from test_work_tracking import cfg_of, conf, default_targets, measure_and_commit, plan_edit


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def add_items(repo, *items):
    plan_edit(repo, "bricks.json", lambda d: d["bricks"].extend(items))
    plan_edit(
        repo,
        "targets.json",
        lambda d: d["targets"].extend(t for i in items for t in default_targets(i["id"])),
    )


def sys_item(i, deps=(), **kw):
    return {
        "id": i,
        "job": f"system {i}",
        "kind": "system",
        "depends_on": list(deps),
        "path": f"src/{i}.py",
        **kw,
    }


def write_features(repo, *features):
    p = repo / ".brick-harness" / "features.json"
    p.write_text(json.dumps({"features": list(features)}))
    commit_all(repo, "features", ".brick-harness")


def feat(i, acceptance, slice=None, value=None, source="PLAN.md:5", **kw):
    f = {"id": i, "title": f"feature {i}", "acceptance": acceptance, "source": source, **kw}
    if slice is not None:
        f["slice"] = slice
    if value is not None:
        f["value"] = value
    return f


def queue(repo):
    cfg = cfg_of(repo)
    return bhcore.value_queue(cfg, bhcore.state(cfg))


def held(s):
    return {b["id"]: b["held_by"] for b in s["bricks"] if b.get("held_by")}


def pending_ids(repo):
    return full_state(repo)[1]["queue"]


def test_without_features_the_queue_is_the_build_order_and_nothing_changes(toy):
    assert queue(toy) == ["csv-reader", "json-writer", "csv2json"] == pending_ids(toy)
    _, s = full_state(toy)
    assert s["value"] == {
        "sellable_at_head": [],
        "if_stopped_today": [],
        "next": None,
        "unvalued": [],
    }
    assert s["ready"] == ["csv-reader", "json-writer"] and s["problems"] == []


def test_earliest_slice_first_each_feature_closure_in_dependency_order(toy):
    add_items(toy, sys_item("extra", ["json-writer"]))
    write_features(toy, feat("F1", "csv2json", 2, 100), feat("F2", "extra", 1, 1))
    assert queue(toy) == ["json-writer", "extra", "csv-reader", "csv2json"]
    assert pending_ids(toy) == queue(toy)  # the decision part's page is the head of the queue
    _, s = full_state(toy)
    assert s["value"]["next"] == {"feature": "F2", "remaining_cost": 2}


def test_within_a_slice_the_highest_value_per_remaining_cost_first_ties_by_build_order(toy):
    add_items(
        toy,
        sys_item("big", est_loc=900),
        sys_item("small", est_loc=100),
        sys_item("twin", est_loc=100),
    )
    write_features(
        toy,
        feat("A", "big", 1, 10),  # 10 / 900
        feat("B", "small", 1, 5),  # 5 / 100
        feat("C", "twin", 1, 5),  # same ratio as B: build order decides
    )
    assert queue(toy)[:3] == ["small", "twin", "big"]


def test_est_loc_absent_counts_one_and_shared_items_are_emitted_once(toy):
    write_features(toy, feat("A", "csv2json", 1, 3), feat("B", "json-writer", 1, 3))
    # B costs 1 (json-writer), A costs 3: B first, then A's closure without the repeat
    assert queue(toy) == ["json-writer", "csv-reader", "csv2json"]


def test_unvalued_features_rank_last_are_listed_and_never_by_an_agent_estimate(toy):
    add_items(toy, sys_item("extra"))
    write_features(
        toy,
        feat("NOVALUE", "extra", 1, None),
        feat("BADSRC", "json-writer", 1, 9, source="PLAN.md:999"),
        feat("OK", "csv-reader", 5, 1),
    )
    assert queue(toy)[0] == "csv-reader"  # the valued feature, though its slice is later
    _, s = full_state(toy)
    un = {u["feature"]: u["missing"] for u in s["value"]["unvalued"]}
    assert un["NOVALUE"] == ["value"] and "does not exist" in un["BADSRC"][0]
    _, g = cli("bh-gaps", toy)
    assert {u["feature"] for u in g["value"]["unvalued"]} == {"NOVALUE", "BADSRC"}


def test_items_no_feature_names_follow_in_build_order(toy):
    add_items(toy, sys_item("orphan"))
    write_features(toy, feat("A", "json-writer", 1, 1))
    assert queue(toy) == ["json-writer", "csv-reader", "orphan", "csv2json"]  # waves: build order


def test_a_feature_pointing_at_an_unknown_acceptance_item_is_unvalued_and_changes_no_order(toy):
    write_features(toy, feat("A", "nope", 1, 1))
    assert queue(toy) == ["csv-reader", "json-writer", "csv2json"]
    assert full_state(toy)[1]["value"]["unvalued"] == [
        {"feature": "A", "missing": ["acceptance item nope unknown"]}
    ]


def test_finish_before_start_holds_later_features_while_the_earlier_has_ready_items(toy):
    add_items(toy, sys_item("later", est_loc=1))
    write_features(toy, feat("F1", "csv2json", 1, 5), feat("F2", "later", 2, 5))
    measure_and_commit(toy, "csv-reader")  # F1 is under way: csv-reader met, json-writer ready
    _, s = full_state(toy)
    rows = {b["id"]: b for b in s["bricks"]}
    assert rows["json-writer"]["ready"] and not rows["later"]["ready"]
    assert rows["later"]["held_by"] == "F1" and rows["later"]["status"] == "unmeasured"
    assert held(s) == {"later": "F1"} and "later" not in s["ready_system"]


def test_nothing_is_held_before_a_feature_has_started_or_when_the_earlier_has_no_ready_item(toy):
    add_items(toy, sys_item("later"))
    write_features(toy, feat("F1", "csv2json", 1, 5), feat("F2", "later", 2, 5))
    _, s = full_state(toy)  # nothing started
    assert held(s) == {} and "later" in s["ready_system"]
    # started, but no F1 item is ready (json-writer is blocked, csv2json waits): F2 is not held
    measure_and_commit(toy, "csv-reader")

    def wait(d):
        for b in d["bricks"]:
            if b["id"] == "json-writer":
                b["depends_on"] = ["ghost"]  # a missing dependency blocks it

    plan_edit(toy, "bricks.json", wait)
    _, s = full_state(toy)
    rows = {b["id"]: b for b in s["bricks"]}
    assert rows["json-writer"]["status"] == "blocked" and rows["later"]["ready"]
    assert rows["later"].get("held_by") is None


def test_sellable_facts_follow_the_measured_acceptance_item(toy):
    write_features(toy, feat("SELL", "csv-reader", 1, 9), feat("NEXT", "csv2json", 2, 5))
    assert full_state(toy)[1]["value"]["sellable_at_head"] == []
    measure_and_commit(toy, "csv-reader")
    v = full_state(toy)[1]["value"]
    assert v["sellable_at_head"] == ["SELL"]
    assert v["if_stopped_today"] == [{"feature": "SELL", "slice": 1}]
    assert v["next"] == {"feature": "NEXT", "remaining_cost": 2}  # json-writer and csv2json
    _, g = cli("bh-gaps", toy)
    assert g["value"]["sellable_at_head"] == ["SELL"]


def test_the_report_markdown_lists_the_value_facts(toy):
    write_features(toy, feat("SELL", "csv-reader", 1, 9), feat("NEXT", "csv2json", 2, 5))
    measure_and_commit(toy, "csv-reader")
    cli("bh-gaps", toy, "--write")
    md = (toy / ".brick-harness" / "gaps.md").read_text()
    assert "## Value order" in md and "Sellable at HEAD: SELL" in md and "remaining cost 2" in md


def test_state_queue_is_the_whole_value_order_of_items_not_met(toy):
    add_items(toy, sys_item("extra", ["json-writer"]))
    write_features(toy, feat("F1", "csv2json", 2, 100), feat("F2", "extra", 1, 1))
    s = full_state(toy)[1]
    assert s["queue"] == ["json-writer", "extra", "csv-reader", "csv2json"]
    cfg = cfg_of(toy)
    assert s["queue"] == bhcore.value_queue(cfg, s)


def test_features_file_fails_closed_as_a_problem_and_value_queue_is_pure(toy):
    (toy / ".brick-harness" / "features.json").write_text('{"features": [{"id": "x"}]}')
    code, s = full_state(toy)
    assert code == 1 and "features" in s["problems"][0]
    cfg = cfg_of(toy)
    st = bhcore.state(cfg)
    assert bhcore.value_queue(cfg, st) == bhcore.value_queue(cfg, st)
    assert conf(toy).exists()


def test_features_schema_requires_acceptance_and_types_slice_and_value():
    schema = bhcore.load_schema("features")
    ok = {
        "features": [
            {"id": "a", "title": "t", "acceptance": "x", "slice": 1, "value": 2.5, "source": "f:1"}
        ]
    }
    assert bhcore.validate(ok, schema) == []
    bad = {"features": [{"id": "a", "title": "t", "slice": 0, "value": "x"}]}
    assert len(bhcore.validate(bad, schema)) == 3
