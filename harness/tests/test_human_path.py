"""A human author's change gets what an agent's gets (section 0 G1, G2; QBC-16): measured after a
merge, a clean tree after setup, and a failure message that says what failed. One case per defect
found on the human path; the toy and the fake ``claude`` come from test_toy and test_bhorch."""

import json

import bhorch
from bhcore import Config
from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fake is a fixture)
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
