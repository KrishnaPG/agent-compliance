"""d0: the L2 work packet, one contract for the test author (L3), the builder (L4) and the measurer (L5).

OSS checked: ``jsonschema`` (draft 2020-12) validates the packet against
``harness/schema/packet.schema.json``; this module is the glue: the teaching message of a
refusal, the size cap that moves long text to a file, the Markdown rendering and the
``bh step`` entry. The packet fixes no design: a field the schema does not name is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from bhcore import SIZING_DEFAULT, HarnessError, load_schema

PACKETS_DIR = ".brick-harness/packets"
RUN_REPORT = ".brick-harness/run-report.txt"
RESULT_VERSION = "1.0.0"
SPEC = "docs/spec/packet-standards.md"
STEPS = ("assemble_packet", "validate_packet", "render_packet")


def validate_packet(packet: Any) -> list[Any]:
    """The jsonschema errors of ``packet`` against the packet schema, in path order."""
    from jsonschema import Draft202012Validator

    return sorted(
        Draft202012Validator(load_schema("packet")).iter_errors(packet),
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


def apply_cap(root: Path, packet: dict[str, Any]) -> list[dict[str, str]]:
    """Move the goal to a file in the packet directory when it is over the cap, and reference it
    by path; return the facts (never a refusal: over the cap is a fact)."""
    from bhorch import write_atomic

    cap, goal = packet_cap_bytes(root), packet["goal"]
    if len(goal.encode()) <= cap:
        return []
    rel = f"{PACKETS_DIR}/{packet['id']}/goal.md"
    write_atomic(root / rel, goal.rstrip() + "\n")
    packet["goal"] = f"The goal is in {rel}; read it first."
    packet.setdefault("overflow", []).append({"path": rel})
    return [
        {
            "kind": "over_cap",
            "detail": f"goal is {len(goal.encode())} bytes, over the cap of {cap}; moved to {rel}",
        }
    ]


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


def step(name: str, root: Path, item: str) -> tuple[int, str, str]:
    """Run one program step; return (exit code, stdout, stderr)."""
    from bhorch import write_atomic

    packet, raw = load_packet(root, item)
    errors = validate_packet(packet)
    if errors:
        return 1, "", "\n".join(teaching(e) for e in errors) + "\n"
    facts: list[dict[str, str]] = []
    if name == "render_packet":
        return 0, render_markdown(packet), ""
    if name == "assemble_packet":
        facts = apply_cap(root, packet)
        if facts:
            raw = (json.dumps(packet, indent=2) + "\n").encode()
            write_atomic(packet_path(root, item), raw.decode())
            write_atomic(root / RUN_REPORT, "".join(f"{f['kind']}: {f['detail']}\n" for f in facts))
    result = {
        "schema_version": RESULT_VERSION,
        "command": name,
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "facts": facts,
    }
    return 0, json.dumps(result, indent=2) + "\n", ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="bh step", description="Run one program step, with no agent.")
    ap.add_argument("name", choices=STEPS)
    ap.add_argument("--item", required=True)
    a = ap.parse_args(argv)
    try:
        code, out, err = step(a.name, Path.cwd(), a.item)
    except HarnessError as e:
        code, out, err = 2, "", f"{e}\n"
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code
