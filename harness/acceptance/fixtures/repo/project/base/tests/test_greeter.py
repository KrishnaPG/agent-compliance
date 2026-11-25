import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from project.greeter import greet  # noqa: E402


def test_greet():
    assert greet("a") == "hello a"
