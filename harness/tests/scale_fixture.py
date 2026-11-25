"""Fixture helper: a generated project with N change items, N-ready of them met at HEAD.

Used by the SG-15 bound on ``state`` (decision 0001): the tools read every item and the
state goes to a file, so the run time must not grow faster than linearly. Items own one path each and carry
the default test targets; the met ones have a scoreboard record at HEAD that the measurer's own staleness checks accept.

  python3 tests/scale_fixture.py DEST N [READY]    prints the config path

Pure local Python and git: it runs no test command and starts no container.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import bhcore  # noqa: E402

ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@example.invalid",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@example.invalid",
)


def _git(repo: Path, *a: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def make_project(dest: Path, n: int, ready: int = 5, limits: dict | None = None) -> Path:
    """Create the project under ``dest`` and return its config path."""
    dest.mkdir(parents=True, exist_ok=True)
    hd = dest / ".brick-harness"
    hd.mkdir()
    (dest / "src").mkdir()
    ids = [f"i{k:04d}" for k in range(n)]
    for i in ids:
        (dest / "src" / f"{i}.py").write_text(f'"""{i}"""\n')
    config = {
        "paths": {"lockfiles": []},
        "commands": {
            "test": {"run": "true", "junit": "{out}/junit.xml"},
            "timeout_s": 60,
        },
        "ecosystems": ["python"],
        "catalogue_jobs": ["testing"],
        "na": {},
        **({"limits": limits} if limits else {}),
    }
    (hd / "config.json").write_text(json.dumps(config, indent=1))
    (hd / "bricks.json").write_text(
        json.dumps(
            {
                "bricks": [
                    {
                        "id": i,
                        "job": f"change {i}",
                        "kind": "change",
                        "features": [f"F{k % 10}"],
                        "path": f"src/{i}.py",
                        "refs": [f"#{k + 1}"],
                    }
                    for k, i in enumerate(ids)
                ]
            }
        )
    )
    (hd / "targets.json").write_text(
        json.dumps(
            {
                "targets": [
                    t
                    for i in ids
                    for t in (
                        {"item": i, "metric": "tests.failed", "op": "==", "value": 0},
                        {"item": i, "metric": "tests.passed", "op": ">=", "value": 1},
                    )
                ]
            }
        )
    )
    (hd / ".gitignore").write_text("out/\n")
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-qm", "plan")
    head = _git(dest, "rev-parse", "HEAD")
    cfg = bhcore.Config(hd / "config.json")
    bricks, targets, _ = bhcore._load_plan(cfg, [])
    now = datetime.now(UTC).isoformat(timespec="microseconds")
    results = {
        b["id"]: {
            "status": "met",
            "ref": head,
            "measured_at": now,
            "metrics": {},
            "targets": [
                {
                    "metric": t["metric"],
                    "op": t["op"],
                    "value": t["value"],
                    "actual": 1,
                    "met": True,
                }
                for t in targets
                if t["item"] == b["id"]
            ],
            "targets_digest": bhcore.target_digest(cfg, b, targets),
            "errors": [],
            "runs": [],
        }
        for b in bricks[: n - ready]
    }
    bhcore.write_scoreboard(cfg, results)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-qm", "scoreboard")
    return hd / "config.json"


if __name__ == "__main__":
    out = make_project(
        Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 5
    )
    print(out)
