"""d6: the packet's criteria, and the bootstrap of the plugin's own rows (collected by the plain pytest entry)."""

import json
from pathlib import Path

import bhpacket
import bhtests
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "harness" / "acceptance" / "fixtures" / "packet" / "toy_item"


def packet(variant):
    return json.loads((FIXTURES / f"{variant}.json").read_text())


@pytest.mark.parametrize("variant", ["defect", "defect_found_by_reviewer"])
def test_a_defect_packet_names_its_parent_and_finder(variant):
    p = packet(variant)
    assert bhpacket.validate_packet(p) == []
    for field in ("parent", "found_by"):
        assert bhpacket.validate_packet({k: v for k, v in p.items() if k != field}), field


def test_a_slice_packet_carries_no_defect_fields():
    assert bhpacket.validate_packet({**packet("valid"), "parent": 1})


def test_a_criterion_is_plain_a_keyword_row_part_is_refused_by_the_packet_schema():
    """A project's criteria are tested by plain tests in its own framework, never by catalog keywords."""
    p = packet("valid")
    p["acceptance"][0]["when"] = {"entry_point": {"entry": "plugin_pytest"}}
    assert bhpacket.validate_packet(p)


def test_the_manifest_of_the_plugins_own_rows_is_what_pytest_collects():
    """The bootstrap: docs/atdd/criteria is collected as tests, and the committed manifest names each row's node id."""
    collected = bhtests.collect(ROOT, "docs/atdd/criteria")
    assert "a1-AC1" in collected and len(collected) == len(set(collected.values()))
    manifest = json.loads((ROOT / bhtests.MANIFEST).read_text())
    assert manifest == collected, "regenerate it: python harness/lib/bhtests.py bootstrap"
