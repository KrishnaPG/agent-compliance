"""d6: the generator's pieces and the bootstrap of the plugin's own rows (collected by the plain pytest entry)."""

import json
from pathlib import Path

import bhpacket
import bhtests
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "harness" / "acceptance" / "fixtures" / "packet" / "toy_item"


def packet(variant):
    return json.loads((FIXTURES / f"{variant}.json").read_text())


def test_the_rows_dir_is_the_fixed_prefix_of_the_first_acceptance_glob():
    p = packet("valid")
    assert bhtests.acceptance_dir(p) == "tests/acceptance"
    assert bhtests.rows_path(p) == "tests/acceptance/criteria/toy_item.yaml"


def test_a_keyword_the_library_has_but_cannot_read_the_when_is_not_implemented():
    row = packet("valid")["acceptance"][0]
    row = {
        **row,
        "then": [{"scan_count": {"op": "eq", "value": 0}}],
    }  # after: scan; the when is entry_point
    assert bhtests.unimplemented([row]) == {
        "toy_item-AC1": [("then after entry_point", "scan_count")]
    }
    assert bhtests.unimplemented(packet("valid")["acceptance"]) == {}


@pytest.mark.parametrize("variant", ["defect", "defect_found_by_reviewer"])
def test_a_defect_packet_names_its_parent_and_finder(variant):
    p = packet(variant)
    assert bhpacket.validate_packet(p) == []
    for field in ("parent", "found_by"):
        assert bhpacket.validate_packet({k: v for k, v in p.items() if k != field}), field


def test_a_slice_packet_carries_no_defect_fields():
    assert bhpacket.validate_packet({**packet("valid"), "parent": 1})


def test_a_row_outside_the_closed_catalog_is_refused_by_the_packet_schema():
    p = packet("valid")
    p["acceptance"][0]["when"] = {"no_such_keyword": {}}
    assert bhpacket.validate_packet(p)


def test_the_manifest_of_the_plugins_own_rows_is_what_pytest_collects():
    """The bootstrap: docs/atdd/criteria is collected as tests, and the committed manifest names each row's node id."""
    collected = bhtests.collect(ROOT, "docs/atdd/criteria")
    assert "a1-AC1" in collected and len(collected) == len(set(collected.values()))
    manifest = json.loads((ROOT / bhtests.MANIFEST).read_text())
    assert manifest == collected, "regenerate it: python harness/lib/bhtests.py bootstrap"
