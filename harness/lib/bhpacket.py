"""d0: the L2 work packet, one contract for the test author (L3), the builder (L4) and the measurer (L5).

OSS checked: ``jsonschema`` (draft 2020-12) validates the packet against
``harness/schema/packet.schema.json``; this module is the glue: the teaching message of a
refusal, the size cap that moves long text to a file, the Markdown rendering and the
``bh step`` entry. The packet fixes no design: a field the schema does not name is refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bhcore import RESULT_VERSION, SIZING_DEFAULT, HarnessError, load_schema

PACKETS_DIR = ".brick-harness/packets"
RUN_REPORT = ".brick-harness/run-report.txt"

SPEC = "docs/spec/packet-standards.md"
CRITERIA_SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "atdd" / "criteria.schema.json"
STEPS = ("assemble_packet", "validate_packet", "render_packet", "launch_builder", "generate_tests")
CUSTODY_DIR = (
    ".brick-harness/custody"  # the authoritative packets, one file per digest, outside every clone
)
CLONES_DIR = ".brick-harness/clones"
BUILDER_AGENT = "harness-builder"
# The launch prompt is one fixed line: the packet reaches the builder through the SessionStart hook
# (hooks/h1.py), the one delivery channel, so no packet text travels in argv or stdin.
LAUNCH_PROMPT = (
    "Your work packet was delivered when this session started. Read it, then do the work it asks."
)


def validate_packet(packet: Any) -> list[Any]:
    """The jsonschema errors of ``packet`` against the packet schema, in path order."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    # acceptance[*] is the plugin's one row definition (docs/atdd/criteria.schema.json $defs/row)
    criteria = json.loads((CRITERIA_SCHEMA).read_text())
    registry = Registry().with_resource(criteria["$id"], Resource.from_contents(criteria))
    return sorted(
        Draft202012Validator(load_schema("packet"), registry=registry).iter_errors(packet),
        key=lambda e: [str(p) for p in e.absolute_path],
    )


def _where(error: Any) -> str:
    return (
        "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path).lstrip(
            "."
        )
        or "packet"
    )


def teaching(error: Any) -> str:
    """One message of the shape ``[rule] wrong -> right . ref`` for a schema error (P5)."""
    where, kind = _where(error), error.validator
    if kind == "additionalProperties":
        extra = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        if "design" in extra:
            wrong = f"packet has a design field at {where}"
            right = (
                "the goal states the intent and why, with no design; put the design in the "
                "declared contract, schema or role delta file, not in the packet"
            )
            return f"[packet-design-field] {wrong} -> {right} . {SPEC}"
        return (
            f"[packet-unknown-field] packet has the field {', '.join(extra)} at {where} -> "
            f"use only the fields of harness/schema/packet.schema.json . {SPEC}"
        )
    if kind == "required" and "traces_to" in error.message or where.endswith("traces_to"):
        return (
            f"[packet-traces-to] scenario without traces_to at {where} -> traces_to lists a G, P, R or QBC id; "
            f"give every acceptance scenario traces_to before the packet is accepted . {SPEC}"
        )
    if kind == "required" and "verification" in error.message or where.endswith("verification"):
        return (
            f"[packet-verification] scenario without a valid verification at {where} -> verification is one of "
            "test, lint, fitness, measure; give every acceptance scenario a verification "
            f"(ISO/IEC/IEEE 29148) before the packet is accepted . {SPEC}"
        )
    return f"[packet-schema] {where}: {error.message[:120]} -> fix the field to match harness/schema/packet.schema.json . {SPEC}"


def packet_path(root: Path, item: str) -> Path:
    return root / PACKETS_DIR / f"{item}.json"


def load_packet(root: Path, item: str) -> tuple[Any, bytes]:
    path = packet_path(root, item)
    try:
        raw = path.read_bytes()
        return json.loads(raw), raw
    except (OSError, ValueError) as e:
        raise HarnessError(
            f"[packet-missing] no readable packet for {item} at {path} -> write it where the program reads packets . {SPEC}"
        ) from e


def packet_cap_bytes(root: Path) -> int:
    """sizing.packet_tokens (a default with a project override) as bytes, at 4 bytes a token."""
    cfg = root / ".brick-harness" / "config.json"
    sizing = json.loads(cfg.read_text()).get("sizing", {}) if cfg.is_file() else {}
    return int({**SIZING_DEFAULT, **sizing}["packet_tokens"]) * 4


def planner_values(packet: Any, schema: Any = None) -> list[Any]:
    """The values of the planner-written fields: the schema nodes annotated ``x-written-by: planner``
    (the schema is the one place that says who writes what; the program fills the rest)."""
    schema = load_schema("packet") if schema is None else schema
    if schema.get("x-written-by") == "planner":
        return [packet]
    found: list[Any] = []
    if isinstance(packet, dict):
        for key, sub in schema.get("properties", {}).items():
            if key in packet:
                found += planner_values(packet[key], sub)
    elif isinstance(packet, list) and isinstance(schema.get("items"), dict):
        for item in packet:
            found += planner_values(item, schema["items"])
    return found


def planner_bytes(packet: dict[str, Any]) -> int:
    """UTF-8 bytes of the planner-written fields as JSON: the unit sizing.packet_tokens counts at 4 bytes a token."""
    return len(json.dumps(planner_values(packet), ensure_ascii=False).encode())


def apply_cap(root: Path, packet: dict[str, Any]) -> list[dict[str, str]]:
    """Count only the planner-written fields against the cap. Over it, move the goal (the one free
    text among them) to a file in the packet directory and reference it by path. Over the cap is a
    fact, never a refusal."""
    from bhorch import write_atomic

    cap, size = packet_cap_bytes(root), planner_bytes(packet)
    if size <= cap:
        return []
    rel = f"{PACKETS_DIR}/{packet['id']}/goal.md"
    detail = f"planner-written fields are {size} bytes, over the cap of {cap}"
    if not any(o["path"] == rel for o in packet.get("overflow", [])):
        write_atomic(root / rel, packet["goal"].rstrip() + "\n")
        packet["goal"] = f"The goal is in {rel}; read it first."
        packet.setdefault("overflow", []).append({"path": rel})
        detail += f"; the goal moved to {rel} ({planner_bytes(packet)} bytes left)"
    return [{"kind": "over_cap", "detail": detail}]


def render_markdown(p: dict[str, Any]) -> str:
    """The packet as Markdown for agents; the same packet always gives the same text."""
    c, v, pr = p["constraints"], p["verifier"], p["paved_road"]
    out = [
        f"# Work packet: {p['id']}",
        "",
        f"Schema {p['schema_version']}. Parent issue #{p['parent_issue']}. Tier: {p['tier']}.",
        "",
        "## Goal",
        "",
        p["goal"],
        "",
    ]
    out += ["## Applies", ""] + [f"- {a['id']}: {a['text']}" for a in p["applies"]] + [""]
    out += ["## Constraints", ""]
    out += [f"- Decision {d['id']}: {d['text']}" for d in c.get("decisions", [])]
    out += [f"- Owner: {o}" for o in c.get("owners", [])] + [
        f"- Interface: {i}" for i in c.get("interfaces", [])
    ]
    out += [f"- Declared path: {d}" for d in c["declared_paths"]]
    out += [f"- Limit {k}: {val}" for k, val in sorted(c.get("limits", {}).items())] + [""]
    out += ["## Acceptance", ""]
    for a in p["acceptance"]:
        out += [
            f"### {a['id']}: {a['scenario']}",
            "",
            f"Verification: {a['verification']}. Traces to: {', '.join(a['traces_to'])}.",
            "",
        ]
        out += [f"- Given {json.dumps(g, sort_keys=True)}" for g in a["given"]]
        out += (
            [f"- When {json.dumps(a['when'], sort_keys=True)}"]
            + [f"- Then {json.dumps(t, sort_keys=True)}" for t in a["then"]]
            + [""]
        )
    out += ["## Verifier", ""] + [f"- Check: {x}" for x in v.get("checks", [])]
    out += [f"- Rule {r['id']}: {r['message']}" for r in v.get("rules", [])] + [
        f"- Baseline: {b}" for b in v.get("baselines", [])
    ]
    out += [
        f"- Target {t['id']} ({t['item']}): {t['metric']} {t['op']} {t['value']} {t.get('unit', '')}".rstrip()
        for t in v.get("targets", [])
    ]
    out += [f"- Acceptance path: {x}" for x in v["acceptance_paths"]] + [""]
    out += ["## Paved road", ""] + [f"- Tests go in: {x}" for x in pr["test_paths"]]
    out += [
        f"- Add a dependency: {pr['dependency_command']}",
        f"- Check yourself: {pr['check_command']}",
        "",
    ]
    out += ["## Definition of done", "", p["definition_of_done"], ""]
    out += (
        ["## Overflow", ""] + [f"- {o['path']}" for o in p["overflow"]] + [""]
        if p.get("overflow")
        else []
    )
    return "\n".join(out)


def custody_path(root: Path, digest: str) -> Path:
    return root / CUSTODY_DIR / f"{digest}.json"


def custody_store(root: Path, raw: bytes) -> str:
    """Keep the packet by its sha256 in the orchestrator's directory; the file is read-only and never rewritten."""
    from bhorch import write_atomic

    digest = hashlib.sha256(raw).hexdigest()
    path = custody_path(root, digest)
    if not path.exists():
        write_atomic(path, raw.decode())
        path.chmod(0o444)
    return digest


def custody_read(root: Path, digest: str) -> bytes:
    """The kept packet; its bytes must still hash to the digest that names the file."""
    try:
        raw = custody_path(root, digest).read_bytes()
    except OSError as e:
        raise HarnessError(
            f"[packet-custody] no kept packet {digest} under {root / CUSTODY_DIR} -> the orchestrator "
            f"keeps the packet before it measures against it (custody_store) . {SPEC}"
        ) from e
    if hashlib.sha256(raw).hexdigest() != digest:
        raise HarnessError(
            f"[packet-custody] the kept packet {digest} no longer hashes to its name -> restore it "
            f"from the planner's commit; the program never launches from a changed packet . {SPEC}"
        )
    return raw


def assemble(root: Path, item: str) -> tuple[Any, bytes, list[dict[str, str]], str]:
    """Validate the packet and apply the size cap; return (packet, bytes, facts, teaching errors)."""
    from bhorch import write_atomic

    packet, raw = load_packet(root, item)
    errors = validate_packet(packet)
    if errors:
        return packet, raw, [], "\n".join(teaching(e) for e in errors) + "\n"
    facts = apply_cap(root, packet)
    if facts:
        raw = (json.dumps(packet, indent=2) + "\n").encode()
        write_atomic(packet_path(root, item), raw.decode())
        write_atomic(root / RUN_REPORT, "".join(f"{f['kind']}: {f['detail']}\n" for f in facts))
    return packet, raw, facts, ""


def result_json(name: str, raw: bytes, facts: list[dict[str, str]], **extra: Any) -> str:
    doc = {
        "schema_version": RESULT_VERSION,
        "command": "step",
        "step": name,
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "facts": facts,
        **extra,
    }
    return json.dumps(doc, indent=2) + "\n"


def register(root: Path, clone: Path, digest: str, packet: dict[str, Any]) -> None:
    """Put the clone's copy of the packet where the hooks read it (H0, H1, H2): a copy of the
    kept bytes, so whatever the builder does to it changes nothing the program reads."""
    from bhorch import write_atomic

    write_atomic(packet_path(clone, packet["id"]), custody_read(root, digest).decode())
    for o in packet.get("overflow", []):
        src = root / o["path"]
        if src.is_file():
            (clone / o["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, clone / o["path"])


def launch_builder(root: Path, item: str) -> tuple[int, str, str]:
    """Launch one builder: keep the packet by digest, make the clone, register the packet in it and
    start the builder with the fixed prompt. SessionStart delivers the packet (hooks/h1.py)."""
    import bhorch

    packet, raw, facts, err = assemble(root, item)
    if err:
        return 1, "", err
    digest = custody_store(root, raw)
    clone = root / CLONES_DIR / f"{item}-{digest[:12]}"
    if not clone.exists():
        bhorch.git(root, "clone", "-q", "--shared", str(root), str(clone))
    register(root, clone, digest, packet)
    # A login-mode launch with the plugin: bare mode runs no hooks, and the packet arrives by a hook.
    argv = [
        os.environ.get("BH_CLAUDE", "claude"),
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        ",".join(bhorch.agent_def(BUILDER_AGENT)["tools"]),
        *bhorch.mode_flags("login", None, BUILDER_AGENT),
    ]
    started = datetime.now(UTC)
    try:
        p = subprocess.run(argv, input=LAUNCH_PROMPT, cwd=clone, capture_output=True, text=True)
        code, out = p.returncode, p.stdout
    except OSError as e:
        code, out = 127, ""
        facts = [*facts, {"kind": "launch_failed", "detail": f"cannot start {argv[0]}: {e}"}]
    cli = bhorch.parse_cli_result(out) or {}
    t = bhorch.tokens_of(cli.get("usage"))
    job = {
        "id": f"{item}-builder-{digest[:12]}",
        "kind": "agent",
        "role": "builder",
        "item": item,
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exit_code": code,
        "cost_usd": float(cli.get("total_cost_usd") or 0),
        "tokens": t["input"] + t["output"],
        "packet_sha256": digest,
    }
    return 0, result_json("launch_builder", raw, facts, jobs=[job]), ""


def program_job(
    step_name: str, item: str, started: datetime, digest: str, exit_code: int = 0
) -> dict[str, Any]:
    """The ``jobs[*]`` entry of a program step: no agent, no tokens, no cost."""
    return {
        "id": f"{item}-{step_name}-{digest[:12]}",
        "kind": "program_step",
        "step": step_name,
        "item": item,
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exit_code": exit_code,
        "cost_usd": 0.0,
        "tokens": 0,
        "packet_sha256": digest,
    }


def generate_tests(root: Path, item: str) -> tuple[int, str, str]:
    """The generator, a program step with no agent: the packet's rows become the item's collected tests."""
    import bhtests
    from bhorch import write_atomic

    started = datetime.now(UTC)
    packet, raw, facts, err = assemble(root, item)
    if err:
        return 1, "", err
    more, _ = bhtests.generate(root, packet)
    facts = [*facts, *more]
    write_atomic(root / RUN_REPORT, "".join(f"{f['kind']}: {f['detail']}\n" for f in facts))
    digest = hashlib.sha256(raw).hexdigest()
    return (
        0,
        result_json(
            "generate_tests", raw, facts, jobs=[program_job("generator", item, started, digest)]
        ),
        "",
    )


def step(name: str, root: Path, item: str) -> tuple[int, str, str]:
    """Run one program step; return (exit code, stdout, stderr)."""
    if name == "launch_builder":
        return launch_builder(root, item)
    if name == "generate_tests":
        return generate_tests(root, item)
    if name == "assemble_packet":
        packet, raw, facts, err = assemble(root, item)
    else:
        packet, raw = load_packet(root, item)
        facts, err = [], "\n".join(teaching(e) for e in validate_packet(packet))
        err = err + "\n" if err else ""
    if err:
        return 1, "", err
    if name == "render_packet":
        return 0, render_markdown(packet), ""
    return 0, result_json(name, raw, facts), ""


def run_step(name: str, item: str) -> int:
    """The ``bh step`` entry: run the step in the current directory, print its streams."""
    try:
        code, out, err = step(name, Path.cwd(), item)
    except HarnessError as e:
        code, out, err = 2, "", f"{e}\n"
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code
