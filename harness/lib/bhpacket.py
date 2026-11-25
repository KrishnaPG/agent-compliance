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
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bhbuilder
import bhinfer
from bhcore import RESULT_VERSION, SIZING_DEFAULT, HarnessError, load_schema

PACKETS_DIR = ".brick-harness/packets"
RUN_REPORT = ".brick-harness/run-report.txt"
BUILD_REF = "refs/bh/{item}"  # the item's build commit in the source repository, set by the program only

SPEC = "docs/spec/packet-standards.md"
CRITERIA_SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "atdd" / "criteria.schema.json"
STEPS = (
    "assemble_packet",
    "validate_packet",
    "render_packet",
    "launch_builder",
    "commit_build",
    "merge",
)
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
        f"Schema {p['schema_version']}."
        + (f" Parent issue #{p['parent_issue']}." if p.get("parent_issue") else "")
        + f" Tier: {p['tier']}.",
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


def custody_digest(root: Path, item: str | None = None) -> str | None:
    """The digest of the item's kept packet, the one resolver from an item to its identity: the
    newest kept packet whose id is the item (a changed packet is kept beside the old one). With
    no item, the kept packet of the one item custody holds."""
    kept = []
    for f in (root / CUSTODY_DIR).glob("*.json"):
        try:
            pid = json.loads(f.read_bytes()).get("id")
            kept.append((pid, f.stat().st_mtime_ns, f.stem))
        except (OSError, ValueError, AttributeError):
            continue
    mine = [k for k in kept if item is None or k[0] == item]
    return max(mine, key=lambda k: k[1:])[2] if mine and len({k[0] for k in mine}) == 1 else None


def trailer(packet: dict[str, Any], digest: str) -> str:
    """The commit trailer that ties a commit to its packet (L4): derived from the kept packet."""
    return f"{packet['id']}@{digest}"


SPEC_SECTION_0 = Path(__file__).resolve().parents[2] / "docs" / "spec" / "quality-by-construction.md"
GLOB = re.compile(r"[*?\[]")
PRINCIPLE_RE = re.compile(r"^- \[[ x]\] \*\*(P\d+)\.\*\* (.+)$")
# The tier triggers (QBC-25, QBC-27, §6.1). Mechanical is a positive classification proven from
# facts; anything unproven is design-affecting (ISTQB risk-based testing: unknown risk goes to the
# higher tier). A path matching a design-affecting row raises the item (contract, schema, roles or
# grants, compose, the architecture-target budget), as a SemVer major pin bump does
# (``bhcore.major_bumps``). A mechanical row is the docs proof; the other proofs are diff facts
# (``bhcore.diff_tier``). A project's `tiers.triggers` replaces the list (P8).
TIER_TRIGGERS: list[dict[str, Any]] = [
    {"paths": ["docs/", "*/docs/*", "README*", "CHANGELOG*"], "tier": "mechanical", "fresh_stack": False},
    {"paths": ["*openapi*.yaml", "*openapi*.yml", "*openapi*.json", "*.proto", ".brick-harness/contracts/"],
     "tier": "design-affecting", "fresh_stack": False},
    {"paths": ["*.sql", "migrations/", "*/migrations/*", "*.schema.json"], "tier": "design-affecting", "fresh_stack": True},
    {"paths": ["*grants*", "roles/", "*/roles/*"], "tier": "design-affecting", "fresh_stack": True},
    {"paths": ["compose.yaml", "compose.yml", "compose.*.yaml", "compose.*.yml", "*/compose.yaml", "*/compose.yml",
               "*docker-compose*.yaml", "*docker-compose*.yml"], "tier": "design-affecting", "fresh_stack": True},
    {"paths": [".brick-harness/targets.json"], "tier": "design-affecting", "fresh_stack": False},
]
TIER_RANK = {"mechanical": 0, "design-affecting": 1}


def tier_of(
    cfg_data: dict[str, Any],
    paths: list[str],
    bumps: list[str] | None = None,
    *,
    kind: str = "slice",
    owners: list[str] | None = None,
    renamed: list[str] | None = None,
    pinned: list[str] | None = None,
) -> tuple[str, list[str]]:
    """The tier of an item touching ``paths``, and why (R6, §6.1). Design-affecting when a path
    matches a design-affecting trigger (``tiers.triggers``, else ``TIER_TRIGGERS``) or a lockfile
    has a major ``bumps``; the reasons are those paths and bumps. Otherwise mechanical only when a
    fact proves it: every path matches a mechanical trigger (docs), is one side of a pure rename
    (``renamed``) or a patch or minor pin bump (``pinned``), or the item is a defect (``kind``,
    from the packet: a defect sub-issue under its slice) within exactly one owner (``owners``); the
    reasons are the proofs. Anything unproven is design-affecting, the reasons the unproven paths
    (ISTQB risk-based testing). Derived, never typed."""
    import bhcore

    triggers = cfg_data.get("tiers", {}).get("triggers") or TIER_TRIGGERS
    hits = [(t["tier"], p) for t in triggers for p in paths if bhcore._matches(p, t["paths"])]
    raised = {p for t, p in hits if t != "mechanical"} | set(bumps or [])
    if raised:
        return "design-affecting", sorted(raised)
    proofs = {
        "docs": {p for _, p in hits},
        "pure rename": set(renamed or []),
        "patch or minor pin bump": set(pinned or []),
    }
    rest = set(paths) - set().union(*proofs.values())
    why = [k for k, v in proofs.items() if v & set(paths)]
    if not rest:
        return "mechanical", why
    if kind == "defect" and len(owners or []) == 1:
        return "mechanical", [*why, f"defect fix within owner {owners[0]}"]
    return "design-affecting", sorted(rest)


DONE = (
    "Every acceptance criterion is met by the measurer: its test in verifier.acceptance_paths "
    "passes in the project's own test command, and nothing else turns red."
)


def _slug(item: str) -> str:
    return re.sub(r"\W", "_", item).strip("_").lower() or "item"


def test_roots(root: Path) -> list[str]:
    """The project's test roots as its test runner's own config names them (``bhinfer``)."""
    return list((bhinfer.test_roots(root) or {}).get("value", []))


def paved_road(root: Path, cfg_data: dict[str, Any], protected: list[str]) -> dict[str, Any]:
    """The paved road, inferred from the project's standard files (P9); the config's
    ``paved_road`` overrides any part. Test paths are the project's test roots the builder may
    write: a protected root (the default protects tests/) is left out."""
    import bhcore

    roots = test_roots(root)
    dep = bhinfer.infer(root).get("dependency", {}).get("value", "add it to the project's manifest")
    road = {
        "test_paths": [r for r in roots if not bhcore._matches(r.rstrip("/") + "/", protected)],
        "dependency_command": dep,
        "check_command": "bh check",
    }
    return {**road, **cfg_data.get("paved_road", {})}


def plan_packet(cfg: Any, item: str) -> dict[str, Any]:
    """The d0 packet of a planned item, filled by the program from the plan (items, targets,
    cited passages, rules) and the project's standard files; ``acceptance`` is left for the test
    author. No agent writes any of it."""
    import bhcore
    import bhreview
    import bhrules

    ctx = bhcore.packet_context(cfg)
    b = ctx["bricks"].get(item)
    if b is None:
        raise HarnessError(f"[packet-unknown-item] {item} is not in the plan -> run bh plan first . {SPEC}")
    root = cfg.dir
    principles = [
        {"id": m[1], "text": m[2].strip()}
        for ln in SPEC_SECTION_0.read_text().splitlines()
        if (m := PRINCIPLE_RE.match(ln))
    ]
    passages = [bhcore._passage(cfg, ctx, c) for c in b.get("context", [])]
    road = paved_road(root, cfg.data, cfg.protected)
    lang = cfg.inferred.get("language", {}).get("value")
    accept_root = (test_roots(root) or ["test" if lang == "node" else "tests"])[0].rstrip("/")  # protected: the builder cannot edit it
    targets = [
        {
            "id": f"{item}-T{n}",
            "item": item,
            "metric": t["metric"],
            "op": t["op"],
            "value": t["value"],
            **({"unit": t["unit"]} if t.get("unit") else {}),
        }
        for n, t in enumerate(bhrules.item_targets(cfg, ctx["targets"], item), 1)
        if isinstance(t.get("value"), int | float)
    ]
    goal = b["job"] + (f" Purpose: {b['purpose']}" if b.get("purpose") else "")
    declared = bhcore._own_paths(b) or ["."]
    # the touched owners and their published interfaces, so the builder extends them (QBC-19)
    owners = bhreview.packet_owners(root, declared, bhreview.limits(cfg.data)["message_chars"])
    return {
        "schema_version": "1.0.0",
        "id": item,
        "kind": "slice",
        "tier": tier_of(cfg.data, declared)[0],  # a prediction from the declared paths; the diff corrects it (QBC-30)
        "goal": goal,
        "applies": principles,
        "constraints": {
            "decisions": [
                {"id": f"{p['path']}:{p['lines']}", "text": p["text"]} for p in passages if p["text"]
            ],
            **owners,
            "declared_paths": declared,
            "limits": {**bhcore.SIZING_DEFAULT, **cfg.data.get("sizing", {})},
        },
        "acceptance": [],
        "verifier": {
            "acceptance_paths": [f"{accept_root}/acceptance/{bhinfer.acceptance_name(lang, _slug(item))}"],
            "targets": targets,
            "rules": [
                {"id": r["id"], "message": r["text"] or r["id"]}
                for r in bhcore.packet_rules(cfg, item, ctx)
            ],
        },
        "paved_road": road,
        "definition_of_done": DONE,
    }


def acceptance_file(packet: dict[str, Any]) -> str:
    """The test author's file: ``verifier.acceptance_paths[0]`` when it names a file, else
    ``test_<item>.py`` under the fixed prefix of that glob or directory."""
    first = packet["verifier"]["acceptance_paths"][0]
    parts = first.split("/")
    fixed = parts[: next((i for i, x in enumerate(parts) if GLOB.search(x)), len(parts))]
    if len(fixed) == len(parts) and first.endswith((".py", ".js", ".mjs", ".cjs", ".ts")):
        return first
    prefix = "/".join(x for x in fixed if x)
    return f"{prefix or '.'}/test_{_slug(packet['id'])}.py"


def write_plan_packet(cfg: Any, item: str) -> Path:
    """Write the item's packet from the plan unless one exists (the test author's rows and a
    kept packet are never overwritten)."""
    from bhorch import write_atomic

    path = packet_path(cfg.dir, item)
    if not path.is_file():
        write_atomic(path, json.dumps(plan_packet(cfg, item), indent=2) + "\n")
    return path


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
        write_report(root, facts)
    return packet, raw, facts, ""


def write_report(root: Path, facts: list[dict[str, str]]) -> None:
    """The run report: one ``kind: detail`` line per fact of the step."""
    from bhorch import write_atomic

    write_atomic(root / RUN_REPORT, "".join(f"{f['kind']}: {f['detail']}\n" for f in facts))


def outside_paths(root: Path, packet: dict[str, Any]) -> list[str]:
    """The paths of the item's build ref outside the packet's declared paths: the one L4 comparison
    (publish_build reports it; a re-plan declares what it absorbs)."""
    import bhcore

    ref = BUILD_REF.format(item=packet["id"])
    base = bhbuilder._git(root, "merge-base", "HEAD", ref)
    paths = bhbuilder._git(root, "diff", "--name-only", "--no-renames", base, ref).splitlines()
    declared = packet.get("constraints", {}).get("declared_paths", [])
    return [p for p in paths if not bhcore._matches(p, declared)]


def publish_build(root: Path, clone: Path, packet: dict[str, Any], digest: str) -> tuple[str, list[dict[str, str]]]:
    """L4 Build (packet-standards.md): the program commits the builder's change in its clone, brings
    that commit into the source repository as the item's build ref (the ref the measurer and the merge
    read, which the builder cannot move), and compares the build's paths with the packet's declared
    paths: a path outside them is a scope fact with its teaching, never a refusal (P4, P5)."""
    import bhcore

    sha = bhbuilder.commit_build(clone, packet, digest)
    ref = BUILD_REF.format(item=packet["id"])
    bhbuilder._git(root, "fetch", "-q", str(clone), f"+{sha}:{ref}")
    base = bhbuilder._git(root, "merge-base", "HEAD", ref)
    outside = outside_paths(root, packet)
    cfg = root / ".brick-harness" / "config.json"
    tier, why = bhcore.diff_tier(json.loads(cfg.read_text()) if cfg.is_file() else {}, root, base, ref, packet.get("kind", "slice"))
    if packet.get("tier") and TIER_RANK[tier] > TIER_RANK[packet["tier"]]:  # the program re-plans: one fact says what it did (R6, QBC-30)
        detail = f"tier {tier} from paths {', '.join(why)}"
        wrong = f"packet {packet['id']} is {packet['tier']} but its diff touches {', '.join(why)}"
        right = f"the orchestrator re-plans it as {tier}"
        teach = bhcore._teach("tier", wrong, right, "declare those paths in the packet, or keep the change inside its declared paths")
        return sha, [{"kind": "scope", "detail": detail, "message": teach}]
    if not outside:
        return sha, []
    wrong = f"diff path outside the packet's declared paths: {', '.join(outside[:20])}"
    right = "keep changes inside the declared paths or ask for a plan change"
    return sha, [{"kind": "scope", "detail": bhcore._teach("scope", wrong, right, "declare every path the item touches in the packet")}]


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


def register(root: Path, clone: Path, digest: str) -> None:
    """Put the clone's copy of the kept packet where the hooks read it (H0, H1, H2): a copy of the
    custody bytes, so whatever the builder does to it changes nothing the program reads."""
    from bhorch import write_atomic

    raw = custody_read(root, digest)
    packet = json.loads(raw)
    write_atomic(packet_path(clone, packet["id"]), raw.decode())
    for o in packet.get("overflow", []):
        src = root / o["path"]
        if src.is_file():
            (clone / o["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, clone / o["path"])


def launch_builder(
    root: Path,
    item: str,
    usd: float | None = None,
    feedback: list[str] | None = None,
    base: str | None = None,
    round_no: int = 1,
) -> tuple[int, str, str]:
    """Launch one builder: keep the packet by digest, make the clone, register the packet in it and
    start the builder with the fixed prompt. SessionStart delivers the packet (hooks/h1.py). A later
    round reuses the clone (same packet and base) and the prompt adds only the missed checks' or the
    review's teaching messages (QBC-51, QBC-55). ``base`` is the item's plan commit, the same for
    all its rounds (default HEAD), so a record committed between rounds never starts a new clone.
    ``round_no`` is the builder round the order engine counted from its state; the job carries it."""
    import bhorch

    packet, raw, facts, err = assemble(root, item)
    if err:
        return 1, "", err
    cfg = root / ".brick-harness" / "config.json"
    config = json.loads(cfg.read_bytes()) if cfg.is_file() else {}
    policy = bhbuilder.launch_policy(config)
    digest = custody_store(root, raw)
    base = base or bhorch.git(root, "rev-parse", "HEAD").stdout.strip()  # the base commit the program records
    clone = root / CLONES_DIR / f"{item}-{digest[:12]}-{base[:12]}"  # one clone per packet and base
    bhbuilder.make_clone(root, clone, base)
    register(root, clone, digest)
    built = bhbuilder.builder_settings(packet, root, clone, Path(__file__).resolve().parents[2], config.get("sandbox"))
    probed, refusal = bhbuilder.probe_host(built, clone, policy)
    if refusal:
        return 1, "", refusal + "\n"
    facts = [*facts, *probed]
    settings = bhbuilder.write_settings(root, clone, built)
    # A login-mode launch with the plugin: bare mode runs no hooks, and the packet arrives by a hook.
    argv = [
        os.environ.get("BH_CLAUDE", "claude"),
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        *(["--max-budget-usd", str(usd)] if usd else []),  # the run's per-job cap (budgets.job_usd)
        "--permission-mode",
        "dontAsk",
        "--settings",
        str(settings),
        "--allowedTools",  # Bash is never pre-approved: the sandbox's auto-allow is its only way in
        ",".join(t for t in bhorch.agent_def(BUILDER_AGENT)["tools"] if t != "Bash"),
        *bhorch.mode_flags("login", None, BUILDER_AGENT),
    ]
    started = datetime.now(UTC)
    before = bhorch.git(clone, "rev-parse", "HEAD").stdout.strip()  # a later round starts from the last round's commit
    try:
        prompt = LAUNCH_PROMPT + (
            "\nYour last result went back to you; fix these, then finish:\n" + "\n".join(f"- {f}" for f in feedback)
            if feedback
            else ""
        )
        p = subprocess.run(argv, input=prompt, cwd=clone, capture_output=True, text=True)
        code, out = p.returncode, p.stdout
    except OSError as e:
        code, out = 127, ""
        facts = [*facts, {"kind": "launch_failed", "detail": f"cannot start {argv[0]}: {e}"}]
    cli = bhorch.parse_cli_result(out) or {}
    t = bhorch.tokens_of(cli.get("usage"))
    after, scope = publish_build(root, clone, packet, digest)  # the program commits, never the builder
    facts = [*facts, *scope]
    job = {
        "id": f"{item}-builder-{digest[:12]}-{round_no}",
        "kind": "agent",
        "role": "builder",
        "item": item,
        "round": round_no,
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exit_code": code,
        "subtype": cli.get("subtype"),  # the CLI's own outcome (success, error_max_turns, error_max_budget_usd...)
        "num_turns": cli.get("num_turns"),
        "tree_changed": after != before,  # false: the round was a no-op, recorded as a fact
        "cost_usd": float(cli.get("total_cost_usd") or 0),
        "tokens": t["input"] + t["output"],
        "packet_sha256": digest,
    }
    return 0, result_json("launch_builder", raw, facts, jobs=[job]), ""


def commit_build(root: Path, item: str) -> tuple[int, str, str]:
    """The program's own commit of the builder's change in the item's clone (also run by launch)."""
    packet, raw = load_packet(root, item)
    digest = hashlib.sha256(raw).hexdigest()
    clones = sorted((root / CLONES_DIR).glob(f"{item}-*"), key=lambda p: p.stat().st_mtime)
    if not clones:
        return 1, "", f"[commit_build] no clone of {item} under {CLONES_DIR} -> launch the builder first . {SPEC}\n"
    sha, facts = publish_build(root, clones[-1], packet, digest)
    write_report(root, facts)
    return 0, result_json("commit_build", raw, facts, commit=sha), ""


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


def step(name: str, root: Path, item: str | None) -> tuple[int, str, str]:
    """Run one program step; return (exit code, stdout, stderr)."""
    if name == "merge":  # the one step that works on a branch, not on a packet: --item is optional
        import bhcore

        return bhcore.merge_step(root, item)
    if item is None:
        return 2, "", f"step {name} needs --item\n"
    if name == "launch_builder":
        return launch_builder(root, item)
    if name == "commit_build":
        return commit_build(root, item)
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


def run_step(name: str, item: str | None) -> int:
    """The ``bh step`` entry: run the step in the current directory, print its streams."""
    try:
        code, out, err = step(name, Path.cwd(), item)
    except HarnessError as e:
        code, out, err = 2, "", f"{e}\n"
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code
