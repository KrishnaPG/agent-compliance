"""d2: the rendered packet carries the paved road's parts."""

import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import bhpacket  # noqa: E402

PACKET = LIB.parent / "acceptance" / "fixtures" / "packet" / "toy_item" / "valid.json"


def rendered():
    p = json.loads(PACKET.read_text())
    return p, bhpacket.render_markdown(p)


def test_the_packet_renders_the_acceptance_paths_targets_and_rule_messages():
    p, md = rendered()
    v = p["verifier"]
    assert all(x in md for x in v["acceptance_paths"])
    assert all(str(t["value"]) in md for t in v["targets"])
    assert all(r["message"] in md for r in v["rules"])


def test_the_packet_renders_the_cited_rule_and_decision_text():
    p, md = rendered()
    assert all(a["text"] in md for a in p["applies"])
    assert all(d["text"] in md for d in p["constraints"].get("decisions", []))


def test_the_paved_road_names_bh_check_the_test_paths_and_the_dependency_command():
    p, md = rendered()
    pr = p["paved_road"]
    assert pr["check_command"] in md and pr["dependency_command"] in md
    assert all(x in md for x in pr["test_paths"])
