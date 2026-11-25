"""catalog/rules.toml (R9, QBC-85): standards by reference plus house rules; every check's rule resolves to one."""

import json
import tomllib
from pathlib import Path

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
