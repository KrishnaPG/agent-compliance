"""SG-15 tracker interface (mechanisms M5 to M12 of decision 0001).

Adapters are tested with fixture commands: small scripts that stand in for `bd` and `gh`,
log their arguments and print fixed JSON in the tracker's own shapes. The files adapter is a
real, stateful tracker, so admission, reconciliation, filing and the git claim are tested
against it. Nothing here calls a real tracker; tests/test_tracker_beads.py runs the real Beads
binary when `bd` is on PATH.
"""

import ast
import json
import re
import shutil
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


def with_origin(repo, tmp_path, name="origin.git"):
    o = tmp_path / name
    subprocess.run(["git", "init", "-q", "--bare", str(o)], check=True, env=ENV)
    git(repo, "remote", "add", "origin", str(o))
    git(repo, "push", "-q", "origin", "main")
    return o


def clone(origin, dest):
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True, env=ENV)
    return dest


def tracker_of(repo, **conf_):
    if conf_:
        cfg_edit(repo, tracker=conf_)
    return bt.Tracker(cfg_of(repo))


def seed(tr, n, parent=None):
    return [tr.create(f"task {i}", f"body {i}", "item", parent) for i in range(n)]


# ---------------------------------------------------------------- M5: the runner


def test_placeholders_are_shell_quoted_and_empty_parts_dropped():
    out = bt.render("x {a} [--p {p}] [--q {q}]", {"a": "it's; x", "p": "", "q": ["a", "b"]})
    assert out == "x 'it'\"'\"'s; x'  --q a,b"
    with pytest.raises(bhcore.HarnessError):
        bt.render("x {missing}", {})


def test_an_unconfigured_tracker_is_the_files_adapter(toy):
    tr = bt.Tracker(cfg_of(toy))
    assert tr.name == "files" and tr.caps["atomic_claim"] is False and tr.caps["hierarchy"]
    assert bt.actor_of(cfg_of(toy)).startswith("bh-") and "@" not in tr.actor


def test_every_operation_runs_its_command_and_reads_the_entry_shape(toy, tmp_path):
    tr = tracker_of(toy)
    goal = tr.create("goal", "", "goal")
    a, b = (
        tr.create("a", "bodya", "item", goal),
        tr.create("b", "", "item", goal, [("blocks", "x")]),
    )
    assert tr.show(a)["parent"] == goal and tr.show(a)["type"] == "item"
    assert tr.show(b)["deps"] == ["x"]
    got = tr.list(type="item")
    assert [e["ref"] for e in got["entries"]] == [a, b] and got["more"] is False
    tr.link(a, b, "blocks")
    assert tr.show(a)["deps"] == [b]
    tr.defer_entry(b, "later")
    assert tr.show(b)["state"] == "deferred"
    tr.close_entry(a, "done")
    assert tr.show(a)["state"] == "closed"
    tr.reopen_entry(a, "no")
    assert tr.show(a)["state"] == "open"
    assert tr.claim(a)["claimed"] is True
    assert tr.ready(parent=goal)["entries"] == []  # a blocks on b which is open and a has no deps


def test_list_asks_one_more_and_reports_more(toy):
    tr = tracker_of(toy)
    seed(tr, 5)
    got = tr.list(limit=3)
    assert len(got["entries"]) == 3 and got["more"] is True
    assert tr.list(limit=5)["more"] is False


def test_output_that_fails_the_schema_is_a_reported_error(toy, tmp_path, monkeypatch):
    fake_cli(
        tmp_path, monkeypatch, "gh", {"issue_view": {"number": 1, "title": "t", "state": "WEIRD"}}
    )
    tr = tracker_of(toy, adapter="github")
    with pytest.raises(bt.TrackerError, match="entry schema"):
        tr.show("#1")


def test_a_failed_command_is_an_error_with_its_exit_and_text(toy, tmp_path, monkeypatch):
    fake_cli(tmp_path, monkeypatch, "gh", {}, {"issue_view": "boom"})
    tr = tracker_of(toy, adapter="github")
    with pytest.raises(bt.TrackerError, match="exited 1: boom"):
        tr.show("#1")


def test_a_command_that_outlives_its_timeout_is_a_timeout_error(toy):
    tr = tracker_of(toy, commands={"show": "python3 -c 'import time; time.sleep(5)'"}, timeout_s=1)
    with pytest.raises(bt.TrackerTimeout):
        tr.show("w-x")


def test_target_source_is_resolved_through_show_by_bh_gaps_and_never_by_state(toy):
    tr = tracker_of(toy)
    ref = tr.create("p99 under 40 ms", "the budget is 40 ms", "item")
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
        assert not re.search(
            r"bh-(admit|file|reconcile|work)", (ROOT / "workflows" / w).read_text()
        ), w


def test_close_and_reopen_are_called_only_from_reconcile():
    names = {"close_entry", "reopen_entry"}
    for p in [
        *(ROOT.parent / "bin").glob("bh-*"),
        *(ROOT / "lib").glob("*.py"),
        *(ROOT / "workflows").glob("*.js"),
    ]:
        text = p.read_text()
        if not names & set(re.findall(r"\w+", text)):
            continue
        assert p.name in ("bhtracker.py", "bh-reconcile") or p.name == "bh-reconcile", p.name
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


def test_adapters_are_valid_data_with_the_nine_operations_and_five_capabilities():
    schema = bhcore.load_schema("tracker")
    for n in ("beads", "github", "files"):
        ad = json.loads((ROOT / "adapters" / f"{n}.json").read_text())
        assert bhcore.validate(ad, schema["$defs"]["adapter"], schema) == []
        assert set(ad["capabilities"]) == {
            "atomic_claim",
            "hierarchy",
            "defer",
            "compaction",
            "ready_filter",
        }
        have = set(ad["commands"]) | (
            {"claim"} if not ad["capabilities"]["atomic_claim"] else set()
        )
        have |= {"ready"} if not ad["capabilities"]["ready_filter"] else set()
        assert have == set(bt.OPS), n
    beads = json.loads((ROOT / "adapters" / "beads.json").read_text())
    assert beads["types"] == {"goal": "epic", "feature": "feature", "item": "task"}
    assert re.fullmatch(r"[0-9a-f]{64}", beads["pin"]["sha256"]["linux_amd64"])


BD_TASK = {
    "id": "p-1.1",
    "title": "Task one",
    "description": "b",
    "status": "in_progress",
    "issue_type": "task",
    "assignee": "bh-x",
    "labels": ["l"],
    "metadata": {"bh_key": "k"},
    "parent": "p-1",
    "dependencies": [
        {"id": "p-1.0", "dependency_type": "blocks"},
        {"id": "p-1", "dependency_type": "parent-child"},
    ],
}


def beads_env(tmp_path, monkeypatch, outs, fails=None):
    exe, d = fake_cli(tmp_path, monkeypatch, "bd", outs, fails)
    sha = bt.file_sha256(str(exe))
    return d, {"adapter": "beads", "pin": {"sha256": sha}, "actor": "bh-test"}


def test_beads_adapter_maps_every_command_and_reads_its_json(toy, tmp_path, monkeypatch):
    d, conf_ = beads_env(
        tmp_path,
        monkeypatch,
        {
            "show": [BD_TASK],
            "list": [{**BD_TASK, "dependencies": [{"depends_on_id": "p-1.0", "type": "blocks"}]}],
            "ready": [BD_TASK],
            "create": {"id": "p-9"},
            "update": [BD_TASK],
            "close": [BD_TASK],
            "reopen": [BD_TASK],
            "defer": [BD_TASK],
            "link": {"ok": 1},
        },
    )
    tr = tracker_of(toy, **conf_)
    assert tr.pinned_binary and not tr.facts
    e = tr.show("p-1.1")
    assert (e["ref"], e["state"], e["type"], e["assignee"], e["parent"], e["deps"]) == (
        "p-1.1",
        "in_progress",
        "item",
        "bh-x",
        "p-1",
        ["p-1.0"],
    )
    assert tr.list(state="live", type="item", parent="p-1", key="k")["entries"][0]["deps"] == [
        "p-1.0"
    ]
    assert tr.ready(limit=4, parent="p-1")["entries"][0]["ref"] == "p-1.1"
    assert (
        tr.create("T", "B", "item", "p-1", [("discovered-from", "p-0")], ["x"], {"bh_key": "k"})
        == "p-9"
    )
    tr.link("p-1.1", "p-0", "related")
    assert tr.claim("p-1.1") == {"claimed": True, "holder": "bh-test", "by": "tracker"}
    tr.defer_entry("p-1.1", "r")
    tr.close_entry("p-1.1", "why", "bh-x")
    tr.reopen_entry("p-1.1", "why", "bh-x")
    by = {c[0]: c for c in calls(d)}
    assert (
        by["ready"][1:6] == ["--json", "--brief", "-t", "task", "-n"]
        and "5" in by["ready"]
        and "--parent" in by["ready"]
    )
    assert "open,in_progress,blocked,deferred" in by["list"] and "bh_key=k" in by["list"]
    cr = by["create"]
    assert cr[cr.index("--deps") + 1] == "discovered-from:p-0" and cr[cr.index("-t") + 1] == "task"
    assert json.loads(cr[cr.index("--metadata") + 1]) == {"bh_key": "k"}
    assert by["update"][:3] == ["update", "p-1.1", "--claim"]
    assert by["link"][1:5] == ["p-1.1", "p-0", "--type", "related"]
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


def test_pin_mismatch_is_not_run_and_the_files_adapter_serves_that_run(toy, tmp_path, monkeypatch):
    d, _ = beads_env(tmp_path, monkeypatch, {"show": [BD_TASK]})
    tr = tracker_of(toy, adapter="beads")  # no sha256 for the fake: a mismatch
    assert tr.name == "files" and tr.fallback and tr.pinned_binary is None
    assert (
        tr.facts[0]["kind"] == "pin-mismatch" and tr.facts[0]["actual"] != tr.facts[0]["expected"]
    )
    ref = tr.create("served by files", "", "item")
    assert tr.show(ref)["title"] == "served by files"
    assert calls(d) == []  # the binary was never executed, not even for a version check
    bad = tracker_of(toy, adapter="beads", pin={"sha256": "0" * 64})
    assert bad.facts[0]["kind"] == "pin-mismatch" and calls(d) == []


def test_config_overrides_any_adapter_command_and_adapters_load_from_a_path(
    toy, tmp_path, monkeypatch
):
    fake_cli(
        tmp_path, monkeypatch, "gh", {"issue_view": {"number": 7, "title": "t", "state": "OPEN"}}
    )
    tr = tracker_of(
        toy, adapter="github", commands={"show": "gh issue view {ref} --json number,title,state"}
    )
    assert tr.show("#7")["ref"] == "#7"
    ad = json.loads((ROOT / "adapters" / "files.json").read_text())
    ad["name"] = "mine"
    (toy / "mine.json").write_text(json.dumps(ad))
    assert tracker_of(toy, adapter="mine.json").name == "mine"


def test_github_adapter_renders_every_command_and_reads_its_json(toy, tmp_path, monkeypatch):
    issue = {
        "number": 12,
        "title": "T",
        "body": 'text\n\n<!-- bh-meta: {"bh_key":"k"} -->',
        "state": "OPEN",
        "labels": [{"name": "bh-deferred"}],
        "assignees": [{"login": "u"}],
        "issueType": {"name": "Task"},
        "parent": {"number": 3},
        "blockedBy": [{"number": 5}],
        "url": "https://x/12",
    }
    _, d = fake_cli(
        tmp_path,
        monkeypatch,
        "gh",
        {
            "issue_view": issue,
            "issue_list": [issue],
            "issue_create": "https://github.com/o/r/issues/44",
        },
    )
    tr = tracker_of(toy, adapter="github")
    e = tr.show("#12")
    assert (e["ref"], e["state"], e["type"], e["assignee"], e["parent"], e["deps"], e["body"]) == (
        "#12",
        "deferred",
        "item",
        "u",
        "#3",
        ["#5"],
        "text",
    )
    assert e["metadata"] == {"bh_key": "k"}
    assert tr.list(key="k")["entries"][0]["ref"] == "#12" and tr.list(key="zz")["entries"] == []
    ref = tr.create(
        "T",
        "B",
        "item",
        "#3",
        [("blocks", "#5"), ("discovered-from", "#9")],
        ["a"],
        {"bh_key": "k"},
    )
    assert ref == "#44"
    log = calls(d)
    create = next(c for c in log if c[:2] == ["issue", "create"])
    assert (
        create[create.index("--type") + 1] == "Task"
        and create[create.index("--blocked-by") + 1] == "#5"
    )
    assert "<!-- bh-meta:" in create[create.index("--body") + 1]
    assert any(
        c[:2] == ["issue", "comment"] and "discovered-from #9" in c[-1] for c in log
    )  # linked afterwards
    tr.link("#44", "#6", "blocks")
    tr.link("#44", "#6", "parent-child")
    tr.defer_entry("#44", "r")
    tr.close_entry("#44", "met")
    tr.reopen_entry("#44", "unmet")
    edits = [" ".join(c) for c in calls(d) if c[:2] == ["issue", "edit"]]
    assert any("--add-blocked-by #6" in x for x in edits) and any(
        "#6 --add-sub-issue #44" in x for x in edits
    )
    assert any("--add-label bh-deferred" in x for x in edits)
    assert any(c[:2] == ["issue", "close"] and "completed" in c for c in calls(d))
    assert tr.caps == {
        "atomic_claim": False,
        "hierarchy": True,
        "defer": False,
        "compaction": False,
        "ready_filter": False,
    }


def test_every_shipped_command_renders_to_valid_shell():
    vals = {
        "actor": "a",
        "ref": "r",
        "to": "t",
        "kind": "blocks",
        "title": "T",
        "body": "B",
        "type": "task",
        "parent": "p",
        "deps": ["d"],
        "labels": ["l"],
        "metadata": {"k": 1},
        "limit": 3,
        "state": "open",
        "key": "k",
        "metadata_field": "bh_key=k",
        "reason": "why",
        "comment": "c",
    }
    for n in ("beads", "github", "files"):
        ad = json.loads((ROOT / "adapters" / f"{n}.json").read_text())
        for op, tpl in ad["commands"].items():
            for t in tpl.values() if isinstance(tpl, dict) else [tpl]:
                cmd = bt.render(t, vals)
                assert subprocess.run(["sh", "-n", "-c", cmd]).returncode == 0, (n, op, cmd)


def test_missing_hierarchy_defer_and_ready_filter_are_labels_and_the_list(toy):
    tr = tracker_of(toy, capabilities={"hierarchy": False})
    tr.ad["labels"] = {"parent": "bh-parent:", "deferred": "bh-deferred"}
    goal = tr.create("g", "", "goal")
    a = tr.create("a", "", "item", goal)
    assert "bh-parent:" + goal in tr.show(a)["labels"] and tr.show(a)["parent"] == goal
    assert tr.caps["ready_filter"] is False  # ready is computed: open, leaf, no open dep
    b = tr.create("b", "", "item", goal, [("blocks", a)])
    d = tr.create("d", "", "item", goal)
    tr.defer_entry(d, "r")
    assert [e["ref"] for e in tr.ready(parent=goal)["entries"]] == [a]
    assert goal not in [e["ref"] for e in tr.ready()["entries"]]  # a goal is not an item
    tr.close_entry(a, "x")
    assert [e["ref"] for e in tr.ready(parent=goal)["entries"]] == [b]


# ---------------------------------------------------------------- M7: claim without an atomic claim


def test_claim_race_between_two_clones_has_exactly_one_winner(toy, tmp_path):
    origin = with_origin(toy, tmp_path)
    other = clone(origin, tmp_path / "other")
    shutil.copytree(toy / ".brick-harness", other / ".brick-harness", dirs_exist_ok=True)
    a, b = cfg_of(toy), bhcore.Config(other / ".brick-harness" / "config.json")
    wins = 0
    for i in range(6):
        ra = bt.git_claim(a, f"item-{i}", "w-1", "actor-a")
        rb = bt.git_claim(b, f"item-{i}", "w-1", "actor-b")
        wins += ra["claimed"] + rb["claimed"]
        assert ra["claimed"] != rb["claimed"] and rb["holder"] == "actor-a"
    assert wins == 6
    # the claim ref is a commit of its own, a child of the remote's main, naming item and actor
    msg = git(origin, "log", "-1", "--format=%B", "refs/heads/bh/item-0")
    assert bt.parse_claim(msg + "\n") == {"item": "item-0", "ref": "w-1", "actor": "actor-a"}
    assert git(origin, "rev-parse", "refs/heads/bh/item-0^") == git(origin, "rev-parse", "main")


def test_a_reclaim_by_the_holder_is_a_noop_and_a_ref_survives_a_reopen(toy, tmp_path):
    with_origin(toy, tmp_path)
    cfg = cfg_of(toy)
    first = bt.git_claim(cfg, "i1", "w-1", "me")
    again = bt.git_claim(cfg, "i1", "w-1", "me")
    assert first["claimed"] and again == {"claimed": True, "holder": "me", "by": "git"}
    assert bt.claim_refs(cfg)["i1"]["sha"] == first["sha"]


def test_a_claim_without_an_origin_is_local_under_the_lock(toy):
    assert bt.git_claim(cfg_of(toy), "i1", "w-1", "me") == {
        "claimed": True,
        "holder": "me",
        "by": "local",
    }
    assert bt.claim_refs(cfg_of(toy)) == {}


def test_released_claims_are_only_ours_and_only_when_the_item_left_the_plan(toy, tmp_path):
    origin = with_origin(toy, tmp_path)
    cfg = cfg_of(toy)
    bt.git_claim(cfg, "gone", "w-1", "me")
    bt.git_claim(cfg, "kept", "w-2", "me")
    bt.git_claim(cfg, "theirs", "w-3", "them")
    out = bt.release_claims(cfg, "me", {"kept"}, set(), 30)
    assert out == [{"item": "gone", "ref": "w-1"}]
    assert git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/bh/").split() == [
        "refs/heads/bh/kept",
        "refs/heads/bh/theirs",
    ]


# ---------------------------------------------------------------- M9: admission


def admit_setup(toy, tmp_path, n=3, horizon=None):
    origin = with_origin(toy, tmp_path)
    cfg_edit(toy, horizon={"items": horizon} if horizon else {"items": 5}, tracker={"actor": "me"})
    tr = bt.Tracker(cfg_of(toy))
    goal = tr.create("goal", "", "goal")
    cfg_edit(toy, tracker={"actor": "me", "goal": goal})
    return origin, goal, seed(bt.Tracker(cfg_of(toy)), n, goal)


def test_admission_takes_ready_leaves_in_order_up_to_the_room_and_claims_first(toy, tmp_path):
    origin, goal, refs = admit_setup(toy, tmp_path, n=4)  # toy has 3 items not met: room is 2
    dry = cli("bh-admit", toy)[1]
    assert (
        dry["room"] == 2 and [a["ref"] for a in dry["admit"]] == refs[:2] and dry["admitted"] == []
    )
    assert dry["not_admitted"] == 2 and dry["tracker"] == "files"
    assert git(origin, "for-each-ref", "refs/heads/bh/") == ""  # nothing claimed without --write
    out = cli("bh-admit", toy, "--write")[1]
    assert out["admitted"] == [a["id"] for a in dry["admit"]]
    items = json.loads((toy / ".brick-harness/bricks.json").read_text())["bricks"]
    new = [b for b in items if b.get("refs")]
    assert [b["refs"] for b in new] == [[r] for r in refs[:2]] and all(
        b["kind"] == "change" for b in new
    )
    assert new[0]["id"] == bt.item_id(bt.load_adapter(cfg_of(toy)), refs[0])
    assert len(git(origin, "for-each-ref", "refs/heads/bh/").splitlines()) == 2
    # a repeat takes nothing more: the room is used and the ids exist
    again = cli("bh-admit", toy, "--write")[1]
    assert again["admitted"] == [] and again["room"] == 0 and again["stalled"]["horizon"] == 5


def test_a_readmission_after_a_crash_between_claim_and_write_adopts_the_claimed_entry(
    toy, tmp_path
):
    origin, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    cfg = cfg_of(toy)
    assert bt.git_claim(cfg, bt.item_id(bt.load_adapter(cfg), refs[0]), refs[0], "me")["claimed"]
    out = cli("bh-admit", toy, "--write")[1]
    assert set(out["admitted"]) == {bt.item_id(bt.load_adapter(cfg), r) for r in refs}
    assert out["released"] == []


def test_a_claim_held_elsewhere_is_a_fact_and_the_entry_is_not_admitted(toy, tmp_path):
    origin, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    cfg = cfg_of(toy)
    bt.git_claim(cfg, bt.item_id(bt.load_adapter(cfg), refs[0]), refs[0], "someone-else")
    out = cli("bh-admit", toy, "--write")[1]
    assert [bt.item_id(bt.load_adapter(cfg), refs[1])] == out["admitted"]
    assert out["not_admitted"] == 0  # a claimed entry is not ready, so it is not even a candidate


def test_admission_order_is_one_call_ranking_queued_items_first_then_the_trackers_order(toy):
    cfg = cfg_of(toy)
    ad = bt.load_adapter(cfg)
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


def test_an_unreachable_tracker_admits_nothing_and_says_so(toy):
    cfg_edit(toy, tracker={"adapter": "files", "commands": {"list": "false"}})
    out = cli("bh-admit", toy, "--write")[1]
    assert out["admitted"] == [] and "exited" in out["unreachable"]


def test_a_stalled_horizon_lists_the_gaps_that_block_items(toy, tmp_path):
    admit_setup(toy, tmp_path, n=1, horizon=1)
    out = cli("bh-admit", toy)[1]
    assert out["room"] == 0 and out["stalled"]["horizon"] == 1 and "blocked" in out["stalled"]


# ---------------------------------------------------------------- M8: reconciliation


def admitted(toy, tmp_path):
    origin, goal, refs = admit_setup(toy, tmp_path, n=2, horizon=10)
    cli("bh-admit", toy, "--write")
    plan_edit(
        toy,
        "targets.json",
        lambda d: d["targets"].extend(
            default_targets(bt.item_id(bt.load_adapter(cfg_of(toy)), refs[0]))
        ),
    )
    commit_all(toy, "admitted", ".brick-harness")
    return refs


def test_reconcile_lists_and_fixes_mismatches_and_touches_only_admitted_entries(
    toy, tmp_path, monkeypatch
):
    refs = admitted(toy, tmp_path)
    tr = bt.Tracker(cfg_of(toy))
    stray = tr.create("not ours", "", "item")
    tr.close_entry(refs[1], "a person closed it")  # item not met: a mismatch
    out = cli("bh-reconcile", toy)[1]
    assert out["mismatches"] == [
        {"kind": "tracker-closed-unmet", "item": bt.item_id(tr.ad, refs[1]), "ref": refs[1]}
    ]
    assert (
        out["reopened"] == [] and tr.show(refs[1])["state"] == "closed"
    )  # listing changes nothing
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["reopened"] == [refs[1]] and out["closed"] == []
    assert tr.show(refs[1])["state"] == "open" and tr.show(stray)["state"] == "open"
    again = cli("bh-reconcile", toy, "--write")[1]
    assert again["mismatches"] == [] and again["reopened"] == [] and again["closed"] == []
    assert out["checked"] == 2


def test_reconcile_closes_an_entry_only_when_its_item_is_measured_met(toy):
    from test_work_tracking import measure_and_commit

    tr = bt.Tracker(cfg_of(toy))
    ref = tr.create("read csv", "", "item")
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(refs=[ref]))
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["closed"] == [] and tr.show(ref)["state"] == "open"  # not measured: nothing closes
    measure_and_commit(toy, "csv-reader")  # the measurer, at HEAD, says met
    assert cli("bh-reconcile", toy)[1]["mismatches"][0]["kind"] == "tracker-open-met"
    assert tr.show(ref)["state"] == "open"
    out = cli("bh-reconcile", toy, "--write")[1]
    assert out["closed"] == [ref] and tr.show(ref)["state"] == "closed"
    note = json.loads((toy / ".brick-harness/work" / f"{ref}.json").read_text())["notes"][0]
    assert re.fullmatch(r"measured met at [0-9a-f]{12}, targets [0-9a-f]{12}", note)
    again = cli("bh-reconcile", toy, "--write")[1]
    assert again["closed"] == [] and again["mismatches"] == []


def test_a_missing_ref_is_a_fact_and_nothing_is_deleted(toy, tmp_path):
    refs = admitted(toy, tmp_path)
    (toy / ".brick-harness/work" / f"{refs[1]}.json").unlink()
    out = cli("bh-reconcile", toy, "--write")[1]
    assert {
        "kind": "ref-missing",
        "item": bt.item_id(bt.load_adapter(cfg_of(toy)), refs[1]),
        "ref": refs[1],
    } in out["facts"]
    assert (toy / ".brick-harness/work" / f"{refs[0]}.json").exists()


def test_the_gaps_report_lists_tracker_mismatches_as_facts_and_changes_no_status(toy, tmp_path):
    refs = admitted(toy, tmp_path)
    bt.Tracker(cfg_of(toy)).close_entry(refs[1], "closed by hand")
    _, before = cli("bh-state", toy, "--part", "decision")
    _, rep = cli("bh-gaps", toy)
    assert any(f["kind"] == "tracker-closed-unmet" and f["ref"] == refs[1] for f in rep["facts"])
    _, after = cli("bh-state", toy, "--part", "decision")
    assert before["decision"]["counts"] == after["decision"]["counts"]


# ---------------------------------------------------------------- M10: filing findings


def findings(toy, n):
    fs = [
        {
            "id": f"f{i}",
            "summary": f"finding {i}",
            "severity": "S3",
            "evidence": "theoretical",
            "impact": [],
            "where": "features.md:1",
        }
        for i in range(n)
    ]
    fs[1]["severity"] = "S1"
    cli("bh-rank", toy, "--add", "-", "--write") if False else None
    p = toy / "f.json"
    p.write_text(json.dumps(fs))
    code, out = cli("bh-rank", toy, "--add", str(p), "--write")
    assert code == 0, out
    commit_all(toy, "findings", ".brick-harness")


def test_bh_file_files_by_rank_looks_the_key_up_first_and_records_the_ref(toy):
    findings(toy, 3)
    dry = cli("bh-file", toy)[1]
    assert [f["id"] for f in dry["filed"]][0] == "f1" and all(
        f["ref"] is None for f in dry["filed"]
    )
    out = cli("bh-file", toy, "--write")[1]
    assert out["unfiled"] == 0 and len(out["filed"]) == 3 and out["filed"][0]["id"] == "f1"
    gaps = json.loads((toy / ".brick-harness/gaps.json").read_text())["gaps"]
    assert all(g["filed"].startswith("w-") for g in gaps if g.get("source") == "finding")
    tr = bt.Tracker(cfg_of(toy))
    e = tr.show(out["filed"][0]["ref"])
    assert e["metadata"]["bh_key"] == out["filed"][0]["key"] and e["title"].startswith("[S1]")
    commit_all(toy, "filed", ".brick-harness")
    again = cli("bh-file", toy, "--write")[1]
    assert again["filed"] == [] and len(tr.list(state="all")["entries"]) == 3


def test_a_finding_whose_key_is_already_in_the_tracker_is_adopted_not_created(toy):
    findings(toy, 2)
    g = json.loads((toy / ".brick-harness/gaps.json").read_text())["gaps"][0]
    tr = bt.Tracker(cfg_of(toy))
    ref = tr.create("earlier", "", "item", None, [], [], {"bh_key": bt.finding_key(g)})
    out = cli("bh-file", toy, "--write")[1]
    assert (
        any(f["adopted"] and f["ref"] == ref for f in out["filed"])
        and len(tr.list(state="all")["entries"]) == 2
    )


def test_bh_file_files_at_most_file_per_run_and_leaves_the_rest_ranked(toy):
    findings(toy, 3)
    cfg_edit(toy, limits={"file_per_run": 2})
    out = cli("bh-file", toy, "--write")[1]
    assert len(out["filed"]) == 2 and out["unfiled"] == 1
    rest = [
        g
        for g in json.loads((toy / ".brick-harness/gaps.json").read_text())["gaps"]
        if not g.get("filed")
    ]
    assert len(rest) == 1


def test_a_key_found_twice_is_duplicate_filed_and_a_tracker_error_stops_the_run(toy):
    findings(toy, 2)
    g = json.loads((toy / ".brick-harness/gaps.json").read_text())["gaps"][0]
    tr = bt.Tracker(cfg_of(toy))
    meta = {"bh_key": bt.finding_key(g)}
    tr.create("one", "", "item", None, [], [], meta)
    tr.create("two", "", "item", None, [], [], meta)
    out = cli("bh-file", toy, "--write")[1]
    assert out["duplicate_filed"] and out["duplicate_filed"][0]["key"] == meta["bh_key"]


def test_a_tracker_error_stops_filing_and_leaves_the_findings_ranked(toy):
    findings(toy, 2)
    cfg_edit(toy, tracker={"commands": {"create": "false"}})
    out = cli("bh-file", toy, "--write")[1]
    assert out["stopped"] and out["unfiled"] == 2 and out["filed"] == []


# ---------------------------------------------------------------- M11 and M12


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
