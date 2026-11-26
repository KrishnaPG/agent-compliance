import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest
from test_toy import toy  # noqa: E402, F401  (the toy project fixture, shared)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """Each test owns the program's and the model stub's environment inputs (hermetic tests, pytest
    monkeypatch): the BH_* and ATDD_* variables of the shell that started pytest are removed, so the
    suite gives one result wherever it runs, inside an acceptance row's environment included (the row's
    ATDD_MODEL_STATE counter would otherwise answer a test's stub launch with another launch's reply)."""
    for name in [n for n in os.environ if n.startswith(("BH_", "ATDD_"))]:
        monkeypatch.delenv(name)


@pytest.fixture(scope="session")
def suite_pin():
    """``suite_pin("pytest")`` is ``pytest==<version>`` as run_tests.py pins it, the one place the suite's packages
    are pinned: a toy project that needs a package asks for that exact pin, so provisioning (one run filling uv's
    cache) covers it and a row with no network finds it."""
    header = (ROOT / "run_tests.py").read_text()

    def pin(name):
        return re.search(rf"^#\s+\"({re.escape(name)}==[^\"]+)\"", header, re.M).group(1)

    return pin


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
