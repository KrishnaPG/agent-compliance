"""Every bh command prints its result JSON as the last stdout line (fields.yaml `result`), made of
the decided fields only; the summary text comes first and the whole run document stays in its file."""

import json
import subprocess
import sys

import yaml
from test_bhorch import BH, fake  # noqa: F401
from test_toy import ROOT, toy  # noqa: F401

FIELDS = yaml.safe_load((ROOT.parent / "docs" / "atdd" / "fields.yaml").read_text())["fields"]


def decided(schema):
    return {f["path"].split("[")[0].split(".")[0] for f in FIELDS if f["schema"] == schema}


def test_bh_run_prints_the_result_json_last_with_decided_fields_only(toy, fake):  # noqa: F811
    p = subprocess.run(
        [sys.executable, str(BH), "run", "--skip", "harvest", "--config", str(toy / ".brick-harness" / "config.json")],
        capture_output=True,
        text=True,
        cwd=toy,
    )
    assert p.stdout.startswith("PRODUCT"), p.stderr
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert res["schema_version"] and res["command"] == "run"
    assert set(res) <= decided("result") | {"jobs"}
    assert {k for j in res["jobs"] for k in j} <= {f["path"].removeprefix("jobs[*].").split("[")[0] for f in FIELDS if f["schema"] == "jobs"}
    assert [j.get("role") for j in res["jobs"]][:1] == [None] and "phases" in json.loads((toy / ".brick-harness" / "out" / "run-result.json").read_text())
