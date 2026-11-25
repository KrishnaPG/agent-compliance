"""field: contains on a [*] path tests the one list of collected values; other ops test every element."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from support import apply_op, get_path  # noqa: E402

DOC = {"applies": [{"id": "G1"}, {"id": "P1"}]}


def test_contains_on_a_wildcard_path_is_one_list_membership():
    vals = get_path(DOC, "applies[*].id")
    assert apply_op("contains", vals, "P1", wildcard=True) is None
    assert apply_op("contains", vals, "P2", wildcard=True) is not None


def test_other_ops_still_hold_for_every_element():
    vals = get_path(DOC, "applies[*].id")
    assert apply_op("matches", vals, r"[GP]\d", wildcard=True) is None
    assert apply_op("eq", vals, "G1", wildcard=True) is not None


def test_contains_without_wildcard_is_unchanged():
    assert apply_op("contains", get_path({"a": ["x", "y"]}, "a"), "y") is None
