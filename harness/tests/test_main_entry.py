"""Main's entry check (QBC-118, QBC-119; owner decision 2026-11-26): a change enters the protected
default branch only when its tests pass and its review leaves no open S1 or S2 finding; S3 and S4
are annotations; an owner override is recorded. The builder's merge, ``bh land`` and the GitHub
ruleset with its required ``bh-review`` check all apply it (G2). Each case has its negative control."""

import json
import subprocess
import sys

import bhorch
import bhreview
from bhcore import Config
from ruamel.yaml import YAML
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_human_path import _built
from test_review_rules import MAJOR, NETWORK, plan, reviews
from test_review_step import spec_for
from test_toy import JSON_WRITER, commit_all, git

MINOR = {"summary": "the writer repeats a helper the reader has -> call the reader's helper", "rule": "duplication", "severity": "S3", "evidence": "trigger", "where": "src/json_writer.py:1"}


def _merged(toy, item):
    return any(m.startswith(f"brick-harness: merge {item}") for m in git(toy, "log", "--format=%s", "main").splitlines())


def _facts(res, kind):
    return [f for r in res["phases"]["rounds"] for f in r["facts"] if f["kind"] == kind]


# ---------------------------------------------------------------- the builder path (QBC-118)


def test_qbc_118_an_open_s2_after_its_rounds_is_met_but_not_merged_and_its_slice_stays_open(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[MAJOR]], [JSON_WRITER, JSON_WRITER + "\n# second round\n"])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"  # findings never change met
    assert len(reviews(fake)) == 2  # one requested-changes round (limits.review_rounds 1), then the entry check
    assert not _merged(toy, "json-writer")
    (fact,) = _facts(res, "not_admitted")
    assert fact["message"].startswith("[main-entry] ") and " -> " in fact["message"] and "QBC-91" in fact["detail"]
    items = json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"]
    assert not [b for b in items if b.get("kind") == "defect"]  # QBC-91: no defect filed after the fact
    gaps = json.loads(o.cfg.file("gaps").read_text())["gaps"]
    assert any("ID-15" in json.dumps(g) for g in gaps)  # the finding is recorded on the slice
    at_head = {b["id"]: b["status"] for b in o.state()["bricks"]}
    assert at_head["json-writer"] != "met"  # not met at HEAD: reconcile reopens its tracker entry


def test_qbc_118_the_same_item_with_only_an_s3_finding_is_merged(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[MINOR]], [JSON_WRITER])
    res = run(orch(toy).run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    assert _merged(toy, "json-writer") and not _facts(res, "not_admitted")
    assert any("[duplication]" in f["detail"] for f in _facts(res, "known_issue"))  # an annotation only


def test_qbc_118_admission_is_one_function_of_the_review_log():
    s2, s3 = (bhreview.sarif([f], "x", "0" * 64, 300) for f in (MAJOR, MINOR))
    assert not bhreview.admission(s2)["admitted"] and bhreview.admission(s3)["admitted"]
    assert bhreview.admission(s2, "release blocker accepted by the owner")["override"]
    assert bhreview.admission(None)["admitted"]  # no trigger: no review, 0 tokens
    unfinished = bhreview.sarif([], "x", "0" * 64, 300)
    unfinished["runs"][0]["invocations"] = [{"executionSuccessful": False}]
    assert not bhreview.admission(unfinished)["admitted"]  # main never admits an unjudged change


# ---------------------------------------------------------------- the human path: bh land (QBC-119)


def _human_branch(toy, fake, name="human", path="src/json_writer.py", text=NETWORK):  # noqa: F811
    """The toy built and merged, then a person's branch that adds a network call: its tip."""
    _built(toy, fake)
    git(toy, "checkout", "-q", "-b", name, "main")
    (toy / path).write_text(text)
    sha = commit_all(toy, f"feat: {name}").strip()
    git(toy, "checkout", "-q", "main")
    return sha


def _land(capsys, toy, *argv):
    capsys.readouterr()
    code = bhorch.main(["land", *argv, "--config", str(toy / ".brick-harness" / "config.json")])
    out = capsys.readouterr().out
    return code, json.loads(out.strip().splitlines()[-1]), out


def test_qbc_119_bh_land_refuses_a_branch_with_an_s2_and_admits_it_with_a_recorded_override(toy, fake, capsys):  # noqa: F811
    sha = _human_branch(toy, fake)
    main = git(toy, "rev-parse", "main").strip()
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [MAJOR]}]})
    code, doc, out = _land(capsys, toy, "human")
    assert code == 1 and git(toy, "rev-parse", "main").strip() == main  # not admitted, nothing merged
    (fact,) = [f for f in doc["facts"] if f["kind"] == "not_admitted"]
    assert fact["message"].startswith("[main-entry] human has 1 open S1/S2") and "[ID-15]" in fact["detail"]
    assert "LAND human -> main: not admitted" in out
    code, doc, out = _land(capsys, toy, "human", "--override", "a hotfix the owner accepts")
    assert code == 0, out
    (fact,) = [f for f in doc["facts"] if f["kind"] == "override"]
    assert "a hotfix the owner accepts" in fact["detail"]
    assert git(toy, "rev-parse", "main^2").strip() == sha  # merged into main
    assert git(toy, "log", "-1", "--format=%(trailers:key=Bh-Override,valueonly)", "main").strip() == "a hotfix the owner accepts"


def test_qbc_119_bh_land_admits_a_branch_with_only_an_s3_and_refuses_failing_tests(toy, fake, capsys):  # noqa: F811
    _human_branch(toy, fake)
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [MINOR]}]})
    code, doc, out = _land(capsys, toy, "human", "--check")
    assert code == 0 and not [f for f in doc["facts"] if f["kind"] in ("not_admitted", "override")], out
    git(toy, "checkout", "-q", "-b", "broken", "main")
    t = next((toy / "tests").rglob("test_*.py"))
    t.write_text(t.read_text() + "\n\ndef test_broken():\n    assert False, 'a human broke it'\n")
    commit_all(toy, "test: a failing test", "tests")
    git(toy, "checkout", "-q", "main")
    code, doc, _ = _land(capsys, toy, "broken", "--check")
    (fact,) = [f for f in doc["facts"] if f["kind"] == "not_admitted"]
    assert code == 1 and "the tests fail on broken merged into main" in fact["detail"]


# ---------------------------------------------------------------- GitHub's standard files (QBC-119)


def _check_jsonschema(*argv):
    return subprocess.run([sys.executable, "-m", "check_jsonschema", *argv], capture_output=True, text=True)


def test_qbc_119_the_ruleset_and_workflow_validate_and_name_one_check(tmp_path, monkeypatch):
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("app\n")
    commit_all(repo, "app")
    assert bhreview.install_entry(repo, False) == {"written": [], "pending": []}  # no GitHub: bh land is the path (P12)
    git(repo, "remote", "add", "origin", "https://github.com/example/app.git")
    assert bhreview.install_entry(repo, False)["pending"] == [".github/workflows/bh-review.yml", ".github/rulesets/bh-main.json"]
    asked = bhorch.Orchestrator(Config(repo / ".brick-harness" / "config.json")).phase_setup()["questions"]
    (setup,) = [q for q in asked if q["id"] == "Q-setup"]
    assert "main (.github/workflows/bh-review.yml" in setup["summary"]  # folded into the one setup question
    owner = {"actor_id": 7, "actor_type": "User", "bypass_mode": "pull_request"}
    monkeypatch.setattr(bhreview, "repo_owner", lambda slug: owner if slug == "example/app" else None)
    out = bhreview.install_entry(repo, True)
    assert out["apply"] == "gh api -X POST repos/example/app/rulesets --input .github/rulesets/bh-main.json"
    wf, rs = repo / ".github" / "workflows" / "bh-review.yml", repo / ".github" / "rulesets" / "bh-main.json"
    schema = str(bhreview.SCHEMA_DIR / "github-ruleset.schema.json")
    assert _check_jsonschema("--builtin-schema", "vendor.github-workflows", str(wf)).returncode == 0
    assert _check_jsonschema("--schemafile", schema, str(rs)).returncode == 0
    ruleset, flow = json.loads(rs.read_text()), YAML(typ="safe").load(wf.read_text())
    assert ruleset["bypass_actors"] == [owner] and ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    (checks,) = [r["parameters"]["required_status_checks"] for r in ruleset["rules"] if r["type"] == "required_status_checks"]
    assert [c["context"] for c in checks] == list(flow["jobs"]) == ["bh-review"]  # the check is the job GitHub reports
    assert flow["on"]["pull_request"]["branches"] == ["main"] and "pull_request" in [r["type"] for r in ruleset["rules"]]
    assert 'bh land "$HEAD" --onto "$BASE" --check' in wf.read_text()
    # negative controls: an unknown rule type and a job without runs-on fail their schemas
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**ruleset, "rules": [{"type": "required_review_by_magic"}]}))
    assert _check_jsonschema("--schemafile", schema, str(bad)).returncode == 1
    badwf = tmp_path / "bad.yml"
    badwf.write_text(wf.read_text().replace("    runs-on: ubuntu-latest\n", ""))
    assert _check_jsonschema("--builtin-schema", "vendor.github-workflows", str(badwf)).returncode == 1
    wf.write_text("# the project's own\n")
    assert bhreview.install_entry(repo, True)["written"] == [] and wf.read_text() == "# the project's own\n"  # never over a project's file
