"""SG-15 tracker interface (mechanisms M5 to M9 of decision 0001).

Adapters are tested with fixture commands: small scripts that stand in for `bd` and `gh`,
log their arguments and print fixed JSON in the tracker's own shapes. Admission and
reconciliation run against tests/fake_tracker.py, a stateful stand-in with the six operations
the harness calls. Nothing here calls a real tracker; tests/test_tracker_beads.py runs the real
Beads binary when `bd` is on PATH.
"""

import ast
import hashlib
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

import bhcore
import bhtracker as bt
import pytest
from test_rank import edit_json
from test_toy import BIN, ENV, cli, copy_toy, git
from test_toy import commit_all as _commit_all
from test_work_tracking import change, conf, default_targets

ROOT = Path(__file__).resolve().parent.parent
FAKE = """#!{py}
import json, os, sys
d = os.environ["FAKE_DIR"]
with open(d + "/log", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
name = sys.argv[1] if sys.argv[1] != "issue" else "issue_" + sys.argv[2]
if os.path.exists(d + "/fail_" + name):
    print(open(d + "/fail_" + name).read(), file=sys.stderr)
    sys.exit(1)
if os.path.exists(d + "/out_" + name):
    print(open(d + "/out_" + name).read())
"""


def fake_cli(tmp_path, monkeypatch, name, outs, fails=None):
    """A `name` program on PATH that logs its arguments and prints outs[subcommand]."""
    d = tmp_path / "fake"
    b = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    b.mkdir(exist_ok=True)
    for k, v in outs.items():
        (d / f"out_{k}").write_text(v if isinstance(v, str) else json.dumps(v))
    for k, v in (fails or {}).items():
        (d / f"fail_{k}").write_text(v)
    exe = b / name
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{b}:{ENV['PATH']}")
    monkeypatch.setenv("FAKE_DIR", str(d))
    return exe, d


def calls(d):
    p = d / "log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def commit_all(repo, msg, *paths):
    try:
        return _commit_all(repo, msg, *paths)
    except AssertionError:  # nothing changed
        return git(repo, "rev-parse", "HEAD")


def cfg_edit(repo, **kw):
    edit_json(conf(repo), lambda c: c.update(kw))
    commit_all(repo, "config", ".brick-harness")


def plan_edit(repo, name, fn):
    edit_json(repo / ".brick-harness" / name, fn)
    commit_all(repo, f"edit {name}", ".brick-harness")


def cfg_of(repo):
    return bhcore.Config(conf(repo))


def tracker_of(repo, **conf_):
    if conf_:
        cfg_edit(repo, tracker=conf_)
    return bt.Tracker(cfg_of(repo))


class Store:
    """The fake tracker's store, an adapter for it, and seeding."""

    def __init__(self, tmp_path):
        self.path = tmp_path / "store.json"
        self.adapter = tmp_path / "fake.json"
        run = f"{sys.executable} {Path(__file__).parent / 'fake_tracker.py'} {self.path}"
        self.adapter.write_text(
            json.dumps(
                {
                    "name": "fake",
                    "id_prefix": "fk",
                    "types": {"goal": "goal", "feature": "feature", "item": "item"},
                    "commands": {
                        "ready": f"{run} ready {{limit}} [{{parent}}]",
                        "show": f"{run} show {{ref}}",
                        "list": f"{run} list {{limit}}",
                        "claim": f"{run} claim {{ref}} {{actor}}",
                        "close": f"{run} close {{ref}} {{reason}}",
                        "reopen": f"{run} reopen {{ref}} {{reason}}",
                    },
                    "missing": "no entry",
                    "release": f"{run} reopen {{ref}} released",
                }
            )
        )

    @property
    def db(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def add(self, title, type="item", parent=None, deps=(), **kw):
        db = self.db
        ref = f"t-{len(db) + 1}"
        db[ref] = {
            "ref": ref,
            "title": title,
            "body": f"body of {title}",
            "state": "open",
            "type": type,
            "assignee": None,
            "parent": parent,
            "deps": list(deps),
            **kw,
        }
        self.path.write_text(json.dumps(db))
        return ref

    def put(self, ref, **kw):
        db = self.db
        db[ref].update(kw)
        self.path.write_text(json.dumps(db))


def with_store(toy, tmp_path, goal=None, horizon=5, **extra):
    st = Store(tmp_path)
    t = {"adapter": str(st.adapter), "actor": "me", **extra}
    if goal:
        t["goal"] = goal
    cfg_edit(toy, tracker=t, horizon={"items": horizon})
    return st


# ---------------------------------------------------------------- M5: the runner


def test_placeholders_are_shell_quoted_and_empty_parts_dropped():
    out = bt.render("x {a} [--p {p}] [--q {q}]", {"a": "it's; x", "p": "", "q": ["a", "b"]})
    assert out == "x 'it'\"'\"'s; x'  --q 'a b'".replace(
        "'a b'", "'['\"'\"'a'\"'\"', '\"'\"'b'\"'\"']'"
    )
    with pytest.raises(bhcore.HarnessError):
        bt.render("x {missing}", {})


def test_no_tracker_configured_means_bricks_json_is_the_work_list(toy):
    cfg = cfg_of(toy)
    assert not bt.configured(cfg)
    with pytest.raises(bhcore.HarnessError, match="no tracker configured"):
        bt.Tracker(cfg)
    out = cli("bh-admit", toy, "--write")[1]
    assert out["tracker"] is None and out["admitted"] == [] and out["unreachable"] is None
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["tracker"] is None and out["mismatches"] == [] and out["facts"] == []
    _, st = cli("bh-state", toy, "--part", "decision")
    assert st["decision"]["ready"]  # the work list: bricks.json in build order


def test_every_operation_runs_its_command_and_reads_the_entry_shape(toy, tmp_path):
    s = with_store(toy, tmp_path)
    goal = s.add("goal", "goal")
    a = s.add("a", parent=goal)
    s.add("b", parent=goal, deps=[a])
    tr = bt.Tracker(cfg_of(toy))
    assert tr.name == "fake" and tr.show(a)["title"] == "a" and tr.show(a)["parent"] == goal
    assert [e["ref"] for e in tr.ready(parent=goal)["entries"]] == [a]  # b is blocked
    assert tr.claim(a) == {"claimed": True, "holder": "me", "by": "tracker"}
    assert tr.show(a)["assignee"] == "me" and tr.show(a)["state"] == "in_progress"
    assert tr.ready(parent=goal)["entries"] == []
    tr.close_entry(a, "why")
    assert tr.show(a)["state"] == "closed"
    tr.reopen_entry(a, "again")
    assert tr.show(a)["state"] == "open"
    with pytest.raises(bt.TrackerError) as err:
        tr.show("t-99")
    assert tr.missing(err.value)


def test_list_asks_one_more_and_reports_more(toy, tmp_path):
    s = with_store(toy, tmp_path)
    for i in range(5):
        s.add(f"t{i}")
    tr = bt.Tracker(cfg_of(toy))
    got = tr.list(limit=3)
    assert len(got["entries"]) == 3 and got["more"] is True
    assert tr.list(limit=5)["more"] is False


def test_without_a_claim_command_the_entry_is_taken_and_branches_keep_builders_apart(toy, tmp_path):
    s = with_store(toy, tmp_path)
    ref = s.add("a")
    ad = json.loads(s.adapter.read_text())
    del ad["commands"]["claim"]
    s.adapter.write_text(json.dumps(ad))
    tr = bt.Tracker(cfg_of(toy))
    assert tr.claim(ref) == {"claimed": True, "holder": "me", "by": "branch"}
    assert s.db[ref]["assignee"] is None


def test_output_that_fails_the_schema_is_a_reported_error(toy, tmp_path, monkeypatch):
    fake_cli(
        tmp_path, monkeypatch, "gh", {"issue_view": {"number": 1, "title": "t", "state": "WEIRD"}}
    )
    tr = tracker_of(toy, adapter="github")
    with pytest.raises(bt.TrackerError, match="entry schema"):
        tr.show("1")


def test_a_failed_command_is_an_error_with_its_exit_and_text(toy, tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "gh", {}, {"issue_view": "boom"})
    tr = tracker_of(toy, adapter="github")
    with pytest.raises(bt.TrackerError, match="exited 1: boom"):
        tr.show("1")


def test_a_command_that_outlives_its_timeout_is_a_timeout_error(toy, tmp_path):
    s = with_store(
        toy, tmp_path, timeout_s=1, commands={"show": "python3 -c 'import time; time.sleep(5)'"}
    )
    tr = bt.Tracker(cfg_of(toy))
    with pytest.raises(bt.TrackerTimeout):
        tr.show("t-1")
    assert s.db == {}


def test_target_source_is_resolved_through_show_by_bh_gaps_and_never_by_state(toy, tmp_path):
    s = with_store(toy, tmp_path)
    ref = s.add("p99 under 40 ms")
    s.put(ref, body="the budget is 40 ms")
    plan_edit(
        toy,
        "targets.json",
        lambda d: d["targets"][2].update(source=f'{ref}: "budget is 40 ms"', value=40),
    )
    code, rep = cli("bh-gaps", toy)
    bad = [g for g in rep["gaps"] if g["kind"] == "target-without-source"]
    assert not any("budget" in g["summary"] for g in bad)
    plan_edit(
        toy, "targets.json", lambda d: d["targets"][2].update(source=f'{ref}: "budget is 41 ms"')
    )
    _, rep = cli("bh-gaps", toy)
    assert any("does not contain the quoted text" in g["summary"] for g in rep["gaps"])
    plan_edit(toy, "targets.json", lambda d: d["targets"][2].update(source='w-nope: "x 40"'))
    _, rep = cli("bh-gaps", toy)
    assert any("cannot be read from the tracker" in g["summary"] for g in rep["gaps"])
    _, st = cli("bh-state", toy, "--part", "gaps")  # state never reaches the tracker
    assert not any("tracker" in g["summary"] for g in st["gaps"])


def test_measure_build_and_merge_never_call_the_tracker():
    for n in ("bh-measure", "bh-merge", "bh-branch", "bh-state", "bh-commit", "bh-init", "bh-rank"):
        assert "bhtracker" not in (BIN / n).read_text(), n
    assert "bhtracker" not in (ROOT / "lib" / "bhcore.py").read_text()
    for w in ("harness-build.js", "harness-measure.js"):
        assert not re.search(r"bh-(admit|reconcile)", (ROOT / "workflows" / w).read_text()), w


def test_close_and_reopen_are_called_only_from_reconcile():
    names = {"close_entry", "reopen_entry"}
    for p in [
        *(ROOT.parent / "bin").glob("bh-*"),
        *(ROOT / "lib").glob("*.py"),
        *(ROOT / "workflows").glob("*.js"),
    ]:
        if names & set(re.findall(r"\w+", p.read_text())):
            assert p.name in ("bhtracker.py", "bh-reconcile"), p.name
    tree = ast.parse((ROOT / "lib" / "bhtracker.py").read_text())
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        called = {
            c.func.attr
            for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
        }
        if called & names:
            assert fn.name == "reconcile", fn.name


# ---------------------------------------------------------------- M6: adapters are data

OPS = {"ready", "show", "list", "claim", "close", "reopen"}


def test_adapters_are_valid_data_with_only_the_operations_the_harness_calls():
    schema = bhcore.load_schema("tracker")
    for n in ("beads", "github"):
        ad = json.loads((ROOT / "adapters" / f"{n}.json").read_text())
        assert bhcore.validate(ad, schema["$defs"]["adapter"], schema) == []
        assert set(ad["commands"]) == OPS, n
        assert "capabilities" not in ad
    beads = json.loads((ROOT / "adapters" / "beads.json").read_text())
    assert beads["types"] == {"goal": "epic", "feature": "feature", "item": "task"}
    assert re.fullmatch(r"[0-9a-f]{64}", beads["pin"]["sha256"]["linux_amd64"])
    bad = {"name": "x", "commands": {"ready": "r", "show": "s", "create": "c"}}
    assert bhcore.validate(bad, schema["$defs"]["adapter"], schema)  # no operation nothing calls


BD_TASK = {
    "id": "p-1.1",
    "title": "Task one",
    "description": "b",
    "status": "in_progress",
    "issue_type": "task",
    "assignee": "bh-x",
    "parent": "p-1",
    "dependencies": [
        {"id": "p-1.0", "dependency_type": "blocks"},
        {"id": "p-1", "dependency_type": "parent-child"},
    ],
}


def beads_env(tmp_path, monkeypatch, outs, fails=None):
    exe, d = fake_cli(tmp_path, monkeypatch, "bd", outs, fails)
    return d, {"adapter": "beads", "pin": {"sha256": sha256(exe)}, "actor": "bh-test"}


def test_beads_adapter_maps_every_command_and_reads_its_json(toy, tmp_path, monkeypatch):
    d, conf_ = beads_env(
        tmp_path,
        monkeypatch,
        {
            "show": [BD_TASK],
            "list": [{**BD_TASK, "dependencies": [{"depends_on_id": "p-1.0", "type": "blocks"}]}],
            "ready": [BD_TASK],
            "update": [BD_TASK],
            "close": [BD_TASK],
            "reopen": [BD_TASK],
        },
    )
    tr = tracker_of(toy, **conf_)
    assert not tr.facts
    e = tr.show("p-1.1")
    assert (e["ref"], e["state"], e["type"], e["assignee"], e["parent"], e["deps"]) == (
        "p-1.1",
        "in_progress",
        "item",
        "bh-x",
        "p-1",
        ["p-1.0"],
    )
    assert tr.list(type="item")["entries"][0]["deps"] == ["p-1.0"]
    assert tr.ready(limit=4, parent="p-1")["entries"][0]["ref"] == "p-1.1"
    assert tr.claim("p-1.1") == {"claimed": True, "holder": "bh-test", "by": "tracker"}
    tr.close_entry("p-1.1", "why", "bh-x")
    tr.reopen_entry("p-1.1", "why", "bh-x")
    by = {c[0]: c for c in calls(d)}
    assert (
        by["ready"][1:6] == ["--json", "--brief", "-t", "task", "-n"]
        and "5" in by["ready"]
        and "--parent" in by["ready"]
    )
    assert "open,in_progress,blocked,deferred" in by["list"]
    assert by["update"][:3] == ["update", "p-1.1", "--claim"]
    for op in ("close", "reopen"):  # acting as the claim holder
        assert by[op][by[op].index("--actor") + 1] == "bh-x"
    assert all("--actor" in c for c in calls(d))


def test_beads_claim_refused_for_another_holder_is_claimed_elsewhere(toy, tmp_path, monkeypatch):
    d, conf_ = beads_env(
        tmp_path, monkeypatch, {"show": [{**BD_TASK, "assignee": "other"}]}, {"update": "held"}
    )
    tr = tracker_of(toy, **conf_)
    assert tr.claim("p-1.1") == {"claimed": False, "holder": "other", "by": "tracker"}
    assert tr.facts == [{"kind": "claimed-elsewhere", "ref": "p-1.1", "holder": "other"}]
    d2, conf2 = beads_env(
        tmp_path, monkeypatch, {"show": [{**BD_TASK, "assignee": None}]}, {"update": "db down"}
    )
    with pytest.raises(bt.TrackerError):
        tracker_of(toy, **conf2).claim("p-1.1")


def test_pin_mismatch_is_not_run_and_the_tracker_is_unreachable_with_the_fact(
    toy, tmp_path, monkeypatch
):
    d, _ = beads_env(tmp_path, monkeypatch, {"show": [BD_TASK]})
    cfg_edit(toy, tracker={"adapter": "beads"})  # no sha256 for the fake: a mismatch
    with pytest.raises(bt.TrackerError, match="not run"):
        bt.Tracker(cfg_of(toy))
    out = bt.admit(cfg_of(toy), write=True)
    assert out["admitted"] == [] and "not run" in out["unreachable"]
    cfg_edit(toy, tracker={"adapter": "beads", "pin": {"sha256": "0" * 64}})
    with pytest.raises(bt.TrackerError, match="is not the pin"):
        bt.Tracker(cfg_of(toy))
    assert calls(d) == []  # the binary was never executed, not even for a version check


def test_config_overrides_any_adapter_command_and_adapters_load_from_a_path(
    toy, tmp_path, monkeypatch
):
    fake_cli(
        tmp_path, monkeypatch, "gh", {"issue_view": {"number": 7, "title": "t", "state": "OPEN"}}
    )
    tr = tracker_of(
        toy, adapter="github", commands={"show": "gh issue view {ref} --json number,title,state"}
    )
    assert tr.show("7")["ref"] == "7"
    ad = json.loads((ROOT / "adapters" / "github.json").read_text())
    ad["name"] = "mine"
    (toy / "mine.json").write_text(json.dumps(ad))
    assert tracker_of(toy, adapter="mine.json").name == "mine"


def test_github_adapter_renders_every_command_and_reads_its_json(toy, tmp_path, monkeypatch):
    issue = {
        "number": 12,
        "title": "T",
        "body": "text",
        "state": "OPEN",
        "assignees": [{"login": "u"}],
        "issueType": {"name": "Task"},
        "parent": {"number": 3},
        "blockedBy": [{"number": 5}],
    }
    _, d = fake_cli(tmp_path, monkeypatch, "gh", {"issue_view": issue, "issue_list": [issue]})
    tr = tracker_of(toy, adapter="github")
    e = tr.show("12")
    assert (e["ref"], e["state"], e["type"], e["assignee"], e["parent"], e["deps"], e["body"]) == (
        "12",
        "open",
        "item",
        "u",
        "3",
        ["5"],
        "text",
    )
    assert tr.ready(limit=2)["entries"][0]["ref"] == "12"
    assert tr.list()["entries"][0]["ref"] == "12"
    assert tr.claim("12") == {"claimed": True, "holder": tr.actor, "by": "tracker"}
    tr.close_entry("12", "met")
    tr.reopen_entry("12", "unmet")
    log = calls(d)
    ready = next(c for c in log if c[:2] == ["issue", "list"])
    assert ready[ready.index("--search") + 1] == "no:assignee -is:blocked type:Task"
    assert ready[ready.index("--limit") + 1] == "3"  # one more than asked: a cut is reported
    assert any(c[:2] == ["issue", "edit"] and "--add-assignee" in c for c in log)
    assert any(c[:2] == ["issue", "close"] and "completed" in c for c in log)
    assert any(c[:2] == ["issue", "reopen"] for c in log)


def test_every_shipped_command_renders_to_valid_shell():
    vals = {"actor": "a", "ref": "r", "type": "task", "parent": "p", "limit": 3, "reason": "why"}
    for n in ("beads", "github"):
        ad = json.loads((ROOT / "adapters" / f"{n}.json").read_text())
        for op, tpl in ad["commands"].items():
            cmd = bt.render(tpl, vals)
            assert subprocess.run(["sh", "-n", "-c", cmd]).returncode == 0, (n, op, cmd)


# ---------------------------------------------------------------- M9: admission


def admit_setup(toy, tmp_path, n=3, horizon=None):
    s = with_store(toy, tmp_path, horizon=horizon or 5)
    goal = s.add("goal", "goal")
    cfg_edit(toy, tracker={"adapter": str(s.adapter), "actor": "me", "goal": goal})
    return s, goal, [s.add(f"task {i}", parent=goal) for i in range(n)]


def test_admission_takes_ready_leaves_in_order_up_to_the_room_and_claims_first(toy, tmp_path):
    s, goal, refs = admit_setup(toy, tmp_path, n=4)  # toy has 3 items not met: room is 2
    dry = cli("bh-admit", toy)[1]
    assert (
        dry["room"] == 2 and [a["ref"] for a in dry["admit"]] == refs[:2] and dry["admitted"] == []
    )
    assert dry["not_admitted"] == 2 and dry["tracker"] == "fake"
    assert not any(e["assignee"] for e in s.db.values())  # nothing claimed without --write
    out = cli("bh-admit", toy, "--write")[1]
    assert out["admitted"] == [a["id"] for a in dry["admit"]]
    items = json.loads((toy / ".brick-harness/bricks.json").read_text())["bricks"]
    new = [b for b in items if b.get("refs")]
    assert [b["refs"] for b in new] == [[r] for r in refs[:2]] and all(
        b["kind"] == "change" for b in new
    )
    assert new[0]["id"] == bt.item_id(bt.load_adapter(cfg_of(toy)), refs[0])
    assert [r for r in refs if s.db[r]["assignee"] == "me"] == refs[:2]
    # a repeat takes nothing more: the room is used and the ids exist
    again = cli("bh-admit", toy, "--write")[1]
    assert again["admitted"] == [] and again["room"] == 0 and again["stalled"]["horizon"] == 5


def test_a_readmission_after_a_crash_between_claim_and_write_adopts_the_claimed_entry(
    toy, tmp_path
):
    s, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    bt.Tracker(cfg_of(toy)).claim(refs[0])  # claimed, never written to bricks.json
    out = cli("bh-admit", toy, "--write")[1]
    ad = bt.load_adapter(cfg_of(toy))
    assert set(out["admitted"]) == {bt.item_id(ad, r) for r in refs}
    assert out["claim_held"] == []


def test_a_claim_held_elsewhere_is_a_fact_with_its_release_command_and_the_entry_is_not_admitted(
    toy, tmp_path
):
    s, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    s.put(refs[0], assignee="someone-else", state="in_progress")
    out = cli("bh-admit", toy, "--write")[1]
    assert [bt.item_id(bt.load_adapter(cfg_of(toy)), refs[1])] == out["admitted"]
    assert out["not_admitted"] == 0  # a claimed entry is not ready, so it is not a candidate
    assert [(c["ref"], c["holder"]) for c in out["claim_held"]] == [(refs[0], "someone-else")]
    assert refs[0] in out["claim_held"][0]["release"]


def test_a_claim_refused_at_write_time_is_claimed_elsewhere(toy, tmp_path):
    s, goal, refs = admit_setup(toy, tmp_path, n=1, horizon=10)
    tr = bt.Tracker(cfg_of(toy))
    s.put(refs[0], assignee="someone-else")  # taken between the ready read and the claim
    assert tr.claim(refs[0]) == {"claimed": False, "holder": "someone-else", "by": "tracker"}


def test_admission_order_is_one_call_ranking_queued_items_first_then_the_trackers_order(toy):
    cfg = cfg_of(toy)
    ad = {"name": "fake", "id_prefix": "fk"}
    st = bhcore.state(cfg)
    queue = bhcore.value_queue(cfg, st)
    ref_b = "w-b"
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(refs=[ref_b]))
    cfg = cfg_of(toy)
    st = bhcore.state(cfg)
    es = [{"ref": "w-new1"}, {"ref": ref_b}, {"ref": "w-new2"}]
    got = [e["ref"] for e in bt.admission_order(cfg, es, st, ad)]
    assert got == [ref_b, "w-new1", "w-new2"] and queue  # an item first, the rest in tracker order
    src = (ROOT / "lib" / "bhtracker.py").read_text()
    assert src.count("admission_order(") == 2  # the definition and the one call in admit


def test_an_unreachable_tracker_admits_nothing_and_says_so(toy, tmp_path):
    with_store(toy, tmp_path, commands={"ready": "false"})
    out = cli("bh-admit", toy, "--write")[1]
    assert out["admitted"] == [] and "exited" in out["unreachable"]


def test_a_stalled_horizon_lists_the_gaps_that_block_items(toy, tmp_path):
    admit_setup(toy, tmp_path, n=1, horizon=1)
    out = cli("bh-admit", toy)[1]
    assert out["room"] == 0 and out["stalled"]["horizon"] == 1 and "blocked" in out["stalled"]


# ---------------------------------------------------------------- M8: reconciliation


def admitted(toy, tmp_path):
    s, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    cli("bh-admit", toy, "--write")
    plan_edit(
        toy,
        "targets.json",
        lambda d: d["targets"].extend(
            default_targets(bt.item_id(bt.load_adapter(cfg_of(toy)), refs[0]))
        ),
    )
    commit_all(toy, "admitted", ".brick-harness")
    return s, refs


def test_reconcile_lists_and_fixes_mismatches_and_touches_only_admitted_entries(toy, tmp_path):
    s, refs = admitted(toy, tmp_path)
    stray = s.add("not ours")
    s.put(refs[1], state="closed")  # a person closed it; item not met: a mismatch
    out = cli("bh-reconcile", toy)[1]
    ad = bt.load_adapter(cfg_of(toy))
    assert out["mismatches"] == [
        {"kind": "tracker-closed-unmet", "item": bt.item_id(ad, refs[1]), "ref": refs[1]}
    ]
    assert out["reopened"] == [] and s.db[refs[1]]["state"] == "closed"  # listing changes nothing
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["reopened"] == [refs[1]] and out["closed"] == [] and out["checked"] == 2
    assert s.db[refs[1]]["state"] == "open" and s.db[stray]["state"] == "open"
    again = cli("bh-reconcile", toy, "--write")[1]
    assert again["mismatches"] == [] and again["reopened"] == [] and again["closed"] == []


def test_reconcile_closes_an_entry_only_when_its_item_is_measured_met(toy, tmp_path):
    from test_work_tracking import measure_and_commit

    s = with_store(toy, tmp_path)
    ref = s.add("read csv")
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(refs=[ref]))
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["closed"] == [] and s.db[ref]["state"] == "open"  # not measured: nothing closes
    measure_and_commit(toy, "csv-reader")  # the measurer, at HEAD, says met
    assert cli("bh-reconcile", toy)[1]["mismatches"][0]["kind"] == "tracker-open-met"
    assert s.db[ref]["state"] == "open"
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["closed"] == [ref] and s.db[ref]["state"] == "closed"
    assert re.fullmatch(r"measured met at [0-9a-f]{12}", s.db[ref]["note"])
    again = cli("bh-reconcile", toy, "--write")[1]
    assert again["closed"] == [] and again["mismatches"] == []


def test_a_missing_ref_is_a_fact_and_nothing_is_deleted(toy, tmp_path):
    s, refs = admitted(toy, tmp_path)
    db = s.db
    del db[refs[1]]
    s.path.write_text(json.dumps(db))
    out = cli("bh-reconcile", toy, "--write")[1]
    ad = bt.load_adapter(cfg_of(toy))
    assert {"kind": "ref-missing", "item": bt.item_id(ad, refs[1]), "ref": refs[1]} in out["facts"]
    assert refs[0] in s.db


def test_the_gaps_report_lists_tracker_mismatches_as_facts_and_changes_no_status(toy, tmp_path):
    s, refs = admitted(toy, tmp_path)
    s.put(refs[1], state="closed")
    _, before = cli("bh-state", toy, "--part", "decision")
    _, rep = cli("bh-gaps", toy)
    assert any(f["kind"] == "tracker-closed-unmet" and f["ref"] == refs[1] for f in rep["facts"])
    _, after = cli("bh-state", toy, "--part", "decision")
    assert before["decision"]["counts"] == after["decision"]["counts"]


# ---------------------------------------------------------------- M11, M12: INVEST, flow, split


def split_plan(d):
    d["bricks"] += [
        change("parent-x", features=["F1"]),
        change("kid-a", split_from="parent-x", split_kind="path"),
        change("kid-b", split_from="parent-x"),
    ]


def with_split(toy):
    plan_edit(toy, "bricks.json", split_plan)
    plan_edit(
        toy,
        "targets.json",
        lambda d: d["targets"].extend(
            default_targets("kid-a") + default_targets("kid-b") + default_targets("parent-x")
        ),
    )


def test_only_leaves_run_a_split_parent_is_measured_never_built(toy):
    with_split(toy)
    _, st = cli("bh-state", toy, "--part", "decision")
    d = st["decision"]
    assert "parent-x" not in d["ready"] + d["ready_system"]
    assert {"kid-a", "kid-b"} <= set(d["ready"])
    _, full = cli("bh-state", toy, "--part", "bricks")
    parent = next(b for b in full["bricks"] if b["id"] == "parent-x")
    assert parent["split_parent"] is True and parent["ready"] is False  # waits for its children
    for k in ("kid-a", "kid-b"):
        assert next(b for b in full["bricks"] if b["id"] == k)["split_parent"] is False


def test_new_fields_are_optional_so_the_toy_stays_valid(toy):
    code, st = cli("bh-state", toy, "--part", "problems")
    assert code == 0 and st["problems"] == []
