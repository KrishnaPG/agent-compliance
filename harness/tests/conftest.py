import importlib.util
import sys
from pathlib import Path

import pytest
from test_toy import toy  # noqa: E402, F401  (the toy project fixture, shared)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))


@pytest.fixture
def load_bin():
    return _load_bin


def _load_bin(name):
    """Import a bin/ script (no .py suffix) as a module."""
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader(name.replace("-", "_"), str(ROOT.parent / "bin" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
