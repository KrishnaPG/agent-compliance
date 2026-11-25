"""bh vet (R9, P4, P12): deps.dev, OpenSSF Scorecard and OSV answers kept unchanged as api_results, printed as facts with no verdict word; replayed from recorded mitmproxy flows."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "acceptance" / "keywords"))
from given import given_recorded_api  # noqa: E402
from support import api_log  # noqa: E402

FIXTURES = HARNESS / "acceptance" / "fixtures"
VERDICT = re.compile(r"\b(BROKEN|HELD|PASS(ED)?|FAIL(ED)?|UNVERIFIED|OK)\b", re.I)


def vet(tmp_path, fixture, services, *args):
    work = tmp_path / "work"
    work.mkdir()
    ctx = SimpleNamespace(state={"env": {"PATH": os.environ["PATH"], "PYTHONPATH": str(HARNESS / "lib")}}, work=work, fixtures=FIXTURES, finalizers=[])
    for s in services:
        given_recorded_api(ctx, s, fixture)
    try:
        p = subprocess.run([sys.executable, "-c", "import sys, bhvet; sys.exit(bhvet.main(*sys.argv[1:]))", *args], env=ctx.state["env"], capture_output=True, text=True)
    finally:
        for f in ctx.finalizers:
            f()
    assert p.returncode == 0, p.stderr
    *lines, last = p.stdout.strip().splitlines()
    return lines, json.loads(last), api_log(ctx)


@pytest.mark.parametrize(
    ("fixture", "services", "args"),
    [("requests-2.32.3", ["deps_dev", "scorecard", "osv"], ["pypi", "requests", "2.32.3"]), ("unknown-package", ["deps_dev", "osv"], ["pypi", "no-such-package-r9-zz", "1.0.0"])],
)
def test_vet_keeps_each_answer_and_prints_facts_only(tmp_path, fixture, services, args):
    lines, res, log = vet(tmp_path, fixture, services, *args)
    schema = json.loads((HARNESS / "schema" / "result.schema.json").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(res))
    assert [r["id"] for r in res["api_results"]] == ["deps.dev", "scorecard", "osv"]
    assert all(e["operation"] != "unmatched" for e in log), log  # every call was a recorded one; none left the machine
    assert {e["service"] for e in log} == set(services)
    words = lines + [f["kind"] + " " + f["detail"] for f in res["facts"]]
    assert not [w for w in words if VERDICT.search(w)]  # facts, never a verdict (P4)


def test_vet_reads_the_recorded_bodies_unchanged(tmp_path):
    lines, res, _ = vet(tmp_path, "requests-2.32.3", ["deps_dev", "scorecard", "osv"], "pypi", "requests", "2.32.3")
    body = {r["id"]: r["body"] for r in res["api_results"]}
    assert body["deps.dev"]["versionKey"] == {"system": "PYPI", "name": "requests", "version": "2.32.3"}
    assert body["scorecard"]["repo"]["name"] == "github.com/psf/requests"
    assert f"scorecard.score: {body['scorecard']['score']} of 10 on {body['scorecard']['date']}" in lines
    assert any(ln.startswith(f"osv.vulns: {len(body['osv']['vulns'])}: ") for ln in lines)


def test_unknown_package_is_a_fact_not_a_crash(tmp_path):
    lines, res, _ = vet(tmp_path, "unknown-package", ["deps_dev", "osv"], "pypi", "no-such-package-r9-zz", "1.0.0")
    assert "deps.dev.error: HTTP 404 from api.deps.dev" in lines
    assert "scorecard.error: deps.dev names no source repository" in lines
