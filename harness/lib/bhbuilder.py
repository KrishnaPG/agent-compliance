"""b9: the builder's clone and its cheap restrictions.

OSS and host used, nothing else: ``git clone --shared`` (objects stay in the source and are
immutable; refs are the clone's own), and Claude Code's own settings schema (``permissions``
and ``sandbox``) in a file passed with ``claude --settings``. This module is configuration and
glue: it names the paths to protect and writes them in that schema; the sandbox and the file
tools enforce them.

R10 (host caveat): before a builder starts, ``probe_host`` runs one command through a bubblewrap
sandbox built from the same settings the builder gets, and reads the builder account's groups with
``id -nG``. Nothing else is used. A failed probe or a listed group is an order refusal with its
teaching text; ``allowAllUnixSockets`` is set only when the probe passes with it and fails without.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

LAUNCH_DIR = ".brick-harness/launch"  # one settings file per builder launch, named by its clone
PROGRAM = "bh"  # the program's git identity: the builder never commits
SG01 = "SG-01"  # the spec line for a protected acceptance test (packet-standards.md, L4)

# Where the program keeps what a builder must not change, under the source repository.
_STATE = ("custody", "packets", "out", "hook-facts", "run-report.txt", "config.json", "launch")


# Launch policy defaults (P8): the config's ``launch`` object overrides any key.
LAUNCH_DEFAULTS: dict[str, Any] = {
    "refuse_groups": ["docker"],  # a builder in one of these groups can reach the host through it
    "probe": ["sh", "-c", ": > .brick-harness/probe-ok"],  # what the sandboxed builder must manage to do
    "unix_socket_paths": [],  # host sockets the project's builder needs
    "unix_socket_probe": [],  # a command that needs those sockets; empty: none is needed
}
PROBE_RULE = "sandbox-probe"


def launch_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    return {**LAUNCH_DEFAULTS, **((config or {}).get("launch") or {})}


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    p = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    if p.returncode:
        raise RuntimeError(f"git {args[0]} failed in {cwd}: {p.stderr.strip()[:200]}")
    return p.stdout.strip()


def make_clone(root: Path, clone: Path, base: str) -> None:
    """A shared clone at the base commit the program recorded: no remote is left to fetch from, and
    nothing the builder does to its refs reaches the source's. The base commit holds the packet of
    every item planned so far; the clone checks out none of them (git sparse-checkout), so the one
    packet in it is the one ``register`` puts there, the packet the hooks deliver and scope by."""
    from bhpacket import PACKETS_DIR

    if clone.exists():
        return
    _git(root, "clone", "-q", "--shared", "--no-checkout", str(root), str(clone))
    _git(clone, "remote", "remove", "origin")
    _git(clone, "sparse-checkout", "set", "--no-cone", "/*", f"!/{PACKETS_DIR}/")
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


def _bwrap(settings: dict[str, Any], clone: Path, hidden: list[str]) -> list[str]:
    """The bubblewrap command line of the sandbox these settings describe: the filesystem
    read-only, ``allowWrite`` paths writable, ``denyWrite`` paths read-only again, no network and no
    shared IPC. ``hidden`` paths (host sockets) are replaced by /dev/null."""
    fs = settings["sandbox"]["filesystem"]
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-net", "--unshare-ipc", "--die-with-parent"]
    for p in fs["allowWrite"]:
        argv += ["--bind", p, p]
    for p in fs["denyWrite"]:
        if os.path.exists(p):
            argv += ["--ro-bind", p, p]
    for p in hidden:
        if os.path.exists(p):
            argv += ["--bind", "/dev/null", p]
    return [*argv, "--chdir", str(clone)]


def _passes(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, capture_output=True).returncode == 0
    except OSError:
        return False


def probe_host(
    settings: dict[str, Any], clone: Path, policy: dict[str, Any], groups: list[str] | None = None
) -> tuple[list[dict[str, str]], str]:
    """(facts, refusal). The refusal is a teaching line for an order refusal (P4, P5), empty when
    the builder may start; ``settings`` gets ``allowAllUnixSockets`` set only when the socket probe
    passes with the sockets visible and fails with them hidden, and that choice is a fact."""
    if groups is None:
        groups = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    bad = sorted(set(groups) & set(policy["refuse_groups"]))
    if bad:
        return [], (
            f"[{PROBE_RULE}] the builder account is in group {', '.join(bad)}, which reaches the host outside the sandbox "
            "-> launch builders from an account outside launch.refuse_groups . docs/spec/packet-standards.md"
        )
    (clone / ".brick-harness").mkdir(parents=True, exist_ok=True)
    if not _passes([*_bwrap(settings, clone, []), *policy["probe"]]):
        return [], (
            f"[{PROBE_RULE}] the sandbox probe failed here (bwrap with the builder's settings) "
            "-> make bubblewrap work on this host (user namespaces) before launching a builder . docs/spec/packet-standards.md"
        )
    facts: list[dict[str, str]] = []
    sock = policy["unix_socket_probe"]
    allow = False
    if sock:
        with_it = _passes([*_bwrap(settings, clone, []), *sock])
        without = _passes([*_bwrap(settings, clone, policy["unix_socket_paths"]), *sock])
        allow = with_it and not without
        facts.append(
            {
                "kind": "sandbox_unix_sockets",
                "detail": f"allowAllUnixSockets={str(allow).lower()}: probe with sockets {'passed' if with_it else 'failed'}, without {'passed' if without else 'failed'}",
            }
        )
    settings["sandbox"].setdefault("network", {})["allowAllUnixSockets"] = allow
    return facts, ""


def write_settings(root: Path, clone: Path, settings: dict[str, Any]) -> Path:
    """The settings of this launch only, beside the clone (never inside it, where the builder could
    write, and never shared with another launch)."""
    from bhorch import write_atomic

    path = root / LAUNCH_DIR / f"{clone.name}.settings.json"
    write_atomic(path, json.dumps(settings, indent=2) + "\n")
    return path


def commit_message(packet: dict[str, Any], digest: str) -> str:
    """Conventional Commits 1.0: the subject names the item, the trailers carry the packet identity
    and the acceptance ids the change answers."""
    goal = " ".join(str(packet.get("goal", "")).split())[:60] or "build"
    ids = ", ".join(a["id"] for a in packet.get("acceptance", []))
    from bhpacket import trailer  # the one derivation of the trailer value, from the kept packet

    return f"feat({packet['id']}): {goal}\n\nPacket: {trailer(packet, digest)}\nAcceptance: {ids}\n"


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
