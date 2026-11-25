"""d0: the packet schema, its teaching refusals, the size cap and the rendering."""

import copy
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB.parent / "acceptance" / "keywords"))
pytest.importorskip("jsonschema")
import bhpacket  # noqa: E402

FIXTURES = LIB.parent / "acceptance" / "fixtures" / "packet" / "toy_item"


def fixture(variant):
    return json.loads((FIXTURES / f"{variant}.json").read_text())


def put(root, packet):
    d = root / bhpacket.PACKETS_DIR
    d.mkdir(parents=True)
    (d / f"{packet['id']}.json").write_text(json.dumps(packet))


@pytest.mark.parametrize("variant", ["valid", "mechanical", "config_change", "over_cap"])
def test_a_valid_fixture_has_no_errors(variant):
    assert bhpacket.validate_packet(fixture(variant)) == []


@pytest.mark.parametrize(
    ("variant", "wrong"),
    [
        ("design_field", "design field"),
        ("scenario_without_traces_to", "without traces_to"),
        ("scenario_without_verification", "without a valid verification"),
    ],
)
def test_a_refused_packet_teaches(variant, wrong):
    msgs = [bhpacket.teaching(e) for e in bhpacket.validate_packet(fixture(variant))]
    assert len(msgs) == 1 and wrong in msgs[0] and " -> " in msgs[0] and len(msgs[0]) <= 300


def test_a_verification_outside_the_closed_four_is_refused():
    p = fixture("valid")
    p["acceptance"][0]["verification"] = "review"
    assert bhpacket.validate_packet(p)


def test_a_goal_over_the_cap_moves_to_a_file_and_is_a_fact(tmp_path):
    put(tmp_path, fixture("over_cap"))
    code, out, _ = bhpacket.step("assemble_packet", tmp_path, "toy_item")
    assert code == 0 and json.loads(out)["facts"][0]["kind"] == "over_cap"
    p = json.loads(bhpacket.packet_path(tmp_path, "toy_item").read_text())
    assert (tmp_path / p["overflow"][0]["path"]).is_file() and bhpacket.validate_packet(p) == []
    assert (
        json.loads(bhpacket.step("assemble_packet", tmp_path, "toy_item")[1])["facts"] == []
    )  # now under the cap


def test_the_cap_is_a_project_override(tmp_path):
    put(tmp_path, fixture("valid"))
    (tmp_path / ".brick-harness" / "config.json").write_text('{"sizing": {"packet_tokens": 1}}')
    assert (
        json.loads(bhpacket.step("assemble_packet", tmp_path, "toy_item")[1])["facts"][0]["kind"]
        == "over_cap"
    )


def test_rendering_is_stable_and_refuses_an_invalid_packet(tmp_path):
    put(tmp_path, fixture("valid"))
    assert bhpacket.step("render_packet", tmp_path, "toy_item") == bhpacket.step(
        "render_packet", tmp_path, "toy_item"
    )
    bad = copy.deepcopy(fixture("valid"))
    bad["design"] = "x"
    (tmp_path / bhpacket.PACKETS_DIR / "toy_item.json").write_text(json.dumps(bad))
    assert bhpacket.step("render_packet", tmp_path, "toy_item")[0] == 1
