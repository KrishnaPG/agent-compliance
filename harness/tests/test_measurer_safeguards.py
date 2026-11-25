"""Measurer safeguards (SG-01, 02, 05, 06, 09, 10): no gates, so every test here expects the
score to come from the targets alone and the safeguard to appear as a recorded fact.

Fixtures are git repositories built from examples/toy, as in test_toy.py.
"""

import json

import pytest
from test_toy import JSON_WRITER, build, cli, commit_all, copy_toy, git


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def result(toy, ref, item="json-writer"):
    code, run = cli("bh-measure", toy, "--item", f"{item}@{ref}")
    return code, run["items"][item]


def append(path):
    def edit(r):
        p = r / path
        p.write_text((p.read_text() if p.exists() else "") + "\n\ndef test_fail():\n    assert 0\n")

    return edit


# ------------------------------------------------------------------ SG-01


@pytest.mark.parametrize(
    "path,edit",
    [
        (".brick-harness/targets.json", lambda r: None),
        (".brick-harness/bricks.json", lambda r: None),
        (".brick-harness/config.json", lambda r: None),
        (".brick-harness/scoreboard.json", lambda r: None),
        ("tests/json-writer/test_writer.py", append("tests/json-writer/test_writer.py")),
        ("bench.py", append("bench.py")),
    ],
)
def test_ref_edits_to_plan_and_protected_paths_have_no_effect_and_are_listed(toy, path, edit):
    def both(r):
        if edit(r) is None:
            p = r / path
            p.write_text((p.read_text() if p.exists() else "") + " ")  # JSON stays valid
        # a target that could never be met, were the ref's copy used
        t = r / ".brick-harness" / "targets.json"
        doc = json.loads(t.read_text())
        doc["targets"] = [x for x in doc["targets"] if x["item"] != "json-writer"] + [
            {"item": "json-writer", "metric": "tests.failed", "op": ">=", "value": 99}
        ]
        t.write_text(json.dumps(doc))

    sha = build(toy, edit=both, touched=[path, ".brick-harness/targets.json"])
    code, r = result(toy, sha)
    assert code == 0 and r["status"] == "met", r["errors"]
    assert path in r["ignored_edits"]
    assert ".brick-harness/targets.json" in r["ignored_edits"]


def test_weakened_tests_and_a_wrong_implementation_are_still_unmet(toy):
    def edit(r):
        (r / "src" / "json_writer.py").write_text("def write_rows(rows):\n    return 'x'\n")
        (r / "tests" / "json-writer" / "test_writer.py").write_text(
            "def test_nothing():\n    pass\n"
        )

    sha = build(toy, edit=edit, touched=["tests"])
    code, r = result(toy, sha)
    assert code == 1 and r["status"] == "unmet"
    assert r["metrics"]["tests.failed"] >= 1  # the plan commit's tests ran, not the ref's
    assert "tests/json-writer/test_writer.py" in r["ignored_edits"]


def test_file_added_under_a_protected_path_is_removed_from_the_checkout(toy):
    def edit(r):
        (r / "tests" / "json-writer" / "test_extra.py").write_text(
            "def test_bad():\n    assert 0\n"
        )

    sha = build(toy, edit=edit, touched=["tests"])
    code, r = result(toy, sha)
    assert code == 0 and r["status"] == "met" and r["metrics"]["tests.total"] == 2
    assert r["ignored_edits"] == ["tests/json-writer/test_extra.py"]


def test_ref_with_no_edits_to_guarded_paths_lists_none(toy):
    code, r = result(toy, build(toy))
    assert code == 0 and "ignored_edits" not in r


def test_branch_accepts_edits_to_protected_paths(toy):
    sha = build(toy, edit=append("tests/json-writer/test_writer.py"), touched=["tests"])
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", sha)
    assert code == 0 and r["ok"] and r["ref"] == sha, r
    assert git(toy, "rev-parse", "refs/heads/bh/json-writer") == sha


def test_ref_not_built_on_the_plan_commit_is_measured_and_noted(toy):
    sha = build(toy)
    t = toy / ".brick-harness" / "targets.json"
    doc = json.loads(t.read_text())
    doc["targets"].append({"item": "json-writer", "metric": "tests.errors", "op": "==", "value": 0})
    t.write_text(json.dumps(doc, indent=1))
    cli("bh-commit", toy, "--message", "plan: one more target")
    code, r = result(toy, sha)
    assert code == 0 and r["status"] == "met", r["errors"]
    assert any("plan commit" in n for n in r["notes"])
    assert any(c["metric"] == "tests.errors" for c in r["targets"])  # the plan's targets scored it


def test_merge_restores_plan_and_protected_paths_a_ref_edited(toy):
    original = (toy / "tests" / "json-writer" / "test_writer.py").read_text()

    def edit(r):
        (r / "tests" / "json-writer" / "test_writer.py").write_text(
            "def test_nothing():\n    pass\n"
        )
        (r / "tests" / "json-writer" / "test_extra.py").write_text("def test_extra():\n    pass\n")

    sha = build(toy, edit=edit, touched=["tests"])
    assert result(toy, sha)[0] == 0
    cli("bh-commit", toy, "--message", "scoreboard")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["merged"] == [{"item": "json-writer", "ref": sha}], m
    assert (toy / "tests" / "json-writer" / "test_writer.py").read_text() == original
    assert not (toy / "tests" / "json-writer" / "test_extra.py").exists()
    assert (toy / "src" / "json_writer.py").read_text() == JSON_WRITER  # the build is kept
    assert "restore plan and protected paths" in git(toy, "log", "-1", "--format=%s")


# ------------------------------------------------------------------ SG-02


def test_scope_lists_paths_outside_the_item_and_names_the_contract_does_not_export(toy):
    c = toy / ".brick-harness" / "contracts" / "json-writer.json"
    doc = json.loads(c.read_text())
    doc["exports"] = ["write_rows"]
    c.write_text(json.dumps(doc))
    cli("bh-commit", toy, "--message", "contract exports")

    def edit(r):
        (r / "src" / "json_writer.py").write_text(
            JSON_WRITER + "\nPUBLIC = 1\n_private = 2\n\n\ndef helper():\n    return 1\n"
        )
        (r / "src" / "extra.py").write_text("X = 1\n")
        (r / ".brick-harness" / "catalogue.json").write_text(
            (r / ".brick-harness" / "catalogue.json").read_text() + " "
        )

    sha = build(toy, edit=edit, touched=[".brick-harness/catalogue.json"])
    code, r = result(toy, sha)
    assert code == 0 and r["status"] == "met", r["errors"]  # reported, never scored
    assert r["scope"] == {"outside_paths": ["src/extra.py"], "unlisted_names": ["PUBLIC", "helper"]}


def test_scope_without_declared_exports_lists_only_paths(toy):
    def edit(r):
        (r / "src" / "extra.py").write_text("X = 1\n")

    code, r = result(toy, build(toy, edit=edit))
    assert code == 0 and r["scope"] == {"outside_paths": ["src/extra.py"]}


def test_scope_is_absent_when_the_ref_stays_inside_the_item(toy):
    code, r = result(toy, build(toy))
    assert code == 0 and "scope" not in r


# ------------------------------------------------------------------ SG-05


def test_same_tree_passing_and_failing_is_recorded_as_flaky_without_changing_status(toy):
    flag = toy / ".brick-harness" / "out" / "json-writer" / "flag"  # the jail's writable out dir
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("")
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["commands"]["test"]["run"] += " $(cat $BH_OUT/flag)"
    cfgp.write_text(json.dumps(cfg))
    cli("bh-commit", toy, "--message", "flaky test command")
    sha = build(toy)
    code, first = result(toy, sha)
    assert code == 0 and first["status"] == "met" and "flaky" not in first
    flag.write_text("-k nomatch")  # the same tree now fails
    code, second = result(toy, sha)
    assert code == 1 and second["status"] == "unmet"  # the status is the measurement's alone
    assert [x["status"] for x in second["flaky"]["runs"]] == ["met", "unmet"]
    assert second["flaky"]["runs"][1]["errors"]


def test_different_trees_with_different_results_are_not_flaky(toy):
    code, ok = result(toy, build(toy))

    def broken(r):
        (r / "src" / "json_writer.py").write_text("def write_rows(rows):\n    return 'x'\n")

    code, bad = result(toy, build(toy, edit=broken))
    assert ok["status"] == "met" and bad["status"] == "unmet" and "flaky" not in bad


# ------------------------------------------------------------------ SG-06

BENCH_RUN = (
    "n=$(cat {cnt} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {cnt}; "
    "case $n in 1) v=10;; 2) v=100;; *) v=40;; esac; "
    'echo "{\\"rows_per_s\\": $v, \\"p50_ms\\": 1}" > {out}/bench.json'
)


def bench_toy(toy, runs):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["commands"]["bench"]["run"] = BENCH_RUN.replace("{cnt}", "$BH_OUT/cnt")
    cfgp.write_text(json.dumps(cfg))
    tp = toy / ".brick-harness" / "targets.json"
    doc = json.loads(tp.read_text())
    for t in doc["targets"]:
        if t["item"] == "csv-reader" and t["metric"] == "bench.rows_per_s":
            t["value"] = 40
            if runs:
                t["runs"] = runs
    tp.write_text(json.dumps(doc))


def test_bench_runs_repeat_and_the_median_is_the_value(toy):
    bench_toy(toy, 3)
    code, run = cli("bh-measure", toy, "--item", "csv-reader")
    r = run["items"]["csv-reader"]
    assert r["status"] == "met" and r["metrics"]["bench.rows_per_s"] == 40, (
        r
    )  # median of 10, 100, 40
    assert [x["name"] for x in r["runs"]].count("bench") == 3
    n = r["noise"]["bench.rows_per_s"]
    assert (n["runs"], n["min"], n["max"], n["median"]) == (3, 10, 100, 40)
    assert n["within_noise"] == [">= 40"]  # the target sits inside what the runs spanned


def test_a_single_bench_run_records_no_noise(toy):
    bench_toy(toy, None)
    code, run = cli("bh-measure", toy, "--item", "csv-reader")
    r = run["items"]["csv-reader"]
    assert [x["name"] for x in r["runs"]].count("bench") == 1 and "noise" not in r
    assert r["metrics"]["bench.rows_per_s"] == 10


# ------------------------------------------------------------------ SG-09


def test_added_and_changed_lockfile_packages_are_reported_against_the_stack_record(toy):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["paths"]["lockfiles"] = ["requirements.txt"]
    cfg["standards"] = {"stack": ["pytest", "rich==13"]}
    cfgp.write_text(json.dumps(cfg))
    (toy / "requirements.txt").write_text("pytest==8.0.0\nrequests==2.31.0\n")
    commit_all(toy, "lockfile and stack record")

    def edit(r):
        (r / "requirements.txt").write_text(
            "pytest==9.0.0\nrequests==2.31.0\nrich==13.7.0\nleft-pad==1.0.0\n"
        )

    sha = build(toy, edit=edit, touched=["requirements.txt"])
    code, r = result(toy, sha)
    assert code == 0 and r["status"] == "met", r["errors"]  # reported, never scored
    d = r["dependencies"]
    assert d["added"] == {"rich": "13.7.0", "left-pad": "1.0.0"}
    assert d["changed"] == {"pytest": ["8.0.0", "9.0.0"]}
    assert d["not_in_stack"] == ["left-pad"] and d["second_major"] == ["pytest"]


def test_no_dependency_fact_when_the_lockfiles_are_unchanged(toy):
    code, r = result(toy, build(toy))
    assert code == 0 and "dependencies" not in r


# ------------------------------------------------------------------ SG-10


def with_environment(toy, env):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    marker = toy / ".brick-harness" / "out" / "csv2json" / "marker"
    cfg["environments"] = {"staging": {"run": "echo staged >> $BH_OUT/marker; sh -c {cmd}"}}
    if env:
        cfg["commands"]["test"]["environment"] = env
    cfgp.write_text(json.dumps(cfg))
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER)
    commit_all(toy, "json writer")
    return marker


def test_system_item_runs_in_its_named_environment_and_records_it(toy):
    marker = with_environment(toy, "staging")
    code, run = cli("bh-measure", toy, "--item", "csv2json")
    r = run["items"]["csv2json"]
    assert r["status"] == "met", r["errors"]
    assert r["environment"] == "staging" and marker.read_text() == "staged\n"
    code, run = cli("bh-measure", toy, "--item", "json-writer")
    assert "environment" not in run["items"]["json-writer"]  # a plain brick records none


def test_system_item_without_an_environment_records_local(toy):
    with_environment(toy, None)
    code, run = cli("bh-measure", toy, "--item", "csv2json")
    assert run["items"]["csv2json"]["environment"] == "local"


def test_an_undefined_environment_cannot_run_and_says_so(toy):
    with_environment(toy, "nowhere")
    code, run = cli("bh-measure", toy, "--item", "csv2json")
    r = run["items"]["csv2json"]
    assert code == 1 and any("'nowhere' is not defined" in e for e in r["errors"])
