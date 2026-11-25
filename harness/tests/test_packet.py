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


def test_only_planner_written_fields_count_toward_the_cap(tmp_path):
    p = fixture("valid")
    p["applies"][0]["text"] = "x" * 20000  # a program-filled field, far over the cap
    p["acceptance"][0]["scenario"] = "y" * 20000
    put(tmp_path, p)
    out = json.loads(bhpacket.step("assemble_packet", tmp_path, "toy_item")[1])
    assert out["facts"] == [] and bhpacket.planner_bytes(p) < bhpacket.packet_cap_bytes(tmp_path)


def test_the_planner_fields_are_the_ones_the_catalog_names():
    p = fixture("valid")
    want = [
        p["goal"],
        [a["id"] for a in p["applies"]],
        [d["id"] for d in p["constraints"].get("decisions", [])],
        p["constraints"]["declared_paths"],
    ]
    assert sorted(map(json.dumps, bhpacket.planner_values(p))) == sorted(
        map(json.dumps, [want[0], *want[1], *want[2], want[3]])
    )


def test_declared_paths_over_the_cap_are_a_fact_and_never_a_refusal(tmp_path):
    p = fixture("valid")
    p["constraints"]["declared_paths"] = [f"src/module_{i}/file.py" for i in range(300)]
    put(tmp_path, p)
    code, out, err = bhpacket.step("assemble_packet", tmp_path, "toy_item")
    assert code == 0 and err == "" and json.loads(out)["facts"][0]["kind"] == "over_cap"
    again = json.loads(bhpacket.step("assemble_packet", tmp_path, "toy_item")[1])
    assert again["facts"][0]["kind"] == "over_cap"  # still a fact, still no refusal
