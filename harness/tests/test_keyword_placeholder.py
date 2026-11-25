"""A `$placeholder` inside a value is replaced by its text (catalog `placeholders`): a trailer value
such as `Packet: $packet.id@$packet_sha256` names the given packet."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import then  # noqa: E402


def test_a_placeholder_inside_a_value_is_replaced_by_its_text():
    ctx = SimpleNamespace(state={"packet": {"id": "toy_item", "sha256": "abc", "data": {"id": "toy_item", "acceptance": [{"id": "A1"}, {"id": "A2"}]}}})
    assert then.subst(ctx, "Packet: $packet.id@$packet_sha256") == "Packet: toy_item@abc"
    assert then.subst(ctx, "Acceptance: $acceptance_ids") == "Acceptance: A1, A2"
    assert then.subst(ctx, "$packet.id") == "toy_item"
