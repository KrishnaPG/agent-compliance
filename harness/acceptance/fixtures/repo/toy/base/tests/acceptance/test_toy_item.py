import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from toy.calc import add  # noqa: E402


def test_toy_item_AC1():
    assert add(1, 1) == 2
