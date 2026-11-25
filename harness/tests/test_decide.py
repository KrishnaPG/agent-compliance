"""bh decide (R9, P6, QBC-69): the options of a decision record are judged by one fresh `claude -p` job that never sees the proposer's pick."""

import json
import shutil
import subprocess
from pathlib import Path

import bhcore
import bhorch

STUB = Path(__file__).resolve().parent.parent / "acceptance" / "keywords" / "stub_claude.py"
RECORD = """# Store session state

## Context and Problem Statement
Sessions live in a table the service owns (src/session.py:12).

## Decision Drivers
* T1: restart keeps sessions

## Considered Options
* O1 keep the table
* O2 the cluster's key-value store

## Decision Outcome
Chosen option: "O2", because the proposer likes it.

### Consequences
* Good, because the proposer says so.

## Pros and Cons of the Options

### O1 keep the table
* Good, because nothing new runs.
"""
JUDGED = {
    "options": [
        {"id": "O1", "targets": ["T1"], "rules": [{"id": "H-01", "verdict": "pass"}]},
        {"id": "O2", "targets": [], "rules": [{"id": "H-01", "verdict": "unknown"}]},
    ],
    "recommended": "O1",
    "objections": ["O2 adds a service the project must run -> keep the table; src/session.py:12"],
    "falsifying_calls": ["restart the service; GET /session/1 answers 404"],
}


def test_a_fresh_judge_scores_the_options_without_the_proposers_pick(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "proj"
    (proj / "docs" / "decisions").mkdir(parents=True)
    rec = proj / "docs" / "decisions" / "0001-session-state.md"
    rec.write_text(RECORD)
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shutil.copy(STUB, bin_dir / "claude")
    (bin_dir / "claude").chmod(0o755)
    fx = tmp_path / "model.json"
    reply = {"type": "result", "subtype": "success", "is_error": False, "structured_output": JUDGED, "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01}
    fx.write_text(json.dumps({"replies": [{"stdout": json.dumps(reply)}]}))
    log = tmp_path / "launches.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(shutil.which('git')).parent}")
    monkeypatch.setenv("ATDD_MODEL_FIXTURE", str(fx))
    monkeypatch.setenv("ATDD_MODEL_LOG", str(log))
    monkeypatch.chdir(proj)

    code = bhorch.main(["decide", str(rec)])
    res = json.loads(capsys.readouterr().out)

    assert code == 0, res
    launches = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(launches) == 1  # one separate job, the judge
    argv = launches[0]["argv"]
    assert "-p" in argv and "--no-session-persistence" in argv
    assert not {"--resume", "-r", "--continue", "-c", "--session-id"} & set(argv)  # never the proposer's session
    inp = next(ln.split(": ", 1)[1] for ln in launches[0]["stdin"].splitlines() if ln.startswith("Input file"))
    seen = Path(json.loads(Path(inp).read_text())["record"]).read_text()
    assert "Considered Options" in seen
    assert "Decision Outcome" not in seen and "proposer" not in seen  # the pick never reaches the judge
    assert "## Pros and Cons of the Options" in seen and "nothing new runs" in seen  # MADR's later sections stay
    assert "O2" not in launches[0]["stdin"]
    assert res["command"] == "decide"
    assert not bhcore.schema_errors(res, bhcore.load_schema("result"))
    assert res["recommended"] == "O1" and [o["id"] for o in res["options"]] == ["O1", "O2"]
    (job,) = res["jobs"]
    assert job["role"] == "judge" and job["kind"] == "agent"
    assert job["objections"] == JUDGED["objections"] and job["falsifying_calls"] == JUDGED["falsifying_calls"]
