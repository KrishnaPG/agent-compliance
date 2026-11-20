"""Real Beads (SG-15 M5 to M9).

Runs only when `bd` is on PATH and is the pinned binary (its sha256 equals the adapter's pin);
any other binary is refused by the runner, which proves nothing here. Entries are created with
bd itself: the harness has no create operation.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import bhcore
import bhtracker as bt
import pytest
from test_toy import ENV, cli, commit_all, copy_toy, git

ROOT = Path(__file__).resolve().parent.parent
BD = shutil.which("bd")
PIN = json.loads((ROOT / "adapters" / "beads.json").read_text())["pin"]["sha256"].get(
    bt.platform_key()
)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


needs_bd = pytest.mark.skipif(
    not (BD and PIN and _sha(os.path.realpath(BD)) == PIN),
    reason="the pinned bd binary is not on PATH",
)


def bd(repo, *a, actor="bh-it"):
    p = subprocess.run(
        ["bd", *a, "--actor", actor], cwd=repo, capture_output=True, text=True, env=ENV
    )
    return p.returncode, p.stdout


def mk(repo, title, kind, parent=None, blocked_by=None):
    a = ["create", title, "-t", kind, "--json"]
    a += ["--parent", parent] if parent else []
    a += ["--deps", f"blocks:{blocked_by}"] if blocked_by else []
    code, out = bd(repo, *a)
    assert code == 0, out
    return json.loads(out)["id"]


@pytest.fixture
def proj(tmp_path):
    repo = tmp_path / "proj"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    p = subprocess.run(["bd", "init", "--quiet"], cwd=repo, capture_output=True, env=ENV)
    assert p.returncode == 0, p.stderr
    conf = repo / ".brick-harness" / "config.json"
    c = json.loads(conf.read_text())
    c["tracker"] = {"adapter": "beads", "actor": "bh-it"}
    c["horizon"] = {"items": 6}
    conf.write_text(json.dumps(c, indent=2))
    commit_all(repo, "config", ".brick-harness")
    return repo


def tracker(repo):
    tr = bt.Tracker(bhcore.Config(repo / ".brick-harness" / "config.json"))
    assert tr.name == "beads" and not tr.facts
    return tr


@needs_bd
def test_every_operation_against_real_beads(proj):
    tr = tracker(proj)
    goal = mk(proj, "Goal", "epic")
    feat = mk(proj, "Feature", "feature", goal)
    a = mk(proj, "Task a", "task", feat)
    b = mk(proj, "Task b", "task", feat, blocked_by=a)
    assert tr.show(goal)["type"] == "goal" and tr.show(feat)["type"] == "feature"
    e = tr.show(a)
    assert (e["type"], e["state"], e["parent"]) == ("item", "open", feat)
    assert tr.show(b)["deps"] == [a]
    ready = tr.ready(limit=5, parent=goal)
    assert [x["ref"] for x in ready["entries"]] == [a]  # b is blocked, a feature is not an item
    assert tr.claim(a) == {"claimed": True, "holder": tr.actor, "by": "tracker"}
    assert tr.claim(a)["claimed"] is True  # the same actor again: a no-op
    assert tr.show(a)["state"] == "in_progress" and tr.show(a)["assignee"] == tr.actor
    assert [x["ref"] for x in tr.list(type="item")["entries"] if x["assignee"]] == [a]
    other = bt.Tracker(tr.cfg)
    other.actor = "bh-someone-else"
    got = other.claim(a)
    assert got["claimed"] is False and got["holder"] == tr.actor
    assert other.facts[-1]["kind"] == "claimed-elsewhere"
    code, _ = bd(proj, "close", a, "--reason", "x", actor="bh-someone-else")
    assert code != 0  # Beads itself refuses a close by a non-holder; the harness never forces it
    tr.close_entry(a, "measured met", tr.show(a)["assignee"])
    assert tr.show(a)["state"] == "closed"
    tr.reopen_entry(a, "not met", tr.actor)
    assert tr.show(a)["state"] == "open"
    with pytest.raises(bt.TrackerError) as err:
        tr.show("nope-1")
    assert tr.missing(err.value)
    assert tr.list(limit=1)["more"] is True


@needs_bd
def test_admission_and_reconcile_through_real_beads(proj):
    from test_work_tracking import measure_and_commit

    tr = tracker(proj)
    goal = mk(proj, "Goal", "epic")
    refs = [mk(proj, f"Task {i}", "task", goal) for i in range(5)]
    conf = proj / ".brick-harness" / "config.json"
    c = json.loads(conf.read_text())
    c["tracker"]["goal"] = goal
    c["horizon"] = {"items": 5}  # the toy has 3 items not met: room for 2
    conf.write_text(json.dumps(c, indent=2))
    commit_all(proj, "goal", ".brick-harness")
    out = cli("bh-admit", proj, "--write")[1]
    assert out["room"] == 2 and out["tracker"] == "beads" and len(out["admitted"]) == 2
    taken = out["admit"]
    assert [a["ref"] for a in taken] == refs[:2]  # the tracker's own order
    assert all(tr.show(a["ref"])["assignee"] == tr.actor for a in taken)
    bricks = json.loads((proj / ".brick-harness/bricks.json").read_text())["bricks"]
    assert [b["refs"] for b in bricks if b.get("refs")] == [[r] for r in refs[:2]]
    again = cli("bh-admit", proj, "--write")[1]
    assert again["admitted"] == [] and again["room"] == 0
    commit_all(proj, "admitted", ".brick-harness")
    # an entry closed by hand while its item is unmet is reopened; a met item's entry is closed
    tr.close_entry(refs[0], "by hand", tr.actor)
    r = cli("bh-reconcile", proj, "--write")[1]
    assert r["reopened"] == [refs[0]] and tr.show(refs[0])["state"] == "open"
    ref = mk(proj, "csv", "task", goal)
    p = proj / ".brick-harness/bricks.json"
    d = json.loads(p.read_text())
    d["bricks"][0]["refs"] = [ref]
    p.write_text(json.dumps(d, indent=2))
    commit_all(proj, "map", ".brick-harness")
    measure_and_commit(proj, d["bricks"][0]["id"])
    assert tr.claim(ref)["claimed"]
    item = d["bricks"][0]["id"]
    got = cli("bh-state", proj, "--part", "bricks")[1]["bricks"]
    assert {b["id"]: b["status"] for b in got}[item] == "met", got
    r = cli("bh-reconcile", proj, "--write")[1]
    assert r["closed"] == [ref] and tr.show(ref)["state"] == "closed", r
    assert cli("bh-reconcile", proj, "--write")[1]["mismatches"] == []
