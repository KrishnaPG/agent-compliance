"""output_contains: the catalog's string type matches output as a case-insensitive substring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import then  # noqa: E402


def test_norm_ignores_case_and_whitespace():
    assert then._norm("goal") in then._norm("## Goal\n\nShip   it")
    assert then._norm("SHIP IT") in then._norm("ship\n it")
