"""A human author's change gets what an agent's gets (section 0 G1, G2; QBC-16): measured after a
merge, a clean tree after setup, and a failure message that says what failed. One case per defect
found on the human path, and the pre-push review; the toy and the fake ``claude`` come from test_toy and test_bhorch."""

import json
import os
import subprocess

import bhorch
import bhpresets
from ruamel.yaml import YAML
from bhcore import Config
from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fake is a fixture)
from test_review_rules import MAJOR, network_build, reviews
from test_toy import JSON_WRITER, commit_all, git


def _built(toy, fake):  # noqa: F811
    """The toy after one full run: every item met and merged by the harness."""
    fake.spec(
        outputs_by_item={"harness-test-author": ACCEPT},
        files={"harness-builder": {"src/json_writer.py": JSON_WRITER}},
    )
    res = run(orch(toy).run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]} == dict.fromkeys(
        ("csv-reader", "json-writer", "csv2json"), "met"
    )


def _bh(capsys, toy, *argv):
    """``bh`` as the human runs it: (exit code, its last stdout line as JSON, all of stdout)."""
    capsys.readouterr()
    code = bhorch.main([*argv, "--config", str(toy / ".brick-harness" / "config.json")])
    out = capsys.readouterr().out
    return code, json.loads(out.strip().splitlines()[-1]), out


def test_a_human_merge_re_measures_every_item_it_touched(toy, fake, capsys):  # noqa: F811
    """A human merges a branch (--no-ff) that breaks a met item's test. ``bh measure`` at the
    merged HEAD measures every item the merge made stale, the dependents too, and lists them."""
    _built(toy, fake)
    git(toy, "checkout", "-qb", "human")
    t = toy / "tests" / "json-writer" / "test_writer.py"
    t.write_text(t.read_text() + "\n\ndef test_human_expects_more():\n    assert False, 'one more row'\n")
    commit_all(toy, "test: a human tightens the writer's test", "tests")
    git(toy, "checkout", "-q", "main")
    git(toy, "merge", "-q", "--no-ff", "-m", "Merge branch 'human'", "human")
    _, doc, _ = _bh(capsys, toy, "measure")
    got = {i["id"]: i["status"] for i in doc["items"]}
    assert got == {"csv-reader": "met", "json-writer": "unmet", "csv2json": "met"}, doc  # tests/ is every item's
    _, doc, _ = _bh(capsys, toy, "measure", "--item", "json-writer@HEAD")
    assert [(i["id"], i["status"]) for i in doc["items"]] == [("json-writer", "unmet")]


def test_setup_writes_are_one_conventional_commit_and_a_humans_work_stays_out(tmp_path, fake):  # noqa: F811
    """The files the owner approved (issue forms, CODEOWNERS) and the harness's own ignore file
    are committed by the program as one Conventional Commits commit; a human's uncommitted edit
    is left as it was."""
    repo = tmp_path / "app"
    (repo / "src" / "app" / "billing").mkdir(parents=True)
    (repo / "src" / "app" / "__init__.py").write_text("")
    (repo / "src" / "app" / "billing" / "__init__.py").write_text("")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "app")
    (repo / "README.md").write_text("# work in progress\n")  # the human's, not setup's
    o = bhorch.Orchestrator(Config(repo / ".brick-harness" / "config.json"))
    o.phase_setup(approve=["forms"], owners=[("src/app/billing/", "@billing-team")])
    assert git(repo, "log", "-1", "--format=%s").startswith("build(setup): ")
    assert git(repo, "rev-list", "--count", "HEAD") == "2"  # one commit
    files = set(git(repo, "show", "--name-only", "--format=", "HEAD").splitlines())
    assert {".github/CODEOWNERS", ".brick-harness/.gitignore"} <= files
    assert any(f.startswith(".github/ISSUE_TEMPLATE/") for f in files)
    assert git(repo, "status", "--porcelain", "--untracked-files=all") == "?? README.md"


def test_a_failed_assertion_is_quoted_in_the_teaching(toy, fake, capsys):  # noqa: F811
    """The red fact quotes the test's own assertion message, keeps wrong -> right -> prevent,
    and stays within the message cap."""
    _built(toy, fake)
    (toy / "src" / "csv_reader.py").write_text("def read_rows(text):\n    return []\n")  # a human's edit
    code, _, out = _bh(capsys, toy, "check")
    line = next(x for x in out.splitlines() if x.startswith("[red] csv-reader-AC1"))
    assert code == 1
    assert "failed an assertion: AssertionError: assert [] == [{'a': '1'}]" in line, line
    assert " -> make csv-reader-AC1 pass without editing tests/ . run bh check before finishing" in line
    assert len(line) <= 300


def test_a_push_is_reviewed_only_when_design_affecting_and_never_blocked(tmp_path, toy, fake):  # noqa: F811
    """The preset's pre-push hook runs ``bh review`` on the pushed range: a design-affecting range
    gets one review whose findings print in teach form, a docs-only range none (0 tokens), and the
    push is never blocked (exit 0)."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    bhpresets.write_precommit(app, bhpresets.presets()["python"])
    doc = YAML(typ="safe").load((app / ".pre-commit-config.yaml").read_text())
    (hook,) = [h for r in doc["repos"] for h in r["hooks"] if h["id"] == "bh-review"]
    assert hook["stages"] == ["pre-push"] and "pre-push" in doc["default_install_hook_types"]
    assert doc["default_stages"] == ["pre-commit"]  # the lint hooks stay at commit time
    _, base, sha = network_build(toy)
    git(toy, "checkout", "-q", "build")
    (toy / "README.md").write_text("docs only\n")
    docs = commit_all(toy, "docs: a human's note", "README.md")
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [MAJOR]}]})
    env = dict(os.environ, PATH=f"{bhpresets.CHECKERS.parent.parent / 'bin'}{os.pathsep}{os.environ['PATH']}")

    def push(frm, to):  # what pre-commit's pre-push stage runs: the entry, with the pushed range
        r = subprocess.run(hook["entry"], shell=True, cwd=toy, capture_output=True, text=True, env={**env, "PRE_COMMIT_FROM_REF": frm, "PRE_COMMIT_TO_REF": to})
        return r.returncode, r.stdout

    code, out = push(base, sha)
    assert code == 0 and len(reviews(fake)) == 1, out  # findings never block the push
    assert "[ID-15] json_writer re-checks the token" in out
    code, out = push(sha, docs)
    assert code == 0 and len(reviews(fake)) == 1, out  # mechanical: no review job, 0 tokens
    assert "no review ran" in out
    code, out = push("0" * 40, sha)  # bh review itself fails on a range it cannot read: still never blocks
    assert code == 0 and len(reviews(fake)) == 1, out
    code, out = push("", sha)  # no pushed range (a new branch's first push in some clients)
    assert code == 0 and "[review] no pushed range" in out, out
