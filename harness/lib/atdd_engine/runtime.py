"""Run-time side of a row test: the context a row's steps share, and the three outcomes.

Missing (an AssertionError) = the system under test lacks something: the test is red.
FixtureError, KeywordError = the test cannot be run as written: the test is an error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .teaching import teach


class Missing(AssertionError):
    """The system under test has no such command, subcommand, file, field or fact."""


class FixtureError(Exception):
    """A fixture the row names does not exist or is malformed."""


class KeywordError(Exception):
    """A catalog key has no implementation in the keyword library (or it was refused as ambiguous)."""


def say(rule: str, wrong: str, right: str, ref: str) -> str:
    return teach(rule, wrong, right, ref)


class Ctx:
    """Shared by the steps of one row. `state` is the keyword library's own scratch space."""

    def __init__(self, library, tree: Path, work: Path, fixtures: Path, row_id: str):
        self.lib, self.tree, self.work, self.fixtures, self.row_id = library, tree, work, fixtures, row_id
        self.state: dict = {}
        self.last = None  # what the `when` step returned
        self.finalizers: list = []

    def _call(self, kind: str, key: str, params: dict):
        table = getattr(self.lib, kind.upper())
        fn = table.get(key)
        if fn is None:
            raise KeywordError(say("ATDD-KEYWORD", f"the {kind} key {key} has no implementation", f"implement {kind}.{key} in the keyword library", "docs/atdd/catalog.yaml"))
        return fn(self, **params)

    def given(self, key: str, params: dict) -> None:
        self._call("given", key, params)

    def when(self, key: str, params: dict) -> None:
        pre = getattr(self.lib, "BEFORE_WHEN", None)
        if pre:
            pre(self)
        self.last = self._call("when", key, params)

    def then(self, key: str, params: dict) -> None:
        self._call("then", key, params)

    def close(self) -> None:
        for f in reversed(self.finalizers):
            f()


def load_library(path: Path):
    """Import a keyword-library package from a directory holding __init__.py."""
    path = Path(path).resolve()
    name = "atdd_library_" + path.name
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
