"""The toy project proves reuse: the bin tools drive a second project in its own git repo.

json-writer has its contract, targets and tests but no implementation, so a cycle must
build it; these tests play the builder by committing it on the bh/json-writer branch.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cmds
import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT.parent / "bin"  # the plugin root: bin/ is on PATH while it is enabled
JSON_WRITER = '''"""json-writer brick: list of row dicts -> JSON array text."""

import json


def write_rows(rows: list[dict[str, str]]) -> str:
    return json.dumps(rows, ensure_ascii=False)
'''
ENV = dict(
    {k: v for k, v in os.environ.items() if k not in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")},  # commit dates are real time: the harvest window compares them with measurement times
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.invalid",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.invalid",
)


def git(repo, *a):
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


EMPTY_CATALOG = ROOT / "tests" / "fixtures" / "rules" / "empty"


def copy_toy(dest):
    """The toy, set to a catalog with no rules or checks (tests of the plugin's own catalog
    unset ``standards.catalog``)."""
    shutil.copytree(
        ROOT / "examples" / "toy",
        dest,
        ignore=shutil.ignore_patterns("scoreboard*", "gaps*", "out", "__pycache__"),
    )
    conf = dest / ".brick-harness" / "config.json"
    data = json.loads(conf.read_text())
    data.setdefault("standards", {})["catalog"] = str(EMPTY_CATALOG)
    conf.write_text(json.dumps(data, indent=2) + "\n")


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def commit_all(repo, msg, *paths):
    """Commit ``paths`` (default: everything); a builder commits only what it changed."""
    git(repo, "add", "-A", "--", *(paths or ["."]))
    git(repo, "commit", "-qm", msg, "--", *(paths or ["."]))
    return git(repo, "rev-parse", "HEAD")


def call(name, argv, cwd=None, stdin=None):
    """Run a harness command: ``bh-measure`` and ``bh-init`` as the programs they are, the rest as
    the library calls (``cmds.py``). ``(exit code, stdout text)``."""
    if name in cmds.COMMANDS:
        return cmds.run(name, argv, cwd=cwd, env=ENV, stdin=stdin)
    p = subprocess.run([sys.executable, str(BIN / name), *argv], input=stdin, capture_output=True, text=True, cwd=cwd, env=ENV)
    return p.returncode, p.stdout


def cli(name, repo, *a, config=None):
    code, out = call(name, ["--config", str(config or repo / ".brick-harness" / "config.json"), *a], cwd=repo)
    return code, json.loads(out)


def full_state(repo, config=None):
    """Run bh-state bare: the full state is the file its summary names (rule 5)."""
    code, summary = cli("bh-state", repo, config=config)
    if "file" not in summary:
        return code, summary
    return code, json.loads(Path(summary["file"]).read_text())


def status(repo, **kw):
    _, s = full_state(repo, **kw)
    return {b["id"]: b["status"] for b in s["bricks"]}, s


def build(repo, item="json-writer", edit=None, touched=(), base="main"):
    """Play a builder: commit src/ and ``touched`` on bh/<item> forked from ``base``."""
    git(repo, "checkout", "-qB", f"bh/{item}", base)
    (repo / "src" / "json_writer.py").write_text(JSON_WRITER)
    if edit:
        edit(repo)
    sha = commit_all(repo, f"build {item}", "src", *touched)
    git(repo, "checkout", "-q", "main")
    return sha


def test_state_before_measuring(toy):
    code, s = full_state(toy)
    assert code == 0, s["problems"]
    assert s["ready"] == ["csv-reader", "json-writer"]
    assert s["ready_system"] == []
    assert s["waves"] == [["csv-reader", "json-writer"], ["csv2json"]]
    assert s["commands"]["json-writer"]["test"]["run"].endswith(
        "tests/json-writer --junitxml .brick-harness/out/json-writer/junit.xml"
    )


def test_unbuilt_item_is_unmet_at_head(toy):
    code, run = cli("bh-measure", toy, "--item", "json-writer")
    assert code == 1 and run["items"]["json-writer"]["status"] == "unmet"
    code, run = cli("bh-measure", toy, "--item", "csv-reader")
    assert code == 0, run
    assert run["items"]["csv-reader"]["metrics"]["bench.rows_per_s"] >= 20000


def test_build_measure_merge_remeasure_until_all_met(toy):
    cli("bh-measure", toy, "--item", "csv-reader")
    sha = build(toy)
    st, s = status(toy)
    assert s["branches"] == {"json-writer": sha}
    code, run = cli("bh-measure", toy, "--item", f"json-writer@{sha}", "--slot", "1")
    assert code == 0, run
    st, s = status(toy)
    assert st["json-writer"] == "met-unmerged" and s["unmerged"] == [
        {"item": "json-writer", "ref": sha}
    ]
    assert s["ready_system"] == []  # dependents wait for the code in HEAD
    code, c = cli("bh-commit", toy, "--message", "scoreboard")
    assert code == 0 and c["committed"], c
    code, m = cli("bh-merge", toy)
    assert code == 0, m
    assert m["merged"] == [{"item": "json-writer", "ref": sha}] and m["conflicts"] == []
    assert m["remeasure"] == ["json-writer", "csv2json"]
    st, s = status(toy)
    assert st["json-writer"] == "met" and s["ready_system"] == ["csv2json"]
    for item in m["remeasure"]:  # the merged result is measured at HEAD
        code, run = cli("bh-measure", toy, "--item", item)
        assert code == 0, run
        assert run["items"][item]["ref"] == git(toy, "rev-parse", "HEAD")
    cli("bh-commit", toy, "--message", "scoreboard")
    st, s = status(toy)
    assert s["all_met"] is True, st  # committing the scoreboard moves HEAD; results still hold
    cli("bh-commit", toy, "--message", "again")
    assert status(toy)[1]["all_met"] is True
    # a later change to the item's code at HEAD makes its result stale (and its dependents')
    p = toy / "src" / "json_writer.py"
    p.write_text(p.read_text() + "\n# changed\n")
    commit_all(toy, "change")
    st, _ = status(toy)
    assert st["json-writer"] == "stale" and st["csv2json"] == "stale" and st["csv-reader"] == "met"


def test_failed_candidate_never_replaces_met_current(toy):
    cli("bh-measure", toy, "--item", "csv-reader")
    git(toy, "checkout", "-qb", "bh/csv-reader")
    src = toy / "src" / "csv_reader.py"
    src.write_text(src.read_text().replace("return list(", "return [] and list("))
    sha = commit_all(toy, "break", "src")
    git(toy, "checkout", "-q", "main")
    code, _ = cli("bh-measure", toy, "--item", f"csv-reader@{sha}")
    assert code == 1
    st, s = status(toy)
    assert st["csv-reader"] == "met" and "csv-reader" not in s["ready"]


def test_merge_conflict_makes_item_ready_with_paths(toy):
    sha = build(
        toy,
        edit=lambda r: (r / "src" / "csv2json.py").write_text(
            (r / "src" / "csv2json.py").read_text() + "\n# from builder\n"
        ),
    )
    cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    p = toy / "src" / "csv2json.py"
    p.write_text(p.read_text() + "\n# from main\n")
    commit_all(toy, "main edits the same line")
    cli("bh-commit", toy, "--message", "scoreboard")
    code, m = cli("bh-merge", toy)
    assert code == 0, m
    assert m["merged"] == [] and m["conflicts"][0]["paths"] == ["src/csv2json.py"]
    st, s = status(toy)
    assert st["json-writer"] == "conflict" and "json-writer" in s["ready"]
    last = {b["id"]: b["last"] for b in s["bricks"]}["json-writer"]
    assert last["errors"] == ["conflicts with HEAD at src/csv2json.py"]
    assert not (toy / ".git" / "MERGE_HEAD").exists()


def test_catalogue_conflict_is_a_json_union(toy):
    cat = toy / ".brick-harness" / "catalogue.json"

    def add(entry):
        def edit(r):
            doc = json.loads(cat.read_text())
            doc["entries"].append(entry)
            cat.write_text(json.dumps(doc, indent=1))

        return edit

    sha = build(
        toy,
        edit=add(
            {"job": "units", "ecosystem": "python", "library": "pint", "used_by": ["json-writer"]}
        ),
        touched=[".brick-harness/catalogue.json"],
    )
    add(
        {
            "job": "dates",
            "ecosystem": "python",
            "library": "stdlib:datetime",
            "used_by": ["csv-reader"],
        }
    )(toy)
    cli("bh-commit", toy, "--message", "catalogue on main")
    cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    cli("bh-commit", toy, "--message", "scoreboard")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["merged"], m
    libs = {e["library"] for e in json.loads(cat.read_text())["entries"]}
    assert {"pint", "stdlib:datetime", "stdlib:csv"} <= libs


def test_broken_ref_feeds_its_numbers_back_for_a_rebuild(toy):
    git(toy, "checkout", "-qb", "broken")
    src = toy / "src" / "csv_reader.py"
    src.write_text(src.read_text().replace("return list(", "return [] and list("))
    sha = commit_all(toy, "break")
    git(toy, "checkout", "-q", "main")
    cli("bh-measure", toy, "--item", "csv-reader@broken")
    _, s = full_state(toy)
    last = {b["id"]: b["last"] for b in s["bricks"]}["csv-reader"]
    assert last["ref"] == sha and last["status"] == "unmet"
    failed = [u for u in last["unmet"] if u["metric"] == "tests.failed"][0]
    assert failed["actual"] >= 1 and failed["op"] == "==" and failed["value"] == 0


def test_harvest_ref_affects_the_items_whose_paths_it_touches(toy):
    git(toy, "checkout", "-qb", "harvest")
    p = toy / "src" / "csv_reader.py"
    p.write_text(p.read_text() + "\n# shared helper\n")
    sha = commit_all(toy, "harvest")
    git(toy, "checkout", "-q", "main")
    code, a = cli("bh-state", toy, "--affected", sha)
    assert code == 0 and a["affected"] == ["csv-reader", "csv2json"]


def remote_config(toy, copy=True):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    env = "" if copy else "BH_SKIP_COPY=1 "
    cfg["commands"]["test"]["run"] = env + "sh remote_test.sh {item} {out}"
    cfgp.write_text(json.dumps(cfg))


def test_remote_test_command_leaves_results_in_out(toy):
    remote_config(toy)
    code, run = cli("bh-measure", toy, "--item", "csv-reader")
    assert run["items"]["csv-reader"]["metrics"]["tests.passed"] >= 2
    assert run["items"]["csv-reader"]["status"] == "met"


def test_remote_test_command_without_results_is_unmet(toy):
    remote_config(toy, copy=False)
    code, run = cli("bh-measure", toy, "--item", "csv-reader")
    r = run["items"]["csv-reader"]
    assert code == 1 and r["status"] == "unmet"
    assert any("junit" in e for e in r["errors"])


def test_toy_has_no_gaps_na_areas_and_config_commands_settle(toy):
    code, r = cli("bh-gaps", toy)
    assert code == 0, r
    assert r["gaps"] == []
    assert r["written"] == [] and not (toy / ".brick-harness" / "gaps.json").exists()


def test_gaps_find_faults_with_file_line_evidence(toy):
    h = toy / ".brick-harness"
    b = json.loads((h / "bricks.json").read_text())
    b["bricks"].append({"id": "orphan", "job": "x", "depends_on": ["nowhere"]})
    b["bricks"].append({"id": "csv-reader", "job": "again"})
    (h / "bricks.json").write_text(json.dumps(b, indent=1))
    t = json.loads((h / "targets.json").read_text())
    t["targets"].append({"item": "json-writer", "metric": "bench.size_kb", "op": "<=", "value": 1})
    t["targets"].append({"item": "ghost", "metric": "tests.failed", "op": "==", "value": 0})
    t["targets"].append(
        {
            "item": "csv2json",
            "metric": "bench.p50_ms",
            "op": "<=",
            "value": 5,
            "source": "features.md:8",
        }
    )
    (h / "targets.json").write_text(json.dumps(t, indent=1))
    (toy / "features.md").write_text(
        (toy / "features.md").read_text()
        + "\nSee [spec](missing.md), [ok](/PLAN.md#build-order), [sp](my%20notes.md).\n\n[ref]: gone.md\n"
    )
    (toy / "my notes.md").write_text("# n\n")
    cfg = json.loads((h / "config.json").read_text())
    cfg["commands"].pop("bench")
    cfg["commands"]["test"]["pending"] = "runner not written"
    cfg["sections"]["status"] = "Nope"
    (h / "config.json").write_text(json.dumps(cfg, indent=1))
    _, r = cli("bh-gaps", toy)
    kinds = {}
    for g in r["gaps"]:
        kinds.setdefault(g["kind"], []).append(g)
    for k in (
        "no-numeric-target",
        "no-contract",
        "missing-dependency",
        "item-without-source",
        "target-without-command",
        "target-without-source",
        "target-on-unknown-item",
        "duplicate-item",
        "dangling-reference",
    ):
        assert k in kinds, k
        for g in kinds[k]:
            for e in g["evidence"]:
                assert (toy / e["file"]).is_file() and e["line"] >= 1
    links = sorted(g["summary"] for g in kinds["dangling-reference"] if "link" in g["summary"])
    assert links == ["link to gone.md does not resolve", "link to missing.md does not resolve"]
    assert any("Nope" in g["summary"] for g in kinds["dangling-reference"])
    assert kinds["no-numeric-target"][0]["tag"] == "owner-decides"
    src = {g["summary"] for g in kinds["target-without-source"]}
    assert any("bench.size_kb" in x and "no source" in x for x in src)
    assert any("bench.p50_ms" in x and "does not state 5" in x for x in src)
    _, s = full_state(toy)
    assert s["ready"] == [] and s["ready_system"] == []  # every item is blocked now
    blocked = {b["id"]: b["blocked_by"] for b in s["bricks"]}
    pending = [g["id"] for g in s["gaps"] if "not yet present" in g["summary"]][0]
    assert pending in blocked["csv-reader"] and pending in blocked["json-writer"]


def test_failing_env_setup_blocks_the_item(toy):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["commands"]["env_setup"] = "exit 3"
    cfgp.write_text(json.dumps(cfg, indent=1))
    commit_all(toy, "env")
    cli("bh-measure", toy, "--item", "csv-reader")
    st, s = status(toy)
    assert st["csv-reader"] == "blocked" and "csv-reader" not in s["ready"]
    gap = [g for g in s["gaps"] if "env_setup fails" in g["summary"]][0]
    assert gap["evidence"][0]["file"] == ".brick-harness/config.json"


def test_gaps_add_rejects_unresolvable_evidence_and_writes_only_on_request(toy):
    found = [
        {
            "kind": "contradiction",
            "summary": "rows/s stated twice",
            "tag": "owner-decides",
            "evidence": [
                {"file": "features.md", "line": 8, "quote": "20,000 rows/s"},
                {"file": "PLAN.md", "line": 7},
            ],
        },
        {
            "kind": "contradiction",
            "summary": "made up",
            "tag": "owner-decides",
            "evidence": [{"file": "features.md", "line": 999}],
        },
        {
            "kind": "contradiction",
            "summary": "misquoted",
            "tag": "owner-decides",
            "evidence": [{"file": "features.md", "line": 8, "quote": "50,000 rows/s"}],
        },
        {"kind": "untracked-open-item", "summary": "no evidence", "tag": "fixable", "evidence": []},
    ]
    src = toy / "found.json"
    src.write_text(json.dumps(found))
    _, r = cli("bh-gaps", toy, "--add", str(src))
    review = [g for g in r["gaps"] if g["source"] == "review"]
    assert [g["summary"] for g in review] == ["rows/s stated twice"]
    assert r["received"] == 4 and r["accepted"] == 1 and len(r["rejected"]) == 3
    assert r["written"] == [] and not (toy / ".brick-harness" / "gaps.json").exists()
    _, r2 = cli("bh-gaps", toy, "--add", str(src), "--write")
    assert [g["id"] for g in r2["gaps"] if g["source"] == "review"] == [review[0]["id"]]  # stable
    assert r2["written"] == [".brick-harness/gaps.json", ".brick-harness/gaps.md"]
    src.write_text(json.dumps([]))
    _, r = cli("bh-gaps", toy, "--source", "plan", "--add", str(src), "--write")
    assert any(g["source"] == "review" for g in r["gaps"])  # other sources' findings are kept
    _, r = cli("bh-gaps", toy, "--source", "review", "--add", str(src), "--write")
    assert not any(g["source"] == "review" for g in r["gaps"])  # an empty list clears them
    _, s = full_state(toy)
    assert ".brick-harness/gaps.json" in s["uncommitted"]


def test_state_reports_an_out_dir_that_is_not_git_ignored(toy):
    gi = toy / ".brick-harness" / ".gitignore"
    gi.rename(toy / "moved-gitignore")
    commit_all(toy, "drop ignore")
    _, s = full_state(toy)
    assert any("not git-ignored" in p for p in s["problems"])
    gi.write_text("out/\n")
    commit_all(toy, "restore ignore")
    _, s = full_state(toy)
    assert s["problems"] == []


def test_commit_refuses_moved_targets_and_a_merge_in_progress(toy):
    t = toy / ".brick-harness" / "targets.json"
    doc = json.loads(t.read_text())
    doc["targets"][0]["value"] = 5
    t.write_text(json.dumps(doc))
    code, c = cli("bh-commit", toy, "--message", "move")
    assert code == 2 and "targets dropped or changed" in c["error"]
    git(toy, "checkout", "--", ".brick-harness/targets.json")
    git(toy, "checkout", "-qb", "side")
    (toy / "PLAN.md").write_text("side\n")
    commit_all(toy, "side")
    git(toy, "checkout", "-q", "main")
    (toy / "PLAN.md").write_text("main\n")
    commit_all(toy, "main")
    subprocess.run(["git", "-C", str(toy), "merge", "side"], capture_output=True, env=ENV)
    code, c = cli("bh-commit", toy, "--message", "during merge")
    assert code == 2 and "merge is in progress" in c["error"]
    code, m = cli("bh-merge", toy)
    assert code == 2 and "merge is in progress" in m["error"]


def test_project_in_a_subdirectory_of_the_repo(tmp_path):
    repo = tmp_path / "mono"
    copy_toy(repo / "apps" / "toy")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "mono")
    proj = repo / "apps" / "toy"
    conf = proj / ".brick-harness" / "config.json"
    _, s = full_state(proj, config=conf)
    assert s["problems"] == [] and s["files"]["targets"]["rel"] == ".brick-harness/targets.json"
    git(repo, "checkout", "-qb", "bh/json-writer")
    (proj / "src" / "json_writer.py").write_text(JSON_WRITER)
    sha = commit_all(repo, "build")
    git(repo, "checkout", "-q", "main")
    code, run = cli("bh-measure", proj, "--item", f"json-writer@{sha}", config=conf)
    assert code == 0, run
    code, c = cli("bh-commit", proj, "--message", "sb", config=conf)
    assert code == 0 and ".brick-harness/scoreboard.json" in c["files"]
    code, m = cli("bh-merge", proj, config=conf)
    assert code == 0 and m["remeasure"] == ["json-writer", "csv2json"], m
    for item in ["csv-reader"] + m["remeasure"]:
        assert cli("bh-measure", proj, "--item", item, config=conf)[0] == 0
    cli("bh-commit", proj, "--message", "sb", config=conf)
    assert full_state(proj, config=conf)[1]["all_met"] is True
    # protected paths are relative to the project root, not the repository; edits are ignored
    git(repo, "checkout", "-qb", "bh/csv-reader")
    p = proj / "tests" / "csv-reader" / "test_reader.py"
    p.write_text(p.read_text() + "\n")
    sha = commit_all(repo, "touch a test")
    git(repo, "checkout", "-q", "main")
    _, run = cli("bh-measure", proj, "--item", f"csv-reader@{sha}", config=conf)
    assert run["items"]["csv-reader"]["ignored_edits"] == [
        "apps/toy/tests/csv-reader/test_reader.py"
    ]
    assert run["items"]["csv-reader"]["status"] == "met"


def test_state_summary_is_small_and_the_file_holds_the_full_state(toy):
    code, p = cli("bh-state", toy)
    assert code == 0 and len(json.dumps(p)) < 1500
    on_disk = json.loads(Path(p["file"]).read_text())
    assert [b["id"] for b in on_disk["bricks"]] == ["csv-reader", "json-writer", "csv2json"]
    assert on_disk["head"] == p["head"] and on_disk["counts"]["bricks"] == 3
    for gone in ("pending", "decision", "checklist"):
        assert gone not in on_disk
    for key in ("queue", "oscillating", "learning", "value", "features", "merged"):
        assert key in on_disk
    assert on_disk["learning"]["overlay_candidates"] == []


def test_init_on_an_empty_dir_never_overwrites(tmp_path):
    def init(*a):
        p = subprocess.run(
            [sys.executable, str(BIN / "bh-init"), "--root", str(tmp_path), *a],
            capture_output=True,
            text=True,
        )
        return p.returncode, json.loads(p.stdout)

    git(tmp_path, "init", "-q")
    code, r = init()
    assert code == 0
    assert set(r["created"]) == {".brick-harness/config.json", ".brick-harness/.gitignore"}
    conf = json.loads((tmp_path / ".brick-harness" / "config.json").read_text())
    assert "$schema" not in conf and "overlay" not in conf["standards"]
    code, r = init("--missing", "features")
    assert set(r["created"]) == {"docs/features.md"}
    assert "numeric" in (tmp_path / "docs" / "features.md").read_text()
    (tmp_path / "docs" / "features.md").write_text("# mine\n")
    code, r = init("--missing", "features")
    assert r["created"] == [] and (tmp_path / "docs" / "features.md").read_text() == "# mine\n"
    import bhcore

    cfg = bhcore.Config(tmp_path / ".brick-harness" / "config.json")
    assert cfg.dir == tmp_path
    st = bhcore.state(cfg)
    assert st["problems"] == []
    kinds = {g["kind"] for g in st["gaps"]}
    assert "target-without-command" in kinds and "unsettled-area" not in kinds  # agent-found
    assert not any("standards.catalog" in g["summary"] for g in st["gaps"])  # its own catalog


def test_catalog_skill_named_on_owner_gaps(toy):
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["standards"] = {"catalog": str(EMPTY_CATALOG), "base_version": "1.0.0", "packs": []}
    cfg["catalogue_jobs"] = ["formats", "units"]
    del cfg["na"]["database"]
    cfgp.write_text(json.dumps(cfg))
    _, r = cli("bh-gaps", toy)
    owner = [g for g in r["gaps"] if g["tag"] == "owner-decides"]
    assert owner == []  # design areas are the gaps agent's to find, not a keyword search's
    lib = [g for g in r["gaps"] if g["kind"] == "helper-without-library"][0]
    assert lib["tag"] == "fixable" and lib["resolve_with"] == "agent-compliance:vet-oss"
    cfg["na"]["units"] = "no physical quantities"
    cfgp.write_text(json.dumps(cfg))
    _, r = cli("bh-gaps", toy)
    assert not [g for g in r["gaps"] if g["kind"] == "helper-without-library"]


def test_met_harvest_candidate_of_a_met_item_is_merged(toy):
    cli("bh-measure", toy, "--item", "csv-reader")
    git(toy, "checkout", "-qb", "harvest")
    p = toy / "src" / "csv_reader.py"
    p.write_text(p.read_text() + "\n# shared helper\n")
    sha = commit_all(toy, "harvest", "src")
    git(toy, "checkout", "-q", "main")
    assert cli("bh-measure", toy, "--item", f"csv-reader@{sha}")[0] == 0
    st, s = status(toy)
    assert st["csv-reader"] == "met" and s["unmerged"] == [{"item": "csv-reader", "ref": sha}]
    cli("bh-commit", toy, "--message", "scoreboard")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["merged"] == [{"item": "csv-reader", "ref": sha}], m
    assert git(toy, "merge-base", "--is-ancestor", sha, "HEAD") == ""


def test_merge_takes_refs_from_the_scoreboard_only(toy):
    """H5: an unmet candidate on its branch is never merged, whatever a caller says."""
    sha = build(toy, edit=lambda r: (r / "src" / "json_writer.py").write_text("x = (\n"))
    code, _ = cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    assert code == 1
    cli("bh-commit", toy, "--message", "scoreboard")
    head = git(toy, "rev-parse", "HEAD")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["merged"] == [] and m["remeasure"] == []
    assert git(toy, "rev-parse", "HEAD") == head


GUARD_MSG = "[merge-guard] merge guard removed, merge test failed -> restore the unmerged == [] guard . P6"


def guard_holds(ok, why=""):
    """The catalog's teaching shape, printed plain (no traceback line prefix) when the guard fails."""
    if not ok:
        pytest.fail(f"{GUARD_MSG} {why}"[:300], pytrace=False)


def _measure_and_commit(toy, sha):
    code, run = cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    assert code == 0, run
    cli("bh-commit", toy, "--message", "scoreboard")


def test_merge_of_a_met_item_leaves_nothing_unmerged_in_one_commit(toy):
    """R4/P6: the merge consumes what the scoreboard holds, and a clean merge is exactly the
    builder's commit (no separate restore commit); the candidate is then in HEAD."""
    sha = build(toy)
    assert cli("bh-measure", toy, "--item", f"json-writer@{sha}")[0] == 0
    before = git(toy, "rev-parse", "HEAD")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["merged"] == [{"item": "json-writer", "ref": sha}], m
    assert git(toy, "rev-list", "--count", f"{before}..HEAD") == "1"
    assert git(toy, "merge-base", "--is-ancestor", sha, "HEAD") == ""
    guard_holds(status(toy)[1]["unmerged"] == [])


def test_merge_never_brings_a_ref_edit_of_a_guarded_path_into_head(toy):
    """The measurer ignores a ref's edits of protected paths, so a merge must too: the
    result is one commit per item and HEAD's tests are HEAD's, even though git merged them."""
    def edit(r):
        (r / "tests" / "json-writer" / "test_writer.py").write_text("def test_nothing():\n    pass\n")

    sha = build(toy, edit=edit, touched=("tests",))
    _measure_and_commit(toy, sha)
    guarded = git(toy, "rev-parse", "HEAD:tests/json-writer/test_writer.py")
    before = git(toy, "rev-parse", "HEAD")
    code, m = cli("bh-merge", toy)
    guard_holds(code == 0 and m["merged"], str(m)[:60])
    guard_holds(git(toy, "rev-parse", "HEAD:tests/json-writer/test_writer.py") == guarded)
    assert git(toy, "rev-list", "--count", "--first-parent", f"{before}..HEAD") == "1"
    assert git(toy, "rev-parse", "HEAD:src/json_writer.py") == git(toy, "rev-parse", f"{sha}:src/json_writer.py")


def test_unmet_candidate_never_reaches_head_even_when_the_merge_would_be_clean(toy):
    sha = build(toy, edit=lambda r: (r / "src" / "json_writer.py").write_text("x = (\n"))
    assert cli("bh-measure", toy, "--item", f"json-writer@{sha}")[0] == 1
    cli("bh-commit", toy, "--message", "scoreboard")
    cli("bh-merge", toy)
    p = subprocess.run(["git", "-C", str(toy), "merge-base", "--is-ancestor", sha, "HEAD"])
    assert p.returncode == 1


def test_a_conflict_names_its_item_and_leaves_the_tree_clean(toy):
    sha = build(
        toy,
        edit=lambda r: (r / "src" / "csv2json.py").write_text(
            (r / "src" / "csv2json.py").read_text() + "\n# from builder\n"
        ),
    )
    cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    p = toy / "src" / "csv2json.py"
    p.write_text(p.read_text() + "\n# from main\n")
    commit_all(toy, "main edits the same line")
    cli("bh-commit", toy, "--message", "scoreboard")
    head = git(toy, "rev-parse", "HEAD")
    code, m = cli("bh-merge", toy)
    assert code == 0 and m["conflicts"][0]["item"] == "json-writer"
    assert git(toy, "rev-parse", "HEAD") == head and git(toy, "ls-files", "-u") == ""
    assert git(toy, "status", "--porcelain", "--untracked-files=no", "--", "src") == ""


def test_state_is_complete_for_the_orchestrator(toy):
    s = full_state(toy)[1]
    assert s["ready"] == ["csv-reader", "json-writer"] and s["ready_system"] == []
    assert set(s["commands"]) >= {"csv-reader", "json-writer"}
    assert s["queue"] == ["csv-reader", "json-writer", "csv2json"]
    assert {b["id"]: b["status"] for b in s["bricks"]}["csv2json"] == "unmeasured"
    assert s["head"] == git(toy, "rev-parse", "HEAD") and s["plan_head"]
    assert s["unmerged"] == [] and s["oscillating"] == [] and s["problems"] == []


def test_state_carries_unmerged_and_branches(toy):
    cli("bh-measure", toy, "--item", "csv-reader")
    sha = build(toy)
    cli("bh-measure", toy, "--item", f"json-writer@{sha}")
    s = full_state(toy)[1]
    assert s["unmerged"] == [{"item": "json-writer", "ref": sha}]
    assert {b["id"]: b["status"] for b in s["bricks"]}["json-writer"] == "met-unmerged"
    assert "json-writer" not in s["ready"]
    assert s["branches"] == {"json-writer": sha}


def builder_commit(toy, edit=None, touched=()):
    """Play an isolated builder: commit on a detached worktree branch, no bh/ ref."""
    git(toy, "checkout", "-qb", "worktree-run-1", "main")
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER)
    if edit:
        edit(toy)
    sha = commit_all(toy, "build", "src", *touched)
    git(toy, "checkout", "-q", "main")
    return sha


def test_branch_sets_bh_ref_to_a_builders_commit(toy):
    sha = builder_commit(toy)
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", sha)
    assert code == 0 and r["ok"] and r["ref"] == sha and r["previous"] is None, r
    assert git(toy, "rev-parse", "refs/heads/bh/json-writer") == sha
    assert full_state(toy)[1]["branches"] == {"json-writer": sha}
    # a retry that builds on the previous commit fast-forwards; the same sha is idempotent
    assert cli("bh-branch", toy, "--item", "json-writer", "--ref", sha)[0] == 0
    git(toy, "checkout", "-q", "worktree-run-1")
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER + "\n# retry\n")
    sha2 = commit_all(toy, "retry", "src")
    git(toy, "checkout", "-q", "main")
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", sha2)
    assert code == 0 and r["previous"] == sha
    assert git(toy, "rev-parse", "refs/heads/bh/json-writer") == sha2


def test_branch_refuses_only_what_cannot_be_a_branch(toy):
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", "0" * 40)
    assert code == 2 and not r["ok"] and "not a commit" in r["error"]
    head = git(toy, "rev-parse", "HEAD")
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", head)
    assert code == 2 and "no new commit" in r["error"]  # nothing built
    sha = builder_commit(toy)
    code, r = cli("bh-branch", toy, "--item", "nope", "--ref", sha)
    assert code == 2 and "unknown item" in r["error"]
    assert git(toy, "branch", "--list", "bh/*") == ""


def test_branch_refuses_a_non_fast_forward_move(toy):
    first = builder_commit(toy)
    assert cli("bh-branch", toy, "--item", "json-writer", "--ref", first)[0] == 0
    git(
        toy, "checkout", "-qb", "worktree-run-2", "main"
    )  # a rebuild that ignored the previous commit
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER + "\n# other\n")
    other = commit_all(toy, "other", "src")
    git(toy, "checkout", "-q", "main")
    code, r = cli("bh-branch", toy, "--item", "json-writer", "--ref", other)
    assert code == 2 and "non-fast-forward" in r["error"], r
    assert git(toy, "rev-parse", "refs/heads/bh/json-writer") == first


def test_system_item_never_hides_an_unmeasured_or_unmet_dependency(toy):
    """csv2json measured while json-writer is unbuilt and csv-reader unmeasured: not all met."""
    cli("bh-measure", toy, "--item", "csv2json")
    st, s = status(toy)
    assert st["csv-reader"] == "unmeasured" and st["json-writer"] != "met"
    assert st["csv2json"] != "met" and s["all_met"] is False
    assert "csv2json" not in s["ready_system"]


def test_unmet_gaps_carry_reason_errors_and_cover_never_measured_items(toy):
    cli("bh-measure", toy, "--item", "json-writer")  # unbuilt: unmet with errors
    code, out = call(
        "bh-gaps",
        ["--config", str(toy / ".brick-harness" / "config.json"), "--source", "cycle", "--add", "-",
         "--unmet", "json-writer:no-change", "csv-reader:not-attempted", "csv2json"],
        cwd=toy, stdin="[]",
    )  # fmt: skip
    gaps = [g for g in json.loads(out)["gaps"] if g["kind"] == "unmet-after-rounds"]
    by = {g["summary"].split()[1]: g for g in gaps}
    assert set(by) == {"json-writer", "csv-reader", "csv2json"}
    assert "no-change" in by["json-writer"]["summary"]
    assert "not-attempted" in by["csv-reader"]["summary"]  # never measured: cited in the items file
    assert by["csv-reader"]["evidence"][0]["file"].endswith("bricks.json")
    assert "unmet:" in by["csv2json"]["summary"]
