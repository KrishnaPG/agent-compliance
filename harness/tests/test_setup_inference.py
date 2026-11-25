"""P9, QBC-60 to QBC-63, QBC-81: `bh run` works with no `.brick-harness/config.json`.

The test entry, language, install and dependency commands come from the project's own standard
files (justfile, Makefile, package.json, the pytest config, the lockfile), each recorded as an
``inferred`` fact naming its file. What no file gives, and the standard-file writes setup
offers, is one owner question; the answer is that standard file, never a plugin file.
"""

import json
import shutil
from pathlib import Path

import bhbuilder
import bhinfer
import bhorch
import pytest
from bhcore import Config
from test_bhorch import ACCEPT, fake  # noqa: F401  (the fake claude fixture)
from test_toy import JSON_WRITER, commit_all, git

ROOT = Path(__file__).resolve().parent.parent
GREET = "exports.greet = (name) => `hello ${name}`;\n"
GREET_TEST = (
    "const test = require('node:test');\nconst assert = require('node:assert');\n\n"
    "test('greet_AC1 says hello', () => {\n"
    "  const { greet } = require('../../src/greet.js');\n"
    "  assert.strictEqual(greet('a'), 'hello a');\n});\n"
)


@pytest.fixture
def bh_run(monkeypatch, capsys):
    """`bh run` from the project root through the bh CLI's own entry, with no --config: the
    default path does not exist. The builder's host check (R10) is tested in
    test_launch_probe, not by this host's groups."""
    monkeypatch.setitem(bhbuilder.LAUNCH_DEFAULTS, "refuse_groups", [])

    def go(repo, *a):
        monkeypatch.chdir(repo)
        code = bhorch.main(["run", *a])
        text = capsys.readouterr().out
        assert code == 0, text
        return json.loads((repo / ".brick-harness" / "out" / "run-result.json").read_text()), text

    return go


@pytest.fixture
def python_toy(tmp_path):
    """The toy with no config: its documents at their conventional names, src on pytest's own
    ``pythonpath``, and only the targets its tests measure. The whole suite is the test entry,
    so the test directories that need the unbuilt item are left out (the author's acceptance tests cover them)."""
    repo = tmp_path / "toy"
    shutil.copytree(
        ROOT / "examples" / "toy",
        repo,
        ignore=shutil.ignore_patterns(
            "config.json",
            "scoreboard*",
            "gaps*",
            "out",
            "__pycache__",
            "bench.py",
            "json-writer",
            "csv2json",
        ),
    )
    (repo / "docs").mkdir()
    (repo / "PLAN.md").rename(repo / "docs" / "build-order.md")
    (repo / "features.md").rename(repo / "docs" / "features.md")
    (repo / "pytest.ini").write_text("[pytest]\npythonpath = src\n")
    tf = repo / ".brick-harness" / "targets.json"
    t = json.loads(tf.read_text())
    t["targets"] = [x for x in t["targets"] if x["metric"].startswith("tests.")]
    tf.write_text(json.dumps(t, indent=2))
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


@pytest.fixture
def node_repo(tmp_path):
    """A small Node project: package.json's test script runs node's own test runner; one
    planned item, greet, not built yet."""
    repo = tmp_path / "greet"
    (repo / "src").mkdir(parents=True)
    (repo / "test").mkdir()
    (repo / "docs").mkdir()
    pkg = {"name": "greet", "version": "1.0.0", "private": True, "scripts": {"test": "node --test"}}
    (repo / "package.json").write_text(json.dumps(pkg, indent=2))
    lock = {
        "name": "greet",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": {"name": "greet", "version": "1.0.0"}},
    }
    (repo / "package-lock.json").write_text(json.dumps(lock, indent=2))
    (repo / "test" / "smoke.test.js").write_text(
        "const test = require('node:test');\ntest('smoke', () => {});\n"
    )
    (repo / "docs" / "build-order.md").write_text(
        "# Plan\n\n## Build order\n\n1. greet: say hello.\n"
    )
    (repo / "docs" / "features.md").write_text(
        "# Features\n\n## F1 greet\n\n- Acceptance checks:\n  - greet says hello\n"
    )
    hd = repo / ".brick-harness"
    hd.mkdir()
    brick = {
        "id": "greet",
        "job": "Say hello to a name.",
        "features": ["F1"],
        "ecosystem": "node",
        "path": "src/greet.js",
        "source": "docs/build-order.md:5",
    }
    (hd / "bricks.json").write_text(json.dumps({"bricks": [brick]}, indent=2))
    (hd / "targets.json").write_text(
        json.dumps(
            {"targets": [{"item": "greet", "metric": "tests.failed", "op": "==", "value": 0}]},
            indent=2,
        )
    )
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "greet")
    return repo


def test_bh_run_builds_the_python_toy_with_no_config(python_toy, fake, bh_run):  # noqa: F811
    fake.spec(
        outputs_by_item={"harness-test-author": ACCEPT},
        files={"harness-builder": {"src/json_writer.py": JSON_WRITER}},
    )
    res, text = bh_run(python_toy)
    assert not (python_toy / ".brick-harness" / "config.json").exists()
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]} == dict.fromkeys(
        ("csv-reader", "json-writer", "csv2json"), "met"
    )
    facts = [f["detail"] for f in res["phases"]["setup"]["facts"]]
    assert (
        "test: pytest (from pytest.ini)" in facts and "language: python (from pytest.ini)" in facts
    )
    assert "build_order: docs/build-order.md (from docs/build-order.md)" in facts
    assert "inferred test: pytest (from pytest.ini)" in text  # the run report names the file
    assert git(python_toy, "check-ignore", ".brick-harness/out/x")  # the run state is ignored


def test_bh_run_builds_a_node_project_with_no_config(node_repo, fake, bh_run):  # noqa: F811
    accept = {
        "greet": {
            "acceptance": [
                {
                    "id": "greet-AC1",
                    "scenario": "s",
                    "traces_to": ["docs/build-order.md:5"],
                    "verification": "test",
                }
            ],
            "test_code": GREET_TEST,
        }
    }
    fake.spec(
        outputs_by_item={"harness-test-author": accept},
        files={"harness-builder": {"src/greet.js": GREET}},
    )
    res, _ = bh_run(node_repo)
    facts = {f["detail"].split(":")[0]: f["detail"] for f in res["phases"]["setup"]["facts"]}
    assert facts["test"] == "test: npm test (from package.json)"
    assert facts["language"] == "language: node (from package-lock.json)"
    assert facts["install"] == "install: ['npm ci --ignore-scripts'] (from package-lock.json)"
    assert facts["dependency"] == "dependency: npm install <package> (from package-lock.json)"
    assert [(r["item"], r["status"]) for r in res["phases"]["rounds"]] == [("greet", "met")], res[
        "phases"
    ]["rounds"]
    packet = json.loads((node_repo / ".brick-harness" / "packets" / "greet.json").read_text())
    assert packet["verifier"]["acceptance_paths"] == ["test/acceptance/greet.test.js"]
    assert packet["paved_road"]["dependency_command"] == "npm install <package>"


def test_what_no_file_says_is_asked_once_and_answered_by_a_standard_file(tmp_path, fake):  # noqa: F811
    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / "README.md").write_text("# bare\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "bare")
    orch = bhorch.Orchestrator(Config(repo / ".brick-harness" / "config.json"))
    setup = orch.phase_setup()
    asked = {q["id"]: q for q in setup["questions"]}
    assert set(asked) == {"Q-test", "Q-setup"}  # one question each, all writes together
    assert "justfile" in asked["Q-test"]["summary"] and "forms" in asked["Q-setup"]["summary"]
    assert not (repo / ".github").exists()  # nothing written without the owner's yes
    (repo / "justfile").write_text("test:\n    echo ok\n")  # the answer is the standard file
    setup = orch.phase_setup(approve=[])  # --approve with none named: all it asked for
    assert setup["questions"] == []
    assert "test: just test (from justfile)" in [f["detail"] for f in setup["facts"]]
    assert setup["written"]["forms"]["written"]
    status = git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    plugin_files = [
        s for s in status if ".brick-harness/" in s and not s.endswith(".brick-harness/.gitignore")
    ]
    assert plugin_files == []  # no plugin config file (QBC-63)
    assert orch.phase_setup()["questions"] == []  # answered: not asked again


def test_one_inference_owner_no_second_detector():
    """bh-init is gone, and no other module keeps a lockfile or test-entry table of its own."""
    assert not (ROOT.parent / "bin" / "bh-init").exists()
    assert "subprocess" not in (ROOT / "lib" / "bhinfer.py").read_text()  # reads files, runs nothing
    for mod in ("bhcore", "bhpacket", "bhorch"):
        text = (ROOT / "lib" / f"{mod}.py").read_text()
        assert "PREPARE = (" not in text and "LOCK_ADD = (" not in text, mod
    assert bhinfer.infer(ROOT / "examples" / "toy")["test"] == {
        "value": "pytest",
        "source": "pytest.ini",
    }
