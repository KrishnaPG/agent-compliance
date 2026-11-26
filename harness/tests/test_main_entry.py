"""Main's entry check (QBC-118, QBC-119; owner decision 2026-11-26): a change enters the protected
default branch only when its tests pass and its review leaves no open S1 or S2 finding; S3 and S4
are annotations; an owner override is recorded. The builder's merge, ``bh land`` and the GitHub
ruleset with its required ``bh-review`` check all apply it (G2). Each case has its negative control."""

import json
import subprocess
import sys

import bhorch
import bhpacket
import bhreview
from bhcore import Config
from ruamel.yaml import YAML
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_human_path import _built
from test_review_rules import MAJOR, NETWORK, plan
from test_review_step import STRICT, spec_for
from test_toy import JSON_WRITER, commit_all, git

MINOR = {"summary": "the writer repeats a helper the reader has -> call the reader's helper", "rule": "duplication", "severity": "S3", "evidence": "trigger", "where": "src/json_writer.py:1"}


def _merged(toy, item):
    return any(m.startswith(f"brick-harness: merge {item}") for m in git(toy, "log", "--format=%s", "main").splitlines())


def _defects(toy):
    return [b for b in json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"] if b.get("kind") == "defect"]


def _facts(res, kind):
    return [f for r in res["phases"]["rounds"] for f in r["facts"] if f["kind"] == kind]


# ---------------------------------------------------------------- the builder path (QBC-118)


def test_qbc_118_an_open_s2_after_its_rounds_is_met_but_not_merged_and_its_slice_stays_open(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[MAJOR]], [JSON_WRITER, JSON_WRITER + "\n# second round\n"])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"  # findings never change met
    jw = [j.get("job") for j in res["jobs"] if j.get("item") == "json-writer" and j.get("job") == "review"]
    assert len(jw) == 2  # one requested-changes round (limits.review_rounds 1), then the entry check
    assert not _merged(toy, "json-writer")
    (fact,) = _facts(res, "not_admitted")
    assert fact["message"].startswith("[main-entry] ") and " -> " in fact["message"] and "QBC-91" in fact["detail"]
    (d,) = _defects(toy)  # its rework: one defect item under it (QBC-36), built on the build that waits
    assert d["parent"] == "json-writer" and d["found_by"] == "reviewer" and d["breaks"] == ["ID-15"]
    (wait,) = _facts(res, "awaiting_entry")
    assert wait["detail"] == f"awaiting entry: 1 open findings, defect {d['id']} queued"
    assert not _facts(res, "stuck")
    gaps = json.loads(o.cfg.file("gaps").read_text())["gaps"]
    assert [g["state"] for g in gaps if g.get("rule") == "ID-15" and g["evidence"][0]["file"] == "src/json_writer.py"] == ["open"]  # open, on the slice's code
    at_head = {b["id"]: b["status"] for b in o.state()["bricks"]}
    assert at_head["json-writer"] != "met"  # not met at HEAD: reconcile reopens its tracker entry
    assert "bh land refs/bh/json-writer --override REASON" in fact["message"]
    # the merges that start no agent read the same recorded review (0 tokens): main stays as it was
    code, out, err = bhpacket.step("merge", toy, "json-writer")
    assert code == 1 and err.startswith("[main-entry] ") and json.loads(out)["merged"] == []
    m = run(o.phase_measure([{"ref": bhpacket.BUILD_REF.format(item="json-writer"), "items": ["json-writer"]}]))
    assert m["merged"] == [] and [u["item"] for u in m["not_admitted"]] == ["json-writer"]
    assert not _merged(toy, "json-writer") and not (toy / "src" / "json_writer.py").exists()  # only a scoreboard commit


FIXED = JSON_WRITER + "\n# the verified principal is taken as a value\n"


def test_qbc_118_a_second_run_queues_the_defect_fix_and_the_parent_enters_main_with_it(toy, fake):  # noqa: F811
    """Not admitted is not stuck: the second run reports the parent awaiting entry, the Kanban queue
    pulls its defect item (the reviewer's regression row, the builder's fix on the waiting build,
    the measurer), and the fix's admission to main brings the parent in, met at HEAD."""
    plan(toy)
    spec_for(fake, [[MAJOR]], [JSON_WRITER, JSON_WRITER + "\n# second round\n"])
    run(orch(toy).run())
    (d,) = _defects(toy)
    did = d["id"].replace("-", "_")
    c = toy / ".brick-harness" / "config.json"  # the toy's test entry names a folder per item; a defect has none
    c.write_text(c.read_text().replace(" tests/{item} --junitxml", " $(ls -d tests/{item} 2>/dev/null) --junitxml"))
    commit_all(toy, "test entry: an item without its own folder")
    row = {
        "acceptance": [{"id": f"{d['id']}-AC1", "scenario": "the verified principal is a value", "traces_to": ["QBC-36"], "verification": "test"}],
        "test_code": f"from pathlib import Path\n\n\ndef test_{did}_AC1_fixed():\n    \"\"\"{d['id']}-AC1\"\"\"\n"
        "    assert 'verified principal' in (Path(__file__).resolve().parents[2] / 'src' / 'json_writer.py').read_text()\n",
    }
    first = [JSON_WRITER, JSON_WRITER + "\n# second round\n"]  # the calls so far, in the fake's one log
    fake.spec(
        outputs_by_item={"harness-test-author": STRICT},
        outputs_seq={"harness-reviewer": [{"findings": [MAJOR]}, {"findings": [MAJOR]}, row, row, {"findings": []}]},
        files_seq={"harness-builder": [{"src/json_writer.py": b} for b in [*first, FIXED]]},
    )
    o = orch(toy)
    res = run(o.run())
    rounds = {r["item"]: r for r in res["phases"]["rounds"]}
    assert rounds["json-writer"]["status"] == "met" and not _facts(res, "stuck")
    assert any(f["kind"] == "awaiting_entry" for f in rounds["json-writer"]["facts"])
    jobs = [j.get("job") or j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == d["id"]]
    assert jobs[:4] == ["regression_row", "red_run", "builder", "measurer"], jobs
    assert rounds[d["id"]]["status"] == "met" and _merged(toy, d["id"])
    assert (toy / "src" / "json_writer.py").read_text() == FIXED  # the parent's build and its fix, on main
    at_head = {b["id"]: b["status"] for b in o.state()["bricks"]}
    assert at_head["json-writer"] == "met" and at_head[d["id"]] == "met"


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
    (plugin,) = [s["with"] for s in flow["jobs"]["bh-review"]["steps"] if s.get("with", {}).get("path") == ".bh-plugin"]
    root = bhreview.PLUGIN_ROOT
    tag = subprocess.run(["git", "describe", "--exact-match", "--tags", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert plugin["ref"] == (tag or git(root, "rev-parse", "HEAD").strip())  # the writing plugin's own version
    monkeypatch.setattr(bhreview, "plugin_ref", lambda: "v9.9.9")  # the plugin was updated
    assert bhreview.install_entry(repo, False)["written"] == [".github/workflows/bh-review.yml"]  # re-pinned, no question
    assert "ref: v9.9.9\n" in wf.read_text() and bhreview.install_entry(repo, False)["written"] == []
    # negative controls: an unknown rule type and a job without runs-on fail their schemas
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**ruleset, "rules": [{"type": "required_review_by_magic"}]}))
    assert _check_jsonschema("--schemafile", schema, str(bad)).returncode == 1
    badwf = tmp_path / "bad.yml"
    badwf.write_text(wf.read_text().replace("    runs-on: ubuntu-latest\n", ""))
    assert _check_jsonschema("--builtin-schema", "vendor.github-workflows", str(badwf)).returncode == 1
    wf.write_text("# the project's own\n")
    assert bhreview.install_entry(repo, True)["written"] == [] and wf.read_text() == "# the project's own\n"  # never over a project's file
