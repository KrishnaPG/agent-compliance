"""catalog/rules.toml (R9, QBC-85): standards by reference plus house rules; every check's rule resolves to one."""

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import bhrules

PLUGIN = Path(__file__).resolve().parents[2]


def test_every_check_rule_is_a_house_rule_and_every_citation_names_a_listed_standard():
    rules = tomllib.loads((PLUGIN / "catalog" / "rules.toml").read_text())  # a repeated id is a TOML error
    standards, house = rules["standards"], rules["house"]
    assert all(s["url"].startswith("https://") and s["title"] and s["version"] for s in standards.values())
    assert all(r["text"] for r in house.values())
    checked = {c["rule"] for c in json.loads((PLUGIN / "checks" / "index.json").read_text())["checks"]}
    assert checked <= set(house), f"checks bound to no house rule: {sorted(checked - set(house))}"
    cited = {c.partition(":")[0] for r in house.values() for c in r.get("cites", [])}
    assert cited <= set(standards), f"citations of unlisted standards: {sorted(cited - set(standards))}"
    assert not set(standards) & set(house)


def test_a_standard_section_id_takes_its_standards_line_and_a_house_rule_its_right_way(tmp_path):
    rows = bhrules.rule_rows(SimpleNamespace(data={}, dir=tmp_path))
    assert bhrules.rule_text(rows, "NIST-SP-800-53:SI-7").startswith("SI-7 of NIST SP 800-53 Security and Privacy Controls Rev. 5: https://")
    right = tomllib.loads((PLUGIN / "catalog" / "rules.toml").read_text())["house"]["RL-08"]["right"]
    assert bhrules.rule_text(rows, "RL-08") == f"{right} [S2]" and right.startswith("Use no timers")  # with its default severity (QBC-114)
    assert bhrules.rule_text(rows, "XX-99") == "" and bhrules.rule_text(rows, "NOPE:1") == ""
