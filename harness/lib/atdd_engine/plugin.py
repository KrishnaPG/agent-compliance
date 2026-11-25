"""pytest side of the generated tests: the --tree option, the `ctx` fixture, JUnit properties, error versus failure."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .runtime import Ctx, FixtureError, load_library
from .teaching import teach


def pytest_addoption(parser):
    parser.addoption("--tree", default=os.environ.get("ATDD_TREE"), help="the plugin tree under test (or env ATDD_TREE)")


def pytest_configure(config):
    config.addinivalue_line("markers", "criterion(id): the acceptance row this test is generated from")


def make_ctx(request, tmp_path, record_property, library_dir, fixtures_dir):
    marker = request.node.get_closest_marker("criterion")
    row_id = marker.args[0] if marker else request.node.name
    record_property("criterion", row_id)  # JUnit: <property name="criterion" value="a1-AC1"/>
    tree = request.config.getoption("--tree")
    if not tree or not Path(tree).is_dir():
        raise FixtureError(teach("ATDD-TREE", "no tree under test was given", "pass --tree <plugin checkout> or set ATDD_TREE", "docs/spec/packet-standards.md L3"))
    ctx = Ctx(load_library(library_dir), Path(tree).resolve(), tmp_path, Path(fixtures_dir), row_id)
    try:
        yield ctx
    finally:
        ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """An AssertionError is red (a failure). Any other exception means the test could not run: report an error."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and call.excinfo is not None and not isinstance(call.excinfo.value, AssertionError):
        rep.when = "setup"  # JUnit XML and the summary then say error, not failure
