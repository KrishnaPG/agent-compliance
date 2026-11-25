"""b9: the builder's clone and its cheap restrictions.

OSS and host used, nothing else: ``git clone --shared`` (objects stay in the source and are
immutable; refs are the clone's own), and Claude Code's own settings schema (``permissions``
and ``sandbox``) in a file passed with ``claude --settings``. This module is configuration and
glue: it names the paths to protect and writes them in that schema; the sandbox and the file
tools enforce them.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

SETTINGS_FILE = ".brick-harness/builder-settings.json"
PROGRAM = "bh"  # the program's git identity: the builder never commits
SG01 = "SG-01"  # the spec line for a protected acceptance test (packet-standards.md, L4)

# Where the program keeps what a builder must not change, under the source repository.
_STATE = ("custody", "packets", "out", "hook-facts", "run-report.txt", "config.json", "builder-settings.json")


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    p = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    if p.returncode:
        raise RuntimeError(f"git {args[0]} failed in {cwd}: {p.stderr.strip()[:200]}")
    return p.stdout.strip()


def make_clone(root: Path, clone: Path, base: str) -> None:
    """A shared clone at the base commit the program recorded: no remote is left to fetch from, and
    nothing the builder does to its refs reaches the source's."""
    if clone.exists():
        return
    _git(root, "clone", "-q", "--shared", "--no-checkout", str(root), str(clone))
    _git(clone, "remote", "remove", "origin")
    _git(clone, "checkout", "-q", "--detach", base)


def protected_paths(packet: dict[str, Any], root: Path, clone: Path, plugin_root: Path) -> list[str]:
    """The paths the sandbox makes read-only: the clone's acceptance tests and packet files, then the
    source repository, the orchestrator's directory and the plugin root. The clone itself sits under
    the source repository's state directory, so the source's own ``.brick-harness`` entries are
    listed one by one, never the directory."""
    tests = [str(clone / p.split("*", 1)[0].rstrip("/")) for p in packet.get("verifier", {}).get("acceptance_paths", [])]
    packets = [str(clone / ".brick-harness" / "packets")]
    orch = os.environ.get("BH_ORCHESTRATOR_DIR")
    out = [*tests, *packets, str(root / ".git"), *(str(root / ".brick-harness" / s) for s in _STATE)]
    if orch:
        out.append(orch)
    out.append(str(plugin_root))
    return list(dict.fromkeys(out))


def builder_settings(
    packet: dict[str, Any], root: Path, clone: Path, plugin_root: Path, sandbox: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Claude Code settings for one builder. File tools are scoped to the working directory; Bash is
    allowed only through the sandbox (never pre-approved, never unsandboxed); the sandbox is
    read-only on the protected paths and has no ``denyRead``. The config's ``sandbox`` object is
    merged in verbatim (its own keys win)."""
    sb: dict[str, Any] = {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "filesystem": {
            "allowWrite": [str(clone)],
            "denyWrite": protected_paths(packet, root, clone, plugin_root),
        },
        "network": {"allowAllUnixSockets": False},
    }
    for k, v in (sandbox or {}).items():
        if isinstance(v, dict) and isinstance(sb.get(k), dict):
            sb[k] = {**sb[k], **v}
        else:
            sb[k] = v
    return {
        "permissions": {
            "allow": ["Edit(*)", "Write(*)"],
            "deny": [],
            "blockReadsOutsideWorkingDirectories": True,
        },
        "sandbox": sb,
    }


def write_settings(root: Path, settings: dict[str, Any]) -> Path:
    from bhorch import write_atomic

    path = root / SETTINGS_FILE
    write_atomic(path, json.dumps(settings, indent=2) + "\n")
    return path


def commit_message(packet: dict[str, Any], digest: str) -> str:
    """Conventional Commits 1.0: the subject names the item, the trailers carry the packet identity
    and the acceptance ids the change answers."""
    goal = " ".join(str(packet.get("goal", "")).split())[:60] or "build"
    ids = ", ".join(a["id"] for a in packet.get("acceptance", []))
    return f"feat({packet['id']}): {goal}\n\nPacket: {packet['id']}@{digest}\nAcceptance: {ids}\n"


def commit_build(clone: Path, packet: dict[str, Any], digest: str) -> str:
    """The program stages and commits the builder's change as itself; the builder holds no commit.
    The program's own state in the clone is not part of the change. Returns the commit, or the base
    when the builder changed nothing."""
    env = {
        "GIT_AUTHOR_NAME": PROGRAM,
        "GIT_AUTHOR_EMAIL": f"{PROGRAM}@localhost",
        "GIT_COMMITTER_NAME": PROGRAM,
        "GIT_COMMITTER_EMAIL": f"{PROGRAM}@localhost",
    }
    _git(clone, "add", "-A", "--", ".", ":(exclude).brick-harness", env=env)
    if subprocess.run(["git", "-C", str(clone), "diff", "--cached", "--quiet"]).returncode:
        _git(clone, "commit", "-q", "-m", commit_message(packet, digest), env=env)
    return _git(clone, "rev-parse", "HEAD")
