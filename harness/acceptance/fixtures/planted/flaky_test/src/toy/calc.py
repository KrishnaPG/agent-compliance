from pathlib import Path

_COUNT = Path(__file__).resolve().parents[2] / ".flaky_count"
_n = int(_COUNT.read_text()) if _COUNT.exists() else 0
_COUNT.write_text(str(_n + 1))
_FLAKY = _n % 2 == 0


def add(a, b):
    return a + b


def sub(a, b):
    return a - b if not _FLAKY else a + b
