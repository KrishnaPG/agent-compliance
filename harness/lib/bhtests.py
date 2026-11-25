"""The plugin's own acceptance rows as collected tests (keyword-driven testing, docs/spec/packet-standards.md L3).

The rows in ``docs/atdd/criteria`` are the plugin's tests: ``pytest`` collects them with the row plugin
``atdd_engine.plugin`` (OSS: pytest, PyYAML). ``bootstrap`` writes ``.brick-harness/manifest.json``
(criterion id to test node id, read back from ``pytest --collect-only``). A user project never uses this
module: its acceptance tests are plain tests in its own framework, written by the test author job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent
MANIFEST = ".brick-harness/manifest.json"


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
