"""Severity and the right fix come from the rule (section 6.6, QBC-114 and QBC-115), each with a
negative control (QBC-109): a finding on a catalog rule takes the rule's default severity (SARIF
``defaultConfiguration.level``, Semgrep rule ``severity``) and teaches the rule's own right way
first; the catalog holds the generic rules for the defect classes a measured miss showed it lacked,
and the facts select them."""

import json
import tomllib

import bhcore
import bhpacket
import bhreview
import bhrules
import pytest
from bhcore import Config, HarnessError
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_review_rules import network_build, plan
from test_rule_selection import HOUSE, PLUGIN, bh, catalog, conf
from test_toy import commit_all, git

GAP_RULES = ("NO-30", "CF-20", "ID-16", "ID-17", "PF-16", "PF-17")
FIELDS = ("text", "why", "right", "question", "applies", "cites", "severity")


def defaults_hold(house):
    bad = sorted(k for k, r in house.items() if r.get("severity") not in bhrules.SEVERITY)
    assert not bad, f"rules without a default severity: {bad}"


def test_qbc_114_every_rule_has_a_default_severity_from_what_it_protects(tmp_path):
    defaults_hold(HOUSE)
    assert set(bhrules.SEVERITY) == {"S1", "S2", "S3"}
    assert {r["severity"] for r in HOUSE.values()} == {"S1", "S2", "S3"}  # all three classes are used
    spec = (PLUGIN / "docs" / "spec" / "quality-by-construction.md").read_text()
    assert all(f"  - {s} {c}:" in spec for s, c in bhrules.SEVERITY.items())  # the mapping lives in the spec
    with pytest.raises(AssertionError, match="HO-01"):  # negative control: a rule loses its default
        defaults_hold({**HOUSE, "HO-01": {k: v for k, v in HOUSE["HO-01"].items() if k != "severity"}})
    for bad in ('[house.XX-01]\ntext = "t"\napplies = ["time"]\n', '[house.XX-01]\ntext = "t"\nseverity = "S9"\napplies = ["time"]\n'):
        with pytest.raises(HarnessError, match="catalog-severity"):  # negative control: refused as a catalog error
            bhrules.rules_doc(catalog(tmp_path, bad))


def test_qbc_114_bh_rule_prints_the_default_severity(toy, capsys):
    plan(toy)
    code, out = bh(capsys, "rule", "--config", conf(toy), "ID-16")
    assert code == 0 and "Severity: S1 (critical)" in out
    code, out = bh(capsys, "rule", "--config", conf(toy), "NO-05")
    assert "Severity: S3 (minor)" in out and "S1 (critical)" not in out  # negative control: another class


def finding(rule, severity, evidence="theoretical", **extra):
    return {"summary": f"{rule} broken in the writer -> apply it to write()", "rule": rule, "severity": severity,
            "evidence": evidence, "where": "src/json_writer.py:3", **extra}  # fmt: skip


def test_qbc_114_a_finding_takes_its_rules_default_and_only_evidence_moves_it(toy, fake):  # noqa: F811
    packet, base, sha = network_build(toy)
    major = next(k for k, r in HOUSE.items() if r["severity"] == "S2")
    minor = next(k for k, r in HOUSE.items() if r["severity"] == "S3")
    house = bhrules.rule_meta(Config(conf(toy)))
    out, changes = bhreview.settle(
        [
            finding(major, "S3"),  # lowered by feel: set back to the rule's major default
            finding(major, "S3", severity_reason="src/json_writer.py:1 the module is a declared throwaway spike"),
            finding(major, "S3", severity_reason="src/json_writer.py:3 the line itself"),  # its own line is no evidence
            finding(major, "S3", severity_reason="docs/nowhere.md:4 a missing file"),
            finding(minor, "S2"),  # raised by feel: set back to the rule's minor default
            finding(minor, "S2", evidence="reproduced"),  # raised with a reproduction: kept
            finding("grants", "S2"),  # a triggered domain keeps the reviewer's triage
        ],
        house,
        toy,
        sha,
    )
    assert [f["severity"] for f in out] == ["S2", "S3", "S2", "S2", "S3", "S2", "S2"]
    assert [c["why"].split(":")[0] for c in changes] == ["lowering refused", "lowered", "lowering refused", "lowering refused", "raise refused"]
    # through the review job: the reviewer's S3 on a major rule comes back S2, blocking, and recorded
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [finding(major, "S3")]}]})
    log = run(orch(toy).review_diff(packet, "ab" * 32, base, sha, "design-affecting", []))
    (res,) = log["runs"][0]["results"]
    assert res["properties"]["severity"] == "S2" and res["level"] == "error" and bhreview.errors(log)
    assert log["runs"][0]["properties"]["severity_settled"][0]["asked"] == "S3"
    minor_log = bhreview.sarif(out[4:5], "json-writer", "ab" * 32, 300, house)
    assert bhreview.errors(minor_log) == []  # negative control: a minor rule's finding does not send the build back
    gaps = json.loads((toy / ".brick-harness" / "gaps.json").read_text())["gaps"]
    assert {g["severity"] for g in gaps if g.get("rule") == major} == {"S2"}  # the recorded finding is the settled one


def test_qbc_115_a_findings_right_way_starts_from_its_rule(toy):
    plan(toy)
    meta = bhrules.rule_meta(Config(conf(toy)))
    rid = "ID-15"
    wrong = "write() verifies the bearer token again on every row although the gateway already verified it at entry, so" + " x" * 10
    here = "take the principal the gateway passes as an argument of write() and delete the second jwt.decode call in json_writer" + " y" * 10
    f = finding(rid, "S2", summary=f"{wrong} -> {here}")
    log = bhreview.sarif([f], "json-writer", "ab" * 32, 300, meta)
    (res,) = log["runs"][0]["results"]
    text = res["message"]["text"]
    head, right = text.split(" -> ", 1)
    assert len(text) <= 300 and head.startswith(f"[{rid}] {wrong[:55]}")  # what is wrong still teaches
    assert right.startswith(meta[rid]["right"].rstrip(".") + "; here: take the principal") and right.endswith(f". bh rule {rid}")
    (desc,) = log["runs"][0]["tool"]["driver"]["rules"]
    assert desc == {"id": rid, "defaultConfiguration": {"level": "error"}, "help": {"text": meta[rid]["right"]}, "properties": {"severity": "S2"}}
    bare = bhreview.sarif([f], "json-writer", "ab" * 32, 300)  # negative control: without the rule's metadata
    assert meta[rid]["right"][:40] not in bare["runs"][0]["results"][0]["message"]["text"]
    dom = bhreview.sarif([finding("grants", "S2")], "json-writer", "ab" * 32, 300, meta)
    assert "rules" not in dom["runs"][0]["tool"]["driver"]  # a triggered domain has no rule to describe
    # a catalog with no right text teaches its rule's first clause (bhrules.rule_meta)
    assert bhrules.rule_meta(None, {"house": {"XX-01": {"text": "Do it once. Then more.", "severity": "S2"}}}) == {"XX-01": {"right": "Do it once.", "severity": "S2"}}
    # the reviewer is told to write only the concrete application, never a weaker remedy
    prompt = (PLUGIN / "agents" / "harness-reviewer.md").read_text()
    assert "Never a weaker or different remedy than the rule's" in prompt and "severity_reason" in prompt


def full(rules):
    for rid in GAP_RULES:
        r = rules["house"][rid]
        assert all(r.get(k) for k in FIELDS), f"{rid} lacks a field"
        assert len(r["right"]) <= 160 and set(r["applies"]) <= set(bhrules.TAGS)
        assert all(c.partition(":")[0] in rules["standards"] for c in r["cites"]), f"{rid} cites an unknown standard"


def test_qbc_115_the_generic_gap_rules_have_full_fields_and_the_facts_select_them(toy, capsys):
    rules = tomllib.loads((PLUGIN / "catalog" / "rules.toml").read_text())
    full(rules)
    broken = json.loads(json.dumps(rules))
    broken["house"]["PF-17"]["cites"] = ["Nowhere:1"]
    with pytest.raises(AssertionError, match="PF-17"):  # negative control: a cite with no standard
        full(broken)
    plan(toy)
    item = ["rules", "--config", conf(toy), "--item", "json-writer"]
    before = json.loads(bh(capsys, *item, "--diff")[1])
    assert "NO-30" in {r["id"] for r in before["chosen"] + before["more"]}  # the core reaches every item
    assert not {"CF-20", "ID-16", "ID-17", "PF-16", "PF-17"} & set(before["added_by_diff"])  # negative control
    (toy / "src" / "api.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n")
    (toy / "src" / "tokens.py").write_text("import jwt\n\n\ndef decode(t, key):\n    return jwt.decode(t, key)\n")
    (toy / "src" / "reads.sql").write_text("select id from item;\n")
    (toy / "tests").mkdir(exist_ok=True)
    (toy / "tests" / "test_speed.py").write_text("import time\n\n\ndef test_fast():\n    t = time.process_time()\n    assert time.process_time() - t < 1\n")
    base = git(toy, "rev-parse", "HEAD").strip()
    commit_all(toy, "an api, tokens, a query and a timing test")
    sel = json.loads(bh(capsys, *item, "--diff", base, "HEAD")[1])
    assert {"CF-20", "ID-16", "ID-17", "PF-16", "PF-17"} <= set(sel["added_by_diff"]), sel["tags"]["diff"]
    p = bhpacket.plan_packet(bhcore.Config(conf(toy)), "json-writer")
    assert "NO-30" in {r["id"] for r in p["verifier"]["rules"]}
