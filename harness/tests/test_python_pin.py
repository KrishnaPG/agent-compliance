"""One interpreter and one set of pinned packages for every plugin entry point (bin scripts, hooks,
the harness tests and acceptance runs): each declares them in its PEP 723 header, and they all agree
with `.python-version`. A header that drifts is a machine that runs another Python."""

import json
import re
import tomllib
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
SCRIPTS = [
    *sorted(p for p in (PLUGIN / "bin").iterdir() if p.is_file() and p.suffix != ".lock"),
    *sorted((PLUGIN / "hooks").glob("*.py")),
    PLUGIN / "harness" / "run_tests.py",
]
SCRIPTS = [p for p in SCRIPTS if p.name != "_common.py"]  # imported by the hooks, never run alone
SHEBANG = "#!/usr/bin/env -S uv run --script --managed-python\n"


def header(path: Path) -> dict:
    m = re.search(r"^# /// script\n((?:#.*\n)+?)# ///\n", path.read_text(), re.M)
    assert m, f"{path.name} has no PEP 723 header"
    return tomllib.loads("".join(line[2:] if line.startswith("# ") else line[1:] for line in m.group(1).splitlines(True)))


def pinned() -> str:
    return (PLUGIN / ".python-version").read_text().strip()


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_every_entry_point_pins_the_interpreter_and_its_packages(path):
    assert path.read_text().startswith(SHEBANG)
    meta = header(path)
    assert meta["requires-python"] == f"=={pinned()}.*"
    for dep in meta["dependencies"]:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][^=<>~!]*", dep), f"{dep} is not an exact pin"


def test_a_package_has_one_version_across_the_headers():
    seen: dict[str, set[str]] = {}
    for path in SCRIPTS:
        for dep in header(path)["dependencies"]:
            name, version = dep.split("==")
            seen.setdefault(name.lower(), set()).add(version)
    assert {n: v for n, v in seen.items() if len(v) > 1} == {}


def test_hooks_run_through_uv_with_the_managed_interpreter():
    commands = [
        h["command"]
        for groups in json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"].values()
        for g in groups
        for h in g["hooks"]
    ]
    assert commands
    assert all(c.startswith("uv run --script --managed-python ") for c in commands)


@pytest.mark.parametrize("path", [p for p in SCRIPTS if header(p)["dependencies"]], ids=lambda p: p.name)
def test_a_script_with_packages_has_its_lock(path):
    lock = path.with_name(path.name + ".lock")
    assert lock.is_file(), f"uv lock --script {path.name}"
    locked = tomllib.loads(lock.read_text())
    assert locked["requires-python"] == f"=={pinned()}.*"
