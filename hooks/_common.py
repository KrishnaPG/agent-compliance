"""Shared glue for the plugin hooks: parse the hook input, tell the agent types apart, record facts.

Hooks only enforce order and give one capped line (QBC-43); they match no code patterns (QBC-44).
"""
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

H0_TO_BUILDER = (
    "[QBC-47] No work packet for this clone -> Builders start from a packet the orchestrator writes "
    "(goal, tier, constraints, tests). Stop and ask to be relaunched with one . docs/spec/quality-by-construction.md"
)
H0_TO_ORCHESTRATOR = (
    "Builder {id} started without a packet. Launch builders through the harness launch step, "
    "which writes the packet first; mechanical work gets a minimal one."
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness" / "lib"))
from atdd_engine.teaching import teach  # noqa: E402 (one owner of the teaching shape)


def sg01_pre(path: str) -> str:
    """SG-01's refusal of an edit to a protected acceptance test: one capped teaching line."""
    return teach(
        "SG-01",
        f"acceptance test is protected (SG-01): {path}",
        "ask the orchestrator to change it in the plan; tests sit in protected paths",
        "docs/spec/packet-standards.md",
    )


def outside_pre(path: str) -> str:
    """SG-01's refusal of a write beyond the clone: one capped teaching line. The path comes last in
    the wrong part, so the cap cuts the path, never what is wrong or the right way (P5, QBC-43)."""
    return teach(
        "R4",
        f"path is outside the clone; the packet and every file beyond the clone are orchestrator-owned: {path}",
        "write only inside the clone; the orchestrator writes the packet",
        "file tools are scoped to the clone",
    )


SG01_NOTE = (
    "[SG-01] SG-01 note: read-only file system, tests are protected -> ask the orchestrator to change them; "
    "do not write into tests/, tests sit in protected paths . docs/spec/packet-standards.md"
)
H2_DEFAULT_CHARS = 200  # d9 moves this into the one limits table (limits.h2_chars)


def load_input() -> dict:
    return json.load(sys.stdin)


def is_builder(data: dict) -> bool:
    return str(data.get("agent_type", "")).split(":")[-1] in ("builder", "harness-builder")


def project_dir(data: dict) -> Path:
    cwd = Path(str(data.get("cwd") or ""))
    return cwd if cwd.is_dir() else Path.cwd()


def packet_files(root: Path) -> list:
    return sorted((root / ".brick-harness" / "packets").glob("*.json"))


def has_packet(data: dict, root: Path) -> bool:
    return bool(packet_files(root))


def target_path(data: dict, root: Path) -> str:
    raw = str((data.get("tool_input") or {}).get("file_path", ""))
    p = Path(raw)
    try:
        return str(p.relative_to(root)) if p.is_absolute() else raw
    except ValueError:
        return raw


def record_fact(root: Path, kind: str, detail: str) -> Path:
    """The scope-fact writer: one JSON file per fact in .brick-harness/hook-facts/ (the measurer reads them)."""
    d = root / ".brick-harness" / "hook-facts"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{len(list(d.glob('*.json'))):06d}-{kind}.json"
    f.write_text(json.dumps({"kind": kind, "detail": detail}) + "\n")
    return f, {"kind": kind, "detail": detail}


def read_facts(root: Path) -> list:
    """The facts record_fact wrote, in order; an unreadable file is skipped."""
    out = []
    for f in sorted((root / ".brick-harness" / "hook-facts").glob("*.json")):
        try:
            out.append(json.loads(f.read_bytes()))  # JSON is UTF-8 bytes (RFC 8259): parsed as bytes, never as text
        except (OSError, ValueError):
            continue
    return out


def declared_globs(root: Path) -> list:
    out = []
    for f in packet_files(root):
        pk = json.loads(f.read_bytes())  # packet data, not code: its declared paths
        out += pk.get("constraints", {}).get("declared_paths", []) + pk.get("paved_road", {}).get("test_paths", [])
    return out


def acceptance_globs(root: Path) -> list:
    """The packet's protected acceptance paths: the one list the builder settings' denyWrite is made from."""
    out = []
    for f in packet_files(root):
        out += json.loads(f.read_bytes()).get("verifier", {}).get("acceptance_paths", [])
    return out
def outside(root: Path, path: str) -> bool:
    """A target path (as target_path gives it) that lies outside the working directory."""
    p = Path(path)
    full = (p if p.is_absolute() else root / p).resolve()
    return not full.is_relative_to(root.resolve())


def inside(path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(path, g) or path == g.rstrip("/*") for g in globs)


def h2_chars(root: Path) -> int:
    cfg = root / ".brick-harness" / "config.json"
    if cfg.is_file():
        return int(json.loads(cfg.read_bytes()).get("limits", {}).get("h2_chars", H2_DEFAULT_CHARS))
    return H2_DEFAULT_CHARS


def seen_marker(root: Path, path: str) -> Path:
    return root / ".brick-harness" / "h2-seen" / hashlib.sha1(path.encode()).hexdigest()


def emit(facts_file=None, **extra) -> None:
    out = {"facts": [], **extra}
    if facts_file is not None:
        out["run_report"] = str(facts_file)
    print(json.dumps(out))
    sys.exit(0)


def owner_of(root: Path, path: str) -> str:
    """c7's `bh owners` answers; until it is shipped the owner is reported as not declared."""
    import subprocess

    bh = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", "")) / "bin" / "bh"
    try:
        p = subprocess.run([str(bh), "owners", path, "--json"], cwd=root, capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            return str(json.loads(p.stdout).get("owner") or "not declared")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "not declared"
