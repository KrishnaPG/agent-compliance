"""SG-19: the catalog's checks run with every item's measurement, by default.

No gates: ``rules.violations == 0`` is one more measured target; suppressions, class shares
and check candidates are facts; the review of a sellable feature only records findings.
Nothing here downloads: a fixture catalog and a fake checker print ast-grep's JSON shape.
"""

import hashlib
import json
import platform
import re
import zipfile

import bhcore
import bhrules
import pytest
from test_toy import EMPTY_CATALOG, ROOT, cli, commit_all, copy_toy, git
from test_work_tracking import cfg_edit, plan_edit

FIX = ROOT / "tests" / "fixtures" / "rules"
CAT, FAKE = FIX / "cat", FIX / "fake-checker"


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    return repo


def with_catalog(repo, **standards):
    cfg_edit(
        repo,
        standards={"catalog": str(CAT), **standards},
        checks={"checker": str(FAKE)},
    )


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return commit_all(repo, f"write {rel}", rel)


def measure(repo, item="csv-reader"):
    _, run = cli("bh-measure", repo, "--item", item)
    return run["items"][item]


def metrics(r):
    return {t["metric"]: t for t in r["targets"]}


# ---------------------------------------------------------------- checks run by default


def test_without_a_catalog_that_ships_checks_nothing_is_added(toy):
    r = measure(toy)
    assert r["status"] == "met" and "rules" not in r
    assert "rules.violations" not in metrics(r)


def test_violations_in_the_items_files_are_the_metric_and_unmet_until_zero(toy):
    with_catalog(toy)
    r = measure(toy)
    assert r["status"] == "met" and metrics(r)["rules.violations"]["actual"] == 0
    write(toy, "src/csv_reader.py", (toy / "src/csv_reader.py").read_text() + "\ntime.sleep(1)\n")
    write(toy, "src/other.py", "time.sleep(2)\n")  # not the item's file, not changed by its ref
    r = measure(toy)
    m = metrics(r)["rules.violations"]
    assert r["status"] == "unmet" and m["actual"] == 1 and not m["met"]
    assert r["rules"]["by_rule"] == {"RL-08": 1}
    assert r["rules"]["findings"][0]["file"] == "src/csv_reader.py"


def test_files_the_ref_changed_count_even_outside_the_items_paths(toy):
    with_catalog(toy)
    git(toy, "checkout", "-q", "-b", "side")
    sha = write(toy, "src/extra.py", "time.sleep(3)\n")
    git(toy, "checkout", "-q", "main")
    _, run = cli("bh-measure", toy, "--item", f"csv-reader@{sha}")
    assert run["items"]["csv-reader"]["rules"]["violations"] == 1


def test_the_target_is_part_of_the_packet_and_the_digest(toy):
    with_catalog(toy)
    cfg = bhcore.Config(toy / ".brick-harness" / "config.json")
    assert "- rules.violations == 0" in bhcore.work_packet(cfg, "csv-reader")["text"]
    before = bhcore.target_digest(cfg, {"id": "csv-reader"}, [])
    cfg.data["standards"]["catalog"] = str(EMPTY_CATALOG)
    assert bhcore.target_digest(cfg, {"id": "csv-reader"}, []) != before


def test_the_catalog_is_this_plugins_own_unless_a_path_names_another(toy):
    cfg_edit(toy, standards={"catalog": str(CAT)})
    cfg = bhcore.Config(toy / ".brick-harness" / "config.json")
    assert bhrules.catalog_root(cfg) == CAT and len(bhrules.load_index(cfg)) == 3
    own = json.loads((bhcore.PLUGIN_ROOT / "checks" / "index.json").read_text())["checks"]
    for value in (None, "<catalog>", "agent-compliance"):
        cfg.data["standards"] = {} if value is None else {"catalog": value}
        assert bhrules.catalog_root(cfg) == bhcore.PLUGIN_ROOT
        assert len(bhrules.load_index(cfg)) == len(own) > 0


def test_the_stack_decides_which_ecosystem_and_pack_checks_run(tmp_path):
    def stack(*files):
        d = tmp_path / str(len(list(tmp_path.iterdir())))
        d.mkdir()
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("x")
        return bhrules.detect(d)

    assert stack("pyproject.toml") == ({"python"}, set())
    assert stack("package.json") == ({"typescript"}, set())
    assert stack("db/migrations/1.txt") == ({"sql"}, {"postgresql"})
    assert stack("a.sql", "b.py") == ({"python", "sql"}, {"postgresql"})
    assert stack("README.md") == (set(), set())


def test_the_sql_pack_runs_only_when_sql_is_detected(toy):
    with_catalog(toy)
    write(toy, "src/csv_reader.py", (toy / "src/csv_reader.py").read_text() + "\n")
    assert "DS-01" not in measure(toy)["rules"]["by_rule"]
    write(toy, "db/migrations/1.sql", "DROP TABLE t;\n")
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(paths=["db"]))
    assert measure(toy)["rules"]["by_rule"]["DS-01"] == 1


# ---------------------------------------------------------------- opt-out, facts the code shows


def test_a_project_opts_a_rule_out_only_in_the_catalogs_form_with_a_reason(toy):
    write(toy, "src/csv_reader.py", (toy / "src/csv_reader.py").read_text() + "\ntime.sleep(1)\n")
    with_catalog(toy)
    ov = "docs/agents/design-compliance.md"
    reason = "a batch tool whose schedule is the product"
    for text in (
        "## Check opt-outs\n\n- RL-08 not-applicable:\n",  # no reason: nothing is opted out
        "## Check opt-outs\n- RL-08 not-applicable:   \n",
        f"## Rules\n\n- RL-08 not-applicable: {reason}\n",  # not under the heading
        f"## Check opt-outs\n\n| RL-08 | not-applicable: {reason} |\n",  # not the line form
        f"## Check opt-outs\n\n## Rules\n\n- RL-08 not-applicable: {reason}\n",
    ):
        write(toy, ov, text)
        assert measure(toy)["rules"]["violations"] == 1, text
    write(toy, ov, f"# Overlay\n\n## Check opt-outs\n\n- RL-08 not-applicable: {reason}\n")
    assert measure(toy)["rules"]["violations"] == 0
    facts = cli("bh-gaps", toy)[1]["facts"]
    na = [f for f in facts if f["kind"] == "rule-not-applicable"]
    assert na == [
        {
            "kind": "rule-not-applicable",
            "rule": "RL-08",
            "reason": "a batch tool whose schedule is the product",
        }
    ]


def test_the_overlay_is_found_as_the_skills_find_it(toy):
    cfg = bhcore.Config(toy / ".brick-harness" / "config.json")
    assert bhcore.overlay_file(cfg) is None
    write(toy, "docs/agents/design-compliance.md", "# fallback\n")
    assert bhcore.overlay_path(cfg) == "docs/agents/design-compliance.md"
    write(toy, "docs/agents/bindings.md", "| Overlay | `rules/mine.md` |\n")
    write(toy, "rules/mine.md", "# mine\n")
    assert bhcore.overlay_path(cfg) == "rules/mine.md"
    write(toy, "AGENTS.md", "Bindings: `ops/bindings.md`\n")
    write(toy, "ops/bindings.md", "| Overlay | rules/other.md |\n")
    write(toy, "rules/other.md", "# other\n")
    assert bhcore.overlay_path(cfg) == "rules/other.md"


def test_entry_modules_are_inferred_from_routes_and_without_them_the_owner_decides(toy):
    with_catalog(toy)
    entry = "from fastapi import APIRouter\nr = APIRouter()\nx = request.args\n"
    write(
        toy, "src/csv_reader.py", (toy / "src/csv_reader.py").read_text() + "\nx = request.args\n"
    )
    r = measure(toy)
    assert "ID-01" not in r["rules"]["by_rule"] and r["rules"]["skipped"][0]["rule"] == "ID-01"
    # the entry module is the one allowed place: the check scans every other module
    _, g = cli("bh-gaps", toy)
    gap = next(x for x in g["gaps"] if x.get("area") == "entry_modules")
    assert (
        gap["tag"] == "owner-decides"
        and gap["kind"] == "unsettled-area"
        and "ID-01" in gap["summary"]
    )
    write(toy, "src/app.py", entry)  # the entry module has the same call and is not scanned
    assert bhrules.entry_modules(toy) == ["src/app.py"]
    r = measure(toy)
    assert r["rules"]["by_rule"] == {"ID-01": 1}
    assert r["rules"]["findings"][0]["file"] == "src/csv_reader.py"
    assert not [x for x in cli("bh-gaps", toy)[1]["gaps"] if x.get("area") == "entry_modules"]


def test_the_real_id15_and_ho02_rules_scan_every_module_except_the_bound_ones(toy):
    """The catalog's own ID-15 and HO-02 python rule files, run by the pinned ast-grep: the
    entry module may verify and the outbox module may publish; the same calls elsewhere count."""
    cfg_edit(toy, standards={"catalog": str(bhcore.PLUGIN_ROOT)})  # the catalog's own checks
    cfg = bhcore.Config(toy / ".brick-harness" / "config.json")
    cmd, label, why = bhrules.checker(cfg)
    if cmd is None:
        pytest.skip(f"pinned ast-grep not available: {why}")
    files = {
        "src/fx/app.py": "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "def entry(tok, key):\n    return jwt.decode(tok, key, algorithms=['RS256'])\n",
        "src/fx/service.py": "def inner(tok, key):\n    return jwt.decode(tok, key, algorithms=['RS256'])\n",
        "src/fx/relay.py": 'def store(conn):\n    conn.execute("insert into outbox (subject) values ($1)", s)\n'
        "async def relay(js, row):\n    await js.publish(row.subject, row.payload)\n",
        "src/fx/direct.py": "async def emit(js, subject, payload):\n    await js.publish(subject, payload)\n",
    }
    for rel, text in files.items():
        write(toy, rel, text)
    assert bhrules.entry_modules(toy) == ["src/fx/app.py"]
    assert bhrules.outbox_modules(toy) == ["src/fx/relay.py"]
    r = bhrules.run_checks(cfg, toy, {"paths": ["src/fx"]}, [])
    assert r["error"] is None and r["checker"] == label
    assert not [s for s in r["skipped"] if s["rule"] in ("ID-15", "HO-02")]
    found = {(f["rule"], f["file"]) for f in r["findings"] if f["rule"] in ("ID-15", "HO-02")}
    assert found == {("ID-15", "src/fx/service.py"), ("HO-02", "src/fx/direct.py")}
    assert r["by_rule"]["ID-15"] == 1 and r["by_rule"]["HO-02"] == 1


# ---------------------------------------------------------------- the checker is pinned and verified


def test_the_pinned_checker_has_a_version_and_a_sha256():
    spec = json.loads((ROOT / "checkers.json").read_text())["ast-grep"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", spec["version"]) and spec["version"] in spec["url"]
    assert re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])


def test_a_download_whose_sha256_differs_is_not_run_and_leaves_nothing(tmp_path):
    z = tmp_path / "rel.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ast-grep", "#!/bin/sh\n")
    spec = {
        "version": "9",
        "platform": f"{platform.system()}-{platform.machine()}".lower(),
        "url": z.as_uri(),
        "sha256": hashlib.sha256(z.read_bytes()).hexdigest(),
        "member": "ast-grep",
    }
    exe = bhrules.ensure(spec, tmp_path / "cache")
    assert exe.read_text() == "#!/bin/sh\n" and exe.stat().st_mode & 0o100
    with pytest.raises(bhcore.HarnessError, match="does not match"):
        bhrules.ensure({**spec, "sha256": "0" * 64}, tmp_path / "other")
    assert not (tmp_path / "other").exists()
    with pytest.raises(bhcore.HarnessError, match="no pinned release"):
        bhrules.ensure({**spec, "platform": "plan9-arm"}, tmp_path / "third")


def test_when_the_checker_cannot_run_the_metric_is_absent_and_the_report_says_why(toy):
    with_catalog(toy)
    cfg_edit(toy, checks={"checker": str(FIX / "missing")})
    r = measure(toy)
    assert r["status"] == "unmet" and "rules.violations" not in r["metrics"]
    assert any("rules: checker failed" in e for e in r["errors"])


# ---------------------------------------------------------------- suppressions


def test_suppressions_a_ref_adds_are_listed_and_never_scored(toy):
    with_catalog(toy)
    git(toy, "checkout", "-q", "-b", "side")
    p = toy / "src" / "csv_reader.py"
    sha = write(
        toy, "src/csv_reader.py", p.read_text() + "\nx = 1  # noqa: E501\ny = 2  # my-marker\n"
    )
    git(toy, "checkout", "-q", "main")
    cfg_edit(toy, standards={"catalog": str(CAT), "suppressions": ["my-marker"]})
    _, run = cli("bh-measure", toy, "--item", f"csv-reader@{sha}")
    r = run["items"]["csv-reader"]
    assert [(s["file"], s["text"][:6]) for s in r["suppressions"]] == [
        ("src/csv_reader.py", "x = 1 "),
        ("src/csv_reader.py", "y = 2 "),
    ]
    assert r["status"] == "met"


# ---------------------------------------------------------------- the packet's judgment rules


def tagged(repo, **extra):
    plan_edit(
        repo,
        "bricks.json",
        lambda d: d["bricks"][0].update(
            paths=["src/queue_worker.py"],
            rules=[{"id": r, "reason": "the worker spec calls for it"} for r in ("NO-02", "HO-01", "HO-02", "RL-05", "RL-06")],
            **extra,
        ),
    )
    plan_edit(repo, "bricks.json", lambda d: d["bricks"][1].update(embodies=["HO-02"]))


def rules_of(repo, item="csv-reader"):
    cfg = bhcore.Config(repo / ".brick-harness" / "config.json")
    return bhcore.packet_rules(cfg, item)


def test_the_packet_has_the_items_own_rules_with_one_line_each(toy):
    with_catalog(toy)
    tagged(toy)
    got = {r["id"]: r["text"] for r in rules_of(toy)}
    assert set(got) == {"NO-02", "HO-01", "HO-02", "RL-05", "RL-06"}
    assert got["NO-02"] == "OSS before code. [S2]"  # with its default severity (QBC-114)
    assert got["RL-05"] == "A process waits on its dependency's native readiness. [S2]"
    assert rules_of(toy, "json-writer") == []  # no rules of its own
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(depends_on=["json-writer"]))
    got = {r["id"]: r["text"] for r in rules_of(toy)}  # embodied by a brick it uses: kept, marked (QBC-106)
    assert got["HO-02"].endswith("[embodied by json-writer]") and "embodied" not in got["HO-01"]


def test_findings_rank_the_rules_and_the_limit_caps_them(toy):
    with_catalog(toy)
    tagged(toy)
    f = toy / "f.json"
    f.write_text(json.dumps([{"summary": f"s{i}", "rule": "RL-06"} for i in range(3)]))
    assert cli("bh-rank", toy, "--add", str(f), "--write")[0] == 0
    ids = [r["id"] for r in rules_of(toy)]
    assert ids[0] == "RL-06" and len(ids) == 5  # most broken first, among the item's own
    cfg_edit(toy, limits={"packet_rules": 2})
    capped = rules_of(toy)  # the first two are full lines; the rest by id and title (QBC-105 (iv))
    assert [r["id"] for r in capped[:2]] == ["RL-06", "HO-01"] and len(capped) == 5
    assert [r["text"].endswith(f"(bh rule {r['id']})") for r in capped] == [False, False, True, True, True]
    assert (
        len(
            bhcore.work_packet(bhcore.Config(toy / ".brick-harness" / "config.json"), "csv-reader")[
                "text"
            ]
        )
        > 0
    )


# ---------------------------------------------------------------- report facts


def test_class_shares_and_check_candidates_are_report_facts(toy):
    with_catalog(toy)
    tagged(toy)
    f = toy / "f.json"
    f.write_text(
        json.dumps(
            [{"summary": f"s{i}", "rule": "HO-01"} for i in range(2)]
            + [{"summary": "t", "rule": "RL-06"}]
        )
    )
    cli("bh-rank", toy, "--add", str(f), "--write")
    facts = {x["kind"]: x for x in cli("bh-gaps", toy)[1]["facts"]}
    c = facts["rule-classes"]
    assert c["in_use"] == 7 and c["enforced"].startswith("2 ") and c["embodied"].startswith("1 ")
    assert c["judgment"].startswith("4 ")
    assert facts["check-candidates"]["rules"] == "HO-01 x2"
