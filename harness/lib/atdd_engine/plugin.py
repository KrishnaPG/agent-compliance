"""pytest plugin: collects the criteria rows (docs/atdd/criteria/*.yaml) directly, one test per row.

Use: `pytest -p atdd_engine.plugin docs/atdd/criteria --tree <plugin checkout>`. The node id carries the row id
(`a.yaml::a1-AC1`) and each test records it as the JUnit property `criterion`. An AssertionError is red (a failure);
any other exception means the test could not run and is reported as an error.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from syrupy.extensions.single_file import SingleFileSnapshotExtension

from .runtime import Ctx, FixtureError, load_library
from .teaching import teach

_ACCEPTANCE = Path(__file__).resolve().parents[2] / "acceptance"


def pytest_addoption(parser):
    parser.addoption("--tree", default=os.environ.get("ATDD_TREE"), help="the plugin tree under test (or env ATDD_TREE)")
    parser.addoption("--atdd-keywords", default=str(_ACCEPTANCE / "keywords"), help="the keyword library directory")
    parser.addoption("--atdd-fixtures", default=str(_ACCEPTANCE / "fixtures"), help="the fixtures directory")


def pytest_collect_file(file_path: Path, parent):
    if file_path.suffix == ".yaml" and file_path.parent.name == "criteria":
        return RowFile.from_parent(parent, path=file_path)


def _steps(row: dict):
    for g in row.get("given", []):
        for k, v in g.items():
            yield "given", k, v or {}
    for k, v in row["when"].items():
        yield "when", k, v or {}
    for t in row.get("then", []):
        for k, v in t.items():
            yield "then", k, v or {}


class RowFile(pytest.File):
    def collect(self):
        library = load_library(Path(self.config.getoption("--atdd-keywords")))
        ambiguous = getattr(library, "AMBIGUOUS", None)
        for row in yaml.safe_load(self.path.read_text())["acceptance"]:
            item = pytest.Function.from_parent(self, name=row["id"], callobj=_run_row)
            item.row = row
            item.user_properties.append(("criterion", row["id"]))  # JUnit: <property name="criterion" value="a1-AC1"/>
            for kind, key, params in _steps(row):
                why = ("needs_keyword: " + str(params.get("reason", ""))) if key == "needs_keyword" else ambiguous and ambiguous(kind, key, params)
                if why:
                    item.add_marker(pytest.mark.skip(reason=f"not runnable: {why}"))
                    break
            yield item


def _run_row(ctx):
    for kind, key, params in _steps(ctx.row):
        getattr(ctx, kind)(key, params)


@pytest.fixture
def ctx(request, tmp_path, row_snapshot):
    tree = request.config.getoption("--tree")
    if not tree or not Path(tree).is_dir():
        raise FixtureError(teach("ATDD-TREE", "no tree under test was given", "pass --tree <plugin checkout> or set ATDD_TREE", "docs/spec/packet-standards.md L3"))
    row = request.node.row
    c = Ctx(load_library(Path(request.config.getoption("--atdd-keywords"))), Path(tree).resolve(), tmp_path, Path(request.config.getoption("--atdd-fixtures")).resolve(), row["id"])
    c.row, c.snapshot = row, row_snapshot
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def row_snapshot(request, snapshot):
    """syrupy's approved-output check, one raw file per row and name in <fixtures>/snapshots/<slice>; never recorded unless `--snapshot-update` is passed."""
    where = str(Path(request.config.getoption("--atdd-fixtures")).resolve() / "snapshots")

    class Raw(SingleFileSnapshotExtension):
        file_extension = "txt"

        @classmethod
        def dirname(cls, *, test_location):
            return str(Path(where) / test_location.basename)

    return snapshot.use_extension(Raw)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """An AssertionError is red (a failure). Any other exception means the test could not run: report an error."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and call.excinfo is not None and not isinstance(call.excinfo.value, AssertionError):
        rep.when = "setup"  # JUnit XML and the summary then say error, not failure
