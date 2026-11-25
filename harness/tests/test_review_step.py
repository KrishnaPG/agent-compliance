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


def domains(r, base, tier="mechanical"):
    return {t["domain"]: t["detail"] for t in bhreview.triggers(r, base, "HEAD", tier)}


# ---------------------------------------------------------------- triggers: facts, never an agent


def test_triggers_come_from_parsed_imports_and_sql_statements(tmp_path):
    r, base = repo(tmp_path, {"db/s.sql": "create table t(a int);\n", "a.py": "x = 1\n", "b.py": "import json\n"})
    write(r, {"a.py": "import hmac\nfrom decimal import Decimal\n", "db/s.sql": "create table t(a int);\nGRANT SELECT ON t TO app;\n"})
    write(r, {"b.py": "import json  # hmac in a comment is not an import\ns = 'jwt'\n"})
    commit_all(r, "change")
    d = domains(r, base)
    assert d == {"keys": "a.py imports hmac", "grants": "db/s.sql changes a GRANT or REVOKE statement", "money": "a.py imports decimal"}


def test_a_removed_import_and_a_revoked_grant_touch_their_domains_too(tmp_path):
    r, base = repo(tmp_path, {"a.py": "import jwt\n", "s.sql": "REVOKE ALL ON t FROM public;\n"})
    write(r, {"a.py": "x = 1\n", "s.sql": "select 1;\n"})
    commit_all(r, "drop")
    assert set(domains(r, base)) == {"auth", "signatures", "grants"}


def test_sql_without_a_dcl_change_and_a_plain_diff_trigger_nothing(tmp_path):
    r, base = repo(tmp_path, {"s.sql": "GRANT SELECT ON t TO app;\ncreate table t(a int);\n", "a.py": "x = 1\n"})
    write(r, {"s.sql": "GRANT SELECT ON t TO app;\ncreate table t(a int, b int);\n", "a.py": "x = 2\n"})
    commit_all(r, "no grant changed")
    assert domains(r, base) == {}


def test_a_diff_split_over_commits_is_judged_whole(tmp_path):
    r, base = repo(tmp_path, {"a.py": "x = 1\n"})
    write(r, {"pay/__init__.py": ""})
    commit_all(r, "harmless first")
    write(r, {"pay/calc.py": "import decimal\n"})
    commit_all(r, "money second")
    assert domains(r, base) == {"money": "pay/calc.py imports decimal"}


def test_design_affecting_items_get_the_duplication_check(tmp_path):
    r, base = repo(tmp_path, {"a.py": "x = 1\n"})
    write(r, {"a.py": "x = 2\n"})
    commit_all(r, "c")
    assert domains(r, base, "design-affecting") == {"duplication": "the item is design-affecting"}


def test_the_project_declares_semantics_by_owner_and_replaces_a_domain(tmp_path):
    """P8: .brick-harness/review-triggers.json replaces a domain of the plugin's table; owners come
    from CODEOWNERS (the last matching line wins)."""
    r, base = repo(
        tmp_path,
        {
            ".github/CODEOWNERS": "* @all\nsrc/login/ @identity\n",
            ".brick-harness/review-triggers.json": json.dumps(
                {"triggers": {"auth": {"owners": ["@identity"]}, "keys": {"python_apis": []}}}
            ),
            "src/login/flow.py": "x = 1\n",
        },
    )
    write(r, {"src/login/flow.py": "import hmac\n"})
    commit_all(r, "c")
    assert domains(r, base) == {"auth": "src/login/flow.py is owned by @identity"}


# ---------------------------------------------------------------- the owner's interface in the packet


def test_the_packet_carries_the_touched_owners_published_interfaces(tmp_path):
    r, _ = repo(
        tmp_path,
        {
            "CODEOWNERS": "src/billing/ @billing\nsrc/web/ @web\n",
            "src/billing/__init__.py": "__all__ = ['charge', 'refund']\n",
            "src/billing/core.py": "def charge(): ...\n",
            "src/web/__init__.py": "__all__ = ['app']\n",
        },
    )
    got = bhreview.packet_owners(r, ["src/billing/core.py"], 300)
    assert got == {"owners": ["@billing"], "interfaces": ["src/billing (@billing): charge, refund"]}
    assert bhreview.packet_owners(r, ["docs/"], 300) == {}  # no owner declared: no field


def test_plan_packet_fills_owners_and_interfaces_from_codeowners(toy):
    (toy / "CODEOWNERS").write_text("src/ @toy-team\n")
    (toy / "src" / "__init__.py").write_text("__all__ = ['read_rows']\n")
    commit_all(toy, "owners")
    p = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    assert p["constraints"]["owners"] == ["@toy-team"]
    assert p["constraints"]["interfaces"] == ["src (@toy-team): read_rows"]
    assert "- Interface: src (@toy-team): read_rows" in bhpacket.render_markdown(p)


# ---------------------------------------------------------------- findings are SARIF facts


def test_findings_are_sarif_with_triage_levels_teaching_and_the_packet():
    f = [
        {"summary": "hand-rolled HMAC compare -> call hmac.compare_digest; reuse auth.verify", "rule": "keys", "severity": "S2", "evidence": "trigger", "where": "src/a.py:7"},
        {"summary": "a long name -> rename it", "severity": "S3", "where": "src/a.py"},
        {"summary": "typo -> fix", "severity": "S4", "where": "src/b.py:0"},
    ]
    log = bhreview.sarif(f, "i", "ab" * 32, 300)
    run_ = log["runs"][0]
    assert run_["properties"] == {"packet_sha256": "ab" * 32, "item": "i"}
    assert [r["level"] for r in run_["results"]] == ["error", "warning", "note"]
    first = run_["results"][0]
    assert first["message"]["text"] == "[keys] hand-rolled HMAC compare -> call hmac.compare_digest; reuse auth.verify . NIST SSDF SP 800-218 PW.7"
    assert first["locations"][0]["physicalLocation"]["region"] == {"startLine": 7}
    assert bhreview.errors(log) == ["src/a.py:7 " + first["message"]["text"]]


# ---------------------------------------------------------------- the flow: before the merge, back to the builder


def spec_for(fake, reviews, builds):
    fake.spec(
        outputs_by_item={"harness-test-author": ACCEPT},
        outputs_seq={"harness-reviewer": [{"findings": f} for f in reviews]},
        files_seq={"harness-builder": [{"src/json_writer.py": b} for b in builds]},
    )


MAJOR = {"summary": "a secret compared with == -> call hmac.compare_digest . prevent: use the owner's verify", "rule": "keys", "severity": "S2", "evidence": "trigger", "where": "src/json_writer.py:3"}


def test_a_major_finding_goes_back_to_the_same_builder_then_merges(toy, fake):
    first = JSON_WRITER.replace("import json\n", "import hmac\nimport json\n")
    spec_for(fake, [[MAJOR], []], [first, first + "\n# compare_digest\n"])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    jw = [j.get("job") or j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == "json-writer"]
    assert jw == ["test_author", "red_run", "builder", "measurer", "review", "builder", "measurer", "review", "merge"]
    builders = [c for c in fake.calls() if c["agent"] == "harness-builder"]
    assert len({c["cwd"] for c in builders}) == 1  # the same clone, the same builder's work
    assert builders[0]["stdin"] == bhpacket.LAUNCH_PROMPT
    assert "[keys] a secret compared with == -> call hmac.compare_digest" in builders[1]["stdin"]
    review = [c for c in fake.calls() if c["agent"] == "harness-reviewer"][0]
    inp = json.loads(open(review["stdin"].split("Input file (read it first; it names every other path): ")[1].split()[0]).read())
    assert inp["triggers"] == [
        {"domain": "keys", "detail": "src/json_writer.py imports hmac"},
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
    spec_for(fake, [[{**MAJOR, "severity": "S1"}]], [JSON_WRITER.replace("import json\n", "import hmac\nimport json\n")])
    o = orch(toy)
    res = run(o.run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    assert len([c for c in fake.calls() if c["agent"] == "harness-builder"]) == 1
    (sarif,) = (o.out / "json-writer").glob("review-*.sarif")
    assert json.loads(sarif.read_text())["runs"][0]["results"][0]["level"] == "error"
    gaps = json.loads(o.cfg.file("gaps").read_text())["gaps"]
    assert any("hmac.compare_digest" in json.dumps(g) for g in gaps)  # recorded where findings live
    assert "stuck" not in [f["kind"] for r in res["phases"]["rounds"] for f in r["facts"]]  # met, not stuck


def test_a_mechanical_item_whose_diff_triggers_nothing_starts_no_reviewer(toy, fake, monkeypatch):
    real = bhpacket.plan_packet
    monkeypatch.setattr(bhpacket, "plan_packet", lambda cfg, item: {**real(cfg, item), "tier": "mechanical"})
    spec_for(fake, [[MAJOR]], [JSON_WRITER])
    res = run(orch(toy).run())
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    assert [c for c in fake.calls() if c["agent"] == "harness-reviewer"] == []
