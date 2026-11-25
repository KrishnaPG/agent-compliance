"""The triggered review (QBC-36, the Review row of section 6.1) and the owner's interface in the packet
(QBC-19, duplication row). Triggers are read by the program from the item's whole diff; the reviewer
is the fake host CLI (tests/fake_bin/claude); findings are SARIF facts recorded before the merge, a
critical or major one goes back to the same builder within max_rounds, and none changes "met"."""

import json
import subprocess

import bhpacket
import bhreview
from bhcore import Config
from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fake is a fixture)
from test_toy import JSON_WRITER, commit_all, git


def repo(tmp_path, files):
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    write(r, files)
    return r, commit_all(r, "base")


def write(r, files):
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text)


def domains(r, base, tier="mechanical", cfg=None):
    return {t["domain"]: t["detail"] for t in bhreview.triggers(r, cfg or {}, base, "HEAD", tier)}


# ---------------------------------------------------------------- triggers: facts, never an agent


def test_triggers_come_from_the_ruff_preset_and_parsed_sql(tmp_path):
    r, base = repo(tmp_path, {"db/s.sql": "create table t(a int);\n", "a.py": "x = 1\n", "b.py": "y = 1\n"})
    write(r, {"a.py": 'password = "hunter2"\n', "db/s.sql": "create table t(a int);\nGRANT SELECT ON t TO app;\n"})
    write(r, {"b.py": "y = 2  # the password lives in the vault\n"})
    commit_all(r, "change")
    assert domains(r, base) == {
        "secrets": "a.py: ruff S105 finding changed",
        "grants": "db/s.sql changes a GRANT or REVOKE statement",
    }


def test_a_removed_secret_and_a_revoked_grant_touch_their_domains_too(tmp_path):
    r, base = repo(tmp_path, {"a.py": 'token = "abc123"\n', "s.sql": "REVOKE ALL ON t FROM public;\n"})
    write(r, {"a.py": "x = 1\n", "s.sql": "select 1;\n"})
    commit_all(r, "drop")
    assert set(domains(r, base)) == {"secrets", "grants"}


def test_a_plain_diff_triggers_nothing_and_no_name_list_exists(tmp_path):
    r, base = repo(tmp_path, {"s.sql": "GRANT SELECT ON t TO app;\ncreate table t(a int);\n", "a.py": "x = 1\n"})
    write(r, {"s.sql": "GRANT SELECT ON t TO app;\ncreate table t(a int, b int);\n", "a.py": "import hmac\nfrom decimal import Decimal\n"})
    commit_all(r, "no grant changed, no finding")
    assert domains(r, base) == {}  # money and the like are the project's to declare


def test_a_diff_split_over_commits_is_judged_whole(tmp_path):
    r, base = repo(tmp_path, {"a.py": "x = 1\n"})
    write(r, {"b.py": "y = 1\n"})
    commit_all(r, "harmless first")
    write(r, {"b.py": 'secret = "k-123"\n'})
    commit_all(r, "secret second")
    assert domains(r, base) == {"secrets": "b.py: ruff S105 finding changed"}
    # QBC-36: the trigger in an earlier commit still counts when a later commit is harmless
    write(r, {"c.py": "z = 1\n"})
    commit_all(r, "harmless third")
    assert domains(r, base) == {"secrets": "b.py: ruff S105 finding changed"}
    assert domains(r, "HEAD~1") == {}  # negative control: the harmless last commit alone


def test_design_affecting_items_get_the_duplication_check(tmp_path):
    r, base = repo(tmp_path, {"a.py": "x = 1\n"})
    write(r, {"a.py": "x = 2\n"})
    commit_all(r, "c")
    assert domains(r, base, "design-affecting") == {"duplication": "the item is design-affecting"}


def test_the_project_declares_owners_and_paths_in_review_triggers(tmp_path):
    """P8: config review.triggers; an owner comes from the one owner map (bhpresets.owner_map)."""
    r, base = repo(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'app'\n",
            ".github/CODEOWNERS": "app/pay/ @payments\n",
            "app/__init__.py": "",
            "app/pay/__init__.py": "",
            "app/web/__init__.py": "",
            "db/money/fx.sql": "select 1;\n",
        },
    )
    write(r, {"app/pay/calc.py": "x = 1\n", "db/money/fx.sql": "select 2;\n", "app/web/v.py": "y = 1\n"})
    commit_all(r, "c")
    cfg = {"review": {"triggers": ["@payments", "db/money/", "@nobody"]}}
    assert domains(r, base, cfg=cfg) == {
        "@payments": "app/pay/calc.py is under review.triggers @payments",
        "db/money/": "db/money/fx.sql is under review.triggers db/money/",
    }


# ---------------------------------------------------------------- the owner's interface in the packet


def test_the_packet_carries_the_touched_owners_published_interfaces(tmp_path):
    r, _ = repo(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'app'\n",
            "CODEOWNERS": "app/billing/ @billing\n",
            "app/__init__.py": "",
            "app/billing/__init__.py": "__all__ = ['charge', 'refund']\n",
            "app/billing/core.py": "def charge(): ...\n",
            "app/web/__init__.py": "__all__ = ['serve']\n",
        },
    )
    got = bhreview.packet_owners(r, ["app/billing/core.py"], 300)
    assert got == {"owners": ["@billing"], "interfaces": ["app.billing (@billing): charge, refund"]}
    assert bhreview.packet_owners(r, ["app/web/"], 300) == {"owners": ["web"], "interfaces": ["app.web (web): serve"]}  # folder name
    assert bhreview.packet_owners(r, ["docs/"], 300) == {}  # no owner unit: no field


def test_plan_packet_asks_the_one_owner_map_for_its_declared_paths(toy, monkeypatch):
    asked = []
    got = {"owners": ["@toy-team"], "interfaces": ["src.toyio (@toy-team): read_rows"]}
    monkeypatch.setattr(bhreview, "packet_owners", lambda root, declared, cap: asked.append((declared, cap)) or got)
    p = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    assert asked == [(p["constraints"]["declared_paths"], 300)]
    assert p["constraints"]["owners"] == got["owners"] and p["constraints"]["interfaces"] == got["interfaces"]
    assert "- Interface: src.toyio (@toy-team): read_rows" in bhpacket.render_markdown(p)


# ---------------------------------------------------------------- findings are SARIF facts


def test_findings_are_sarif_with_triage_levels_teaching_and_the_packet():
    f = [
        {"summary": "hand-rolled HMAC compare -> call hmac.compare_digest; reuse auth.verify", "rule": "secrets", "severity": "S2", "evidence": "trigger", "where": "src/a.py:7"},
        {"summary": "a long name -> rename it", "severity": "S3", "where": "src/a.py"},
        {"summary": "typo -> fix", "severity": "S4", "where": "src/b.py:0"},
    ]
    log = bhreview.sarif(f, "i", "ab" * 32, 300)
    run_ = log["runs"][0]
    assert run_["properties"] == {"packet_sha256": "ab" * 32, "item": "i"}
    assert [r["level"] for r in run_["results"]] == ["error", "warning", "note"]
    first = run_["results"][0]
    assert first["message"]["text"] == "[secrets] hand-rolled HMAC compare -> call hmac.compare_digest; reuse auth.verify . NIST SSDF SP 800-218 PW.7"
    assert first["locations"][0]["physicalLocation"]["region"] == {"startLine": 7}
    assert bhreview.errors(log) == ["src/a.py:7 " + first["message"]["text"]]


# ---------------------------------------------------------------- the flow: before the merge, back to the builder


STRICT = {  # json-writer's acceptance test runs the code, so a wrong build misses
    **ACCEPT,
    "json-writer": {
        **ACCEPT["json-writer"],
        "test_code": ACCEPT["json-writer"]["test_code"].replace(
            "importlib.util.find_spec('json_writer') is not None",
            "importlib.import_module('json_writer').write_rows([]) == '[]'",
        ),
    },
}
WRONG = JSON_WRITER.replace("return json.dumps(rows, ensure_ascii=False)", "return 'x'")


def no_defect(toy):
    """No defect item was planned: an open finding stays on its slice (QBC-91, QBC-118)."""
    items = json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"]
    return not [b for b in items if b.get("kind") == "defect"]


def spec_for(fake, reviews, builds):
    fake.spec(
        outputs_by_item={"harness-test-author": STRICT},
        outputs_seq={"harness-reviewer": [{"findings": f} for f in reviews]},
        files_seq={"harness-builder": [{"src/json_writer.py": b} for b in builds]},
    )


MAJOR = {"summary": "a secret compared with == -> call hmac.compare_digest . prevent: use the owner's verify", "rule": "secrets", "severity": "S2", "evidence": "trigger", "where": "src/json_writer.py:3"}


def test_a_major_finding_goes_back_to_the_same_builder_then_merges(toy, fake):
    first = JSON_WRITER + '\napi_token = "t-1"\n'
    spec_for(fake, [[MAJOR], []], [first, first + "\n# compare_digest\n"])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    jw = [j.get("job") or j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == "json-writer"]
    assert jw == ["test_author", "red_run", "builder", "measurer", "review", "builder", "measurer", "review", "merge"]
    builders = [c for c in fake.calls() if c["agent"] == "harness-builder"]
    assert len({c["cwd"] for c in builders}) == 1  # the same clone, the same builder's work
    assert builders[0]["stdin"] == bhpacket.LAUNCH_PROMPT
    assert "[secrets] a secret compared with == -> call hmac.compare_digest" in builders[1]["stdin"]
    review = [c for c in fake.calls() if c["agent"] == "harness-reviewer"][0]
    inp = json.loads(open(review["stdin"].split("Input file (read it first; it names every other path): ")[1].split()[0]).read())
    assert inp["triggers"] == [
        {"domain": "secrets", "detail": "src/json_writer.py: ruff S105 finding changed"},
        {"domain": "duplication", "detail": "the item is design-affecting"},
    ]
    assert inp["diff"].startswith("git diff ") and inp["packet_sha256"] == bhpacket.custody_digest(toy, "json-writer")
    sarifs = sorted((o.out / "json-writer").glob("review-*.sarif"))
    assert len(sarifs) == 2
    log = git(toy, "log", "--format=%s", "main").splitlines()
    merge = next(i for i, m in enumerate(log) if m.startswith("brick-harness: merge json-writer"))
    assert log.index("brick-harness: review json-writer") > merge  # newest first: recorded before the merge


def test_findings_left_at_the_round_limit_never_change_met(toy, fake):
    cfgp = toy / ".brick-harness" / "config.json"
    cfgp.write_text(json.dumps({**json.loads(cfgp.read_text()), "max_rounds": 1}))
    commit_all(toy, "one round")
    spec_for(fake, [[{**MAJOR, "severity": "S1"}]], [JSON_WRITER + '\napi_token = "t-1"\n'])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    assert len([c for c in fake.calls() if c["agent"] == "harness-builder"]) == 1
    (sarif,) = (o.out / "json-writer").glob("review-*.sarif")
    assert json.loads(sarif.read_text())["runs"][0]["results"][0]["level"] == "error"
    gaps = json.loads(o.cfg.file("gaps").read_text())["gaps"]
    assert any("hmac.compare_digest" in json.dumps(g) for g in gaps)  # recorded where findings live
    assert "stuck" not in [f["kind"] for r in res["phases"]["rounds"] for f in r["facts"]]  # met, not stuck
    assert no_defect(toy) and not (toy / "src" / "json_writer.py").exists()  # met, not admitted to main (QBC-118)


def test_a_new_feature_whose_diff_triggers_no_domain_still_gets_the_duplication_review(toy, fake):
    """json-writer is new behaviour, which no fact proves mechanical, so it is design-affecting
    (R6, section 6.1): the reviewer runs once, for the duplication check alone."""
    spec_for(fake, [[]], [JSON_WRITER])
    res = run(orch(toy).run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    reviews = [c for c in fake.calls() if c["agent"] == "harness-reviewer"]
    assert len(reviews) == 1
    inp = json.loads(open(reviews[0]["stdin"].split("Input file (read it first; it names every other path): ")[1].split()[0]).read())
    assert inp["triggers"] == [{"domain": "duplication", "detail": "the item is design-affecting"}]


def test_a_later_round_that_misses_never_undoes_the_met_build(toy, fake):
    """Round 1 is met with a major finding, round 2's build misses: the round-1 build stays met, and
    its open finding keeps it out of main (QBC-118)."""
    first = JSON_WRITER + '\napi_token = "t-1"\n'
    spec_for(fake, [[MAJOR]], [first, WRONG])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    assert not (toy / "src" / "json_writer.py").exists()  # the met build is not on main
    assert no_defect(toy) and "not_admitted" in [f["kind"] for r in res["phases"]["rounds"] for f in r["facts"]]
    assert len([c for c in fake.calls() if c["agent"] == "harness-reviewer"]) == 1


def test_a_measurer_miss_goes_back_with_only_the_missed_checks(toy, fake):
    spec_for(fake, [[]], [WRONG, JSON_WRITER])
    res = run(orch(toy).run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    builders = [c for c in fake.calls() if c["agent"] == "harness-builder"]
    assert len(builders) == 2
    retry = builders[1]["stdin"].removeprefix(bhpacket.LAUNCH_PROMPT)
    lines = [ln for ln in retry.splitlines() if ln.startswith("- ")]
    assert lines and any("json-writer-AC1" in ln for ln in lines)
    assert all("[red" in ln or "[json-writer-AC1]" in ln for ln in lines), lines


def test_an_item_unmet_at_the_round_limit_is_stuck(toy, fake):
    spec_for(fake, [[]], [WRONG])
    res = run(orch(toy).run())
    rnd = next(r for r in res["phases"]["rounds"] if r["item"] == "json-writer")
    assert rnd["status"] == "unmet" and "stuck" in [f["kind"] for f in rnd["facts"]]
    assert len([c for c in fake.calls() if c["agent"] == "harness-builder"]) == 3  # max_rounds default
