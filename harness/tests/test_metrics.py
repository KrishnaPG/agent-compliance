"""bh metrics (R11): DORA measures from git, the issue history and jobs[*], on a recorded history; the baseline is written once."""

import json
import os
import subprocess

import bhcore
import bhorch
import jsonschema
from recorded_github import flow, replay

H = 3600
T0 = 1_700_000_000
URL = "https://api.github.com/repos/o/r"


def iso(t):
    return subprocess.run(["date", "-u", "-d", f"@{t}", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True).stdout.strip()


def issue(n, label, opened, parent=None):
    d = {"id": 1000 + n, "number": n, "labels": [{"name": label}], "created_at": iso(opened), "body": ""}
    if parent:
        d["parent_issue_url"] = f"{URL}/issues/{parent}"
    return d


def merge(proj, item, t):
    env = {**os.environ, "GIT_COMMITTER_DATE": f"{t} +0000", "GIT_AUTHOR_DATE": f"{t} +0000"}
    subprocess.run(["git", "-C", str(proj), "commit", "-q", "--allow-empty", "-m", f"brick-harness: merge {item} abcdef123456"], env=env, check=True)


def test_metrics_from_a_recorded_history_with_a_baseline_written_once(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "proj"
    (proj / ".brick-harness" / "out").mkdir(parents=True)
    cfgfile = proj / ".brick-harness" / "config.json"
    cfgfile.write_text(json.dumps({"tracker": {"adapter": "github", "repo": "o/r"}}))
    for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(proj), *c], check=True)
    merge(proj, "gh-1", T0 + 10 * H)
    merge(proj, "gh-2", T0 + 30 * H)
    jobs = proj / ".brick-harness" / "out" / "jobs"  # the order engine's state: one kept record per finished job
    jobs.mkdir(parents=True)
    for rec in (
        {"id": "a1", "item": "gh-1", "role": "builder", "tokens": 50, "round": 1},
        {"id": "a2", "item": "gh-1", "role": "builder", "tokens": 40, "round": 2},  # two rounds: rounds is the highest
        {"id": "b", "item": "gh-2", "role": "builder", "tokens": {"input": 250, "output": 50}, "round": 1},
        {"id": "c", "item": "gh-3", "role": "builder", "tokens": 500, "round": 3},
    ):
        (jobs / f"{rec['id']}.json").write_text(json.dumps({"record": rec, "output": None}))
    (jobs / "b.input.json").write_text(json.dumps({"item": "gh-2", "tokens": 900}))  # a job's input is no record
    (jobs / "e.error.json").write_text(json.dumps({"id": "e", "item": "gh-1", "tokens": 10}))  # a failed job's record counts too
    history = [
        issue(1, "slice", T0, 10), issue(2, "slice", T0, 10), issue(3, "slice", T0 + 40 * H, 10),
        issue(9, "defect", T0 + 12 * H, 1),  # a defect under slice 1, after its merge
        issue(8, "defect", T0 + 5 * H, 2),  # opened before slice 2 merged: not a later failure
    ]
    q = "?per_page=100&state=all"
    ctx, stop = replay(tmp_path, monkeypatch, [flow("GET", "/issues" + q, history), flow("GET", "/issues" + q, history)])
    try:
        assert bhorch.main(["metrics", "--config", str(cfgfile)]) == 0
        first = json.loads(capsys.readouterr().out)
        jsonschema.validate(first, bhcore.load_schema("result"))
        base = {m["id"]: (m["value"], m["unit"], m["window"]) for m in first["metrics"]}
        assert base == {
            "change_failure_rate": (0.5, "ratio", "baseline"),
            "lead_time_for_changes": (20.0, "hours", "baseline"),
            "tokens_per_met_slice": (200.0, "tokens", "baseline"),
            "measurer_rounds": (3, "count", "baseline"),
        }
        stored = (proj / ".brick-harness" / "metrics-baseline.json").read_text()
        merge(proj, "gh-3", T0 + 45 * H)
        assert bhorch.main(["metrics", "--config", str(cfgfile)]) == 0
        second = json.loads(capsys.readouterr().out)
        jsonschema.validate(second, bhcore.load_schema("result"))
    finally:
        stop()
    assert (proj / ".brick-harness" / "metrics-baseline.json").read_text() == stored  # written once
    cur = {m["id"]: m["value"] for m in second["metrics"] if m["window"] == "current"}
    assert cur == {"change_failure_rate": 0.0, "lead_time_for_changes": 5.0, "tokens_per_met_slice": 500.0, "measurer_rounds": 3}
    assert [m for m in second["metrics"] if m["window"] == "baseline"] == first["metrics"]
