"""d6: L3 tests, the program's side of "the test author goes first".

The test author (an agent job) writes a packet's acceptance rows from the closed catalog. Nothing here writes test
code: the rows are the tests. ``pytest`` collects them with the row plugin ``atdd_engine.plugin`` (OSS: pytest,
PyYAML; keyword-driven testing, docs/spec/packet-standards.md L3). This module is configuration and glue:

- ``generate``: the ``generate_tests`` program step. It copies the packet's rows to ``<acceptance path>/criteria/<item>.yaml``
  (the directory name the plugin collects), writes ``.brick-harness/manifest.json`` (criterion id to test node id, read
  back from ``pytest --collect-only``, never composed by hand) and commits both, the plan commit.
- ``run_rows``: the red-on-main run, JUnit XML in ``.brick-harness/junit.xml``; an assertion failure is ``red``, an
  error is ``red_by_error`` (the row goes back to the test author).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from atdd_engine import report
from atdd_engine.runtime import load_library
from atdd_engine.teaching import teach

LIB = Path(__file__).resolve().parent
KEYWORDS = LIB.parent / "acceptance" / "keywords"
CATALOG = LIB.parents[1] / "docs" / "atdd" / "catalog.yaml"
CRITERIA_DIR = "criteria"  # the plugin collects rows only from a directory of this name
MANIFEST = ".brick-harness/manifest.json"
JUNIT = ".brick-harness/junit.xml"
SPEC = "docs/spec/packet-standards.md"
GLOB_CHARS = re.compile(r"[*?\[]")


def acceptance_dir(packet: dict[str, Any]) -> str:
    """The protected directory of the packet's rows: the fixed prefix of its first ``verifier.acceptance_paths`` glob."""
    glob = packet["verifier"]["acceptance_paths"][0]
    parts = []
    for part in Path(glob).parts:
        if GLOB_CHARS.search(part):
            break
        parts.append(part)
    base = Path(*parts) if parts else Path(".")
    return str(base if base.suffix == "" else base.parent)


def rows_path(packet: dict[str, Any]) -> str:
    return f"{acceptance_dir(packet)}/{CRITERIA_DIR}/{packet['id']}.yaml"


def pytest_argv(root: Path, target: str, *extra: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "atdd_engine.plugin",
        target,
        "--tree",
        str(root),
        "-p",
        "no:cacheprovider",
        "-q",
        *extra,
    ]


def pytest_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [str(LIB), os.environ.get("PYTHONPATH", "")])),
    }


def collect(root: Path, target: str) -> dict[str, str]:
    """Criterion id -> test node id of every row ``pytest --collect-only`` finds under ``target``."""
    p = subprocess.run(
        pytest_argv(root, target, "--collect-only"),
        cwd=root,
        env=pytest_env(),
        capture_output=True,
        text=True,
    )
    nodes = [ln.strip() for ln in p.stdout.splitlines() if "::" in ln and not ln.startswith(" ")]
    if p.returncode not in (0, 5):  # 5: nothing collected
        raise RuntimeError(f"pytest could not collect {target}: {(p.stdout + p.stderr)[-400:]}")
    return {n.rsplit("::", 1)[1]: n for n in nodes}


def unimplemented(rows: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """Row id -> the (part, keyword) pairs of the row that the keyword library does not implement (or that it names ambiguous)."""
    lib = load_library(KEYWORDS)
    tables = {"given": lib.GIVEN, "when": lib.WHEN, "then": lib.THEN}
    ambiguous = getattr(lib, "AMBIGUOUS", None)
    catalog = yaml.safe_load(CATALOG.read_text())
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        steps = [("given", k, v) for g in r["given"] for k, v in g.items()] + [
            ("when", k, v) for k, v in r["when"].items()
        ]
        steps += [("then", k, v) for t in r["then"] for k, v in t.items()]
        bad = [
            (kind, k)
            for kind, k, v in steps
            if k not in tables[kind]
            or k == "needs_keyword"
            or (ambiguous and ambiguous(kind, k, v or {}))
        ]
        when = next(
            iter(r["when"])
        )  # a then-keyword reads the result of the when-keywords its `after` names
        for t in r["then"]:
            for k in t:
                after = catalog["then"].get(k, {}).get("after")
                if k in tables["then"] and after and when not in after:
                    bad.append((f"then after {when}", k))
        if bad:
            out[r["id"]] = bad
    return out


def committed_rows(root: Path, packet: dict[str, Any]) -> dict[str, str]:
    """Row id -> file of the rows already in the acceptance directory (every file of it, the item's own or not)."""
    out: dict[str, str] = {}
    for f in sorted((root / acceptance_dir(packet) / CRITERIA_DIR).glob("*.yaml")):
        for r in (yaml.safe_load(f.read_text()) or {}).get("acceptance", []):
            out[r["id"]] = f.name
    return out


def drift_facts(root: Path, packet: dict[str, Any]) -> list[dict[str, str]]:
    """Facts for rows and packet that disagree before this generation: a test without a criterion, a criterion without one."""
    have = committed_rows(root, packet)
    ids = {r["id"] for r in packet["acceptance"]}
    facts = []
    for rid, f in sorted(have.items()):
        if rid not in ids:
            facts.append(
                {
                    "kind": "gap",
                    "item": packet["id"],
                    "detail": teach(
                        "tests-without-criterion",
                        f"test without a criterion: {rid} in {f}",
                        "tests are generated from the packet's rows, one per criterion",
                        "regenerate the tests from the packet instead of writing them by hand",
                    ),
                }
            )
    if (
        root / rows_path(packet)
    ).is_file():  # an earlier generation: its tests should be the packet's
        for rid in sorted(ids - set(have)):
            facts.append(
                {
                    "kind": "gap",
                    "item": packet["id"],
                    "detail": teach(
                        "criterion-without-test",
                        f"criterion without a test: {rid} is in the packet only",
                        "tests are generated from the packet's rows, one per criterion",
                        "regenerate the tests from the packet instead of writing them by hand",
                    ),
                }
            )
    return facts


def generate(root: Path, packet: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, str]]:
    """The generate_tests step: facts, and the manifest entries of this item. Rows whose keyword is not implemented stay out."""
    from bhorch import git, write_atomic

    facts = drift_facts(root, packet)
    bad = unimplemented(packet["acceptance"])
    for rid, kws in sorted(bad.items()):
        kind, k = kws[0]
        facts.append(
            {
                "kind": "gap",
                "item": packet["id"],
                "detail": teach(
                    "keyword-not-implemented",
                    f"the generator does not implement the keyword {k} as a {kind} (row {rid})",
                    f"implement {k} in the generator or change the row's keyword",
                    "add the keyword's implementation before the row enters the packet",
                ),
            }
        )
    rows = [r for r in packet["acceptance"] if r["id"] not in bad]
    path = rows_path(packet)
    write_atomic(
        root / path,
        yaml.safe_dump({"item": packet["id"], "acceptance": rows}, sort_keys=False, width=100),
    )
    nodes = collect(root, path) if rows else {}
    mf = root / MANIFEST
    manifest = json.loads(mf.read_text()) if mf.is_file() else {}
    manifest = {k: v for k, v in manifest.items() if not k.startswith(f"{packet['id']}-")} | nodes
    write_atomic(mf, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    git(root, "add", "-f", path, MANIFEST)
    if git(root, "diff", "--cached", "--quiet", check=False).returncode:
        git(
            root,
            "-c",
            "user.name=bh",
            "-c",
            "user.email=bh@localhost",
            "commit",
            "-q",
            "-m",
            f"plan({packet['id']}): acceptance rows and manifest, generated from the packet",
        )
    return facts, nodes


def run_rows(root: Path, packet: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Run the item's rows; row id -> {outcome: green|red|error|skipped|absent, message}. JUnit XML is left in JUNIT."""
    path = rows_path(packet)
    junit = root / JUNIT
    junit.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        pytest_argv(root, path, f"--junitxml={junit}"),
        cwd=root,
        env=pytest_env(),
        capture_output=True,
        text=True,
    )
    out = report.outcomes(junit, root / acceptance_dir(packet) / CRITERIA_DIR)
    own = {r["id"] for r in yaml.safe_load((root / path).read_text())["acceptance"]}
    return {k: v for k, v in out.items() if k in own}


def red_facts(
    packet: dict[str, Any], outcomes: dict[str, dict[str, str]], head: str
) -> list[dict[str, str]]:
    """Facts of the red-on-main run. For a defect, a red row is the regression recorded at the parent commit."""
    facts = []
    for rid, o in sorted(outcomes.items()):
        base = {"item": packet["id"]}
        if o["outcome"] == "red":
            facts.append(
                {
                    **base,
                    "kind": "red",
                    "detail": f"{rid} fails on main by an assertion: {o['message']}"[:300],
                }
            )
            if packet.get("kind") == "defect":
                facts.append(
                    {
                        **base,
                        "kind": "regression_recorded",
                        "detail": f"parent: {rid} fails at {head[:12]}",
                    }
                )
        elif o["outcome"] == "error":
            facts.append(
                {
                    **base,
                    "kind": "red_by_error",
                    "detail": f"{rid} errored on main instead of failing by an assertion: {o['message']}"[
                        :300
                    ],
                }
            )
        elif o["outcome"] in ("green", "skipped", "absent"):
            facts.append(
                {
                    **base,
                    "kind": "gap",
                    "detail": teach(
                        "row-not-red",
                        f"row {rid} is {o['outcome']} on main",
                        "write the row so that it fails by an assertion while the goal is unmet",
                        "run the row against the project before it enters the packet",
                    ),
                }
            )
    return facts


def bootstrap(root: Path) -> dict[str, str]:
    """The plugin's own v2 rows (docs/atdd/criteria) as collected tests: write their manifest (criterion id -> node id)."""
    from bhorch import write_atomic

    manifest = collect(root, "docs/atdd/criteria")
    write_atomic(root / MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":  # python harness/lib/bhtests.py bootstrap
    if sys.argv[1:] != ["bootstrap"]:
        sys.exit(
            "usage: bhtests.py bootstrap  (regenerate .brick-harness/manifest.json from docs/atdd/criteria)"
        )
    print(f"{len(bootstrap(Path.cwd()))} rows in {MANIFEST}")
