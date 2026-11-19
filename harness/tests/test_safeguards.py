"""safeguards.json is the harness's register of pitfalls; this keeps it honest.

No gates: an item moves on only when its targets are measured met. A mechanism of kind gate
may exist only while it is being removed. An entry marked implemented or partial must name
tests that exist, and an implemented entry has nothing left to build or remove.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = json.loads((ROOT / "safeguards.json").read_text())["safeguards"]
ENTRY = {"implemented", "partial", "planned", "deciding"}
MECH = {"implemented", "planned", "deciding", "to-remove"}
KINDS = {"structure", "fact", "order", "limit", "decision", "gate"}
TEST_NAMES = {
    m
    for p in (ROOT / "tests").glob("test_*.py")
    for m in re.findall(r"^def (test_\w+)", p.read_text(), re.M)
}


def test_entries_are_well_formed_and_ids_unique():
    ids = [e["id"] for e in REG]
    assert len(ids) == len(set(ids))
    for e in REG:
        assert re.fullmatch(r"SG-\d\d", e["id"]), e["id"]
        assert e["status"] in ENTRY, e["id"]
        assert e["risk"] and e["mechanism"], e["id"]
        for c in e["catalog"]:
            assert re.fullmatch(r"[A-Z]{2}-\d\d", c), (e["id"], c)
        for m in e["mechanism"]:
            assert m["kind"] in KINDS and m["status"] in MECH, e["id"]
            assert m["where"] and m["does"], e["id"]


def test_no_gates_except_ones_being_removed():
    for e in REG:
        for m in e["mechanism"]:
            assert (m["kind"] == "gate") == (m["status"] == "to-remove"), (e["id"], m["does"])


def test_status_follows_its_mechanisms_and_tests():
    for e in REG:
        states = {m["status"] for m in e["mechanism"]}
        missing = [t for t in e["tests"] if t not in TEST_NAMES]
        assert not missing, (e["id"], missing)
        built = states & {"implemented", "to-remove"}
        if e["status"] == "implemented":
            assert states == {"implemented"} and e["tests"], e["id"]
        if e["status"] == "partial":
            assert built and states != {"implemented"} and e["tests"], e["id"]
        if e["status"] in ("planned", "deciding"):
            assert not built, e["id"]
