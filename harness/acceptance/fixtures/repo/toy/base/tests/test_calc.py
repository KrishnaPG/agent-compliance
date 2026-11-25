import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from toy.calc import add, sub  # noqa: E402


def test_add():
    assert add(2, 3) == 5


def test_sub():
    assert sub(5, 3) == 2
