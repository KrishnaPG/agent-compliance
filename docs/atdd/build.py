# /// script
# requires-python = ">=3.11"
# dependencies = ["check-jsonschema==0.39.0", "pyyaml>=6"]
# ///
"""Generate criteria.schema.json from catalog.yaml, validate every criteria file with check-jsonschema, write coverage.md.

Mechanical, no agent. Run from the repository root:

    uv run --script docs/atdd/build.py            # regenerate schema and coverage.md
    uv run --script docs/atdd/build.py --check    # also exit 1 when anything is invalid or uncovered
    uv run --script docs/atdd/build.py --bullets  # print each task's numbered "Done when" leaves
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = ROOT / "docs/spec/quality-by-construction.md"
PLAN = ROOT / "docs/plan/v2-work-plan.md"
CATALOG = HERE / "catalog.yaml"
FIELDS = HERE / "fields.yaml"
FIELDS_MD = HERE / "d0-fields.md"
SCHEMA = HERE / "criteria.schema.json"
COVERAGE = HERE / "coverage.md"
CRITERIA = HERE / "criteria"
SLICES = "abcdefgh"
STANDARDS = ROOT / "docs/spec/packet-standards.md"

ID_RE = r"^[a-z0-9][a-z0-9_.-]*$"  # as catalog.yaml `types`
KEY_RE = r"^[A-Za-z0-9_.\[\]*=-]+$"
REJECTING = {
    "exit_code": lambda p: p.get("code", 0) != 0,
    "met": lambda p: p.get("status") in {"unmet", "stuck", "not_checked"},
    "schema_valid": lambda p: p.get("valid") is False,
    "refused": lambda p: True,
}
TEACHING = {"teaching", "refused"}
CODE_TOKEN = re.compile(r"[/._`=-]|\d|\b[A-Z]{2,}\b|--")


IDENT = (re.compile(r"^(?=.*[/._=`\d-])\S+$"), re.compile(r"^[A-Z][A-Z0-9-]+$"))  # catalog terms.identifier token


def identifiers(text: str) -> list[str]:
    toks = [re.sub(r"\.$", "", w.strip(",;:()\"'")) for w in text.split()]
    toks = [t.strip(",;:()\"'") for t in toks]
    return [t for t in toks if t and (IDENT[0].match(t) or IDENT[1].match(t))]


def weak_part(text: str) -> bool:
    """A teaching part a generic message could satisfy: one plain word with no code-like token."""
    return len(text.split()) < 2 and not CODE_TOKEN.search(text)


def catalog_lint(catalog: dict) -> list[str]:
    """Catalog defects: an enum whose values are not a map of value -> definition."""
    out = []
    for kind in ("given", "when", "then"):
        for key, entry in catalog[kind].items():
            for name, p in (entry.get("params") or {}).items():
                if p.get("type") == "enum" and "ref" not in p and not isinstance(p.get("values"), dict):
                    out.append(f"catalog {kind}.{key}.{name}: enum values have no definitions")
                elif isinstance(p.get("values"), dict):
                    out += [f"catalog {kind}.{key}.{name}.{v}: empty definition" for v, d in p["values"].items() if not d]
    return out


def negative(k: str, v: dict) -> bool:
    """A then-entry that passes on any tree without the violation (catalog `negative_checks`)."""
    v = v or {}
    op, val = v.get("op"), v.get("value")
    return (
        (k == "scan_count" and ((op in ("eq", "le") and val == 0) or (op == "lt" and val == 1)))
        or k in ("no_fact", "file_unchanged")
        or (k == "fact" and v.get("count") == 0)
        or (k == "paths" and v.get("exist") is False)
        or (k in ("output_contains", "file_contains") and v.get("negate") is True)
        or (k == "field" and op in ("absent", "ne", "not_contains"))
        or (k == "git" and v.get("assert") in ("source_refs_unchanged", "no_git_hook_installed", "no_remote_fetch", "candidate_not_in_head"))
        or (k == "jobs" and v.get("assert") == "absent")
        or (k == "questions_asked" and v.get("count") == 0)
        or (k == "api_call" and v.get("count") == 0)
    )


SOURCE_SCHEMAS = {"packet": ("packet",), "result_json": ("result", "jobs"), "config_effective": ("config",)}


def norm_path(path: str) -> str:
    return re.sub(r"(\[\*\])+", "[*]", re.sub(r"\[(\d+|[a-z_]+=[^\]]*)\]", "[*]", path))


def field_matcher(fields: list[dict]):
    """(schema, row path) -> the fields.yaml entries it names: the entry itself, or an object above it."""
    pats = [(f, re.compile("^" + re.sub(r"(^|\\\.)\\\*(?=\\\.|$)", lambda m: m.group(1) + r"[^.\[]+", re.escape(f["path"])) + "$")) for f in fields]

    def match(schemas: tuple, path: str) -> list[dict]:
        p = norm_path(path)
        exact = [f for f, rx in pats if f["schema"] in schemas and rx.match(p)]
        if exact:
            return exact
        return [f for f, _ in pats if f["schema"] in schemas and f["path"].startswith(p) and f["path"][len(p):][:1] in (".", "[")]

    return match


def field_reads(r: dict) -> list[tuple[tuple, str, bool]]:
    """(schemas, path, exact-only) for every d0 field a row reads, explicitly or through a then-key."""
    out = []
    for g in r.get("given", []):
        if "config" in g and (g["config"] or {}).get("key"):
            out.append((("config",), g["config"]["key"], False))
    blob = json.dumps(r.get("then", [])) + json.dumps(r.get("when", {}))
    out += [(("packet",), p, False) for p in re.findall(r"\$packet\.([A-Za-z0-9_.\[\]*=-]+)", blob)]
    if "$acceptance_ids" in blob:
        out.append((("packet",), "acceptance[*].id", True))
    for step in r.get("then", []):
        for k, v in step.items():
            v = v or {}
            if k == "field" and v.get("source") in SOURCE_SCHEMAS and v.get("op") != "absent":
                out.append((SOURCE_SCHEMAS[v["source"]], v["path"], False))
                for m in re.finditer(r"\[([a-z_]+)=[^\]]*\]", v["path"]):  # selecting by a key reads that key
                    out.append((SOURCE_SCHEMAS[v["source"]], norm_path(v["path"][: m.start()]) + f"[*].{m.group(1)}", True))
            elif k == "met":
                out += [(("result",), "items[*].status", True)] + ([(("result",), "items[*].id", True)] if v.get("item") else [])
            elif k in ("fact", "no_fact"):
                out += [(("result",), "facts[*].kind", True)] + ([(("result",), "facts[*].detail", True)] if v.get("detail") else [])
            elif k == "jobs":
                out += [(("jobs",), "jobs[*].role", True), (("jobs",), "jobs[*].step", True)]
                if v.get("assert") == "program_only":
                    out.append((("jobs",), "jobs[*].kind", True))
    return out


def unused_catalog(catalog: dict, rows: list[dict]) -> list[str]:
    """Catalog keys and enum values no row uses (comparison operators excepted)."""
    used = set()
    for r in rows:
        for sec, steps in (("given", r.get("given", [])), ("when", [r.get("when", {})]), ("then", r.get("then", []))):
            for step in steps:
                for k, v in step.items():
                    used.add((sec, k))
                    for p, val in (v or {}).items():
                        if isinstance(val, str):
                            used.add((sec, k, p, val))
    out = []
    for sec in ("given", "when", "then"):
        for k, entry in catalog[sec].items():
            if (sec, k) not in used and k != "needs_keyword":
                out.append(f"{sec}.{k}")
            for p, d in (entry.get("params") or {}).items():
                if p == "op" or not isinstance(d.get("values"), dict):
                    continue
                users = [(sec, k, p)] + [(s2, k2, p2) for s2 in ("given", "when", "then") for k2, e2 in catalog[s2].items()
                                         for p2, d2 in (e2.get("params") or {}).items() if d2.get("ref") == f"{k}.{p}"]
                out += [f"{sec}.{k}.{p}.{v}" for v in d["values"] if not any((*u, v) in used for u in users)]
    return out


def row_lint(r: dict, catalog: dict) -> list[str]:
    """Compatibility of a row's then-entries with its when and givens (catalog `after`, `needs_given`, conditionals)."""
    out = []
    when = next(iter(r.get("when") or {}), None)
    givens = {k for g in r.get("given", []) for k in g}
    placeholder = re.compile(r"\$(" + "|".join(catalog["placeholders"]) + r")\b")
    packet_placeholder = re.compile(r"\$(" + "|".join(n for n in catalog["placeholders"] if n != "measure_out") + r")\b")
    if packet_placeholder.search(json.dumps(r.get("then", [])) + json.dumps(r.get("when", {}))) and "packet" not in givens:
        out.append("uses a $packet_sha256, $acceptance_ids or $packet.<path> placeholder without a packet given")
    for name in re.findall(r"\$([a-z_0-9]+)", json.dumps(r.get("then", [])) + json.dumps(r.get("when", {}))):
        if name not in catalog["placeholders"]:
            out.append(f"${name} is not a placeholder in catalog.yaml `placeholders`")
    for step in r.get("then", []):
        for k, v in step.items():
            entry = catalog["then"].get(k, {})
            after = list(entry.get("after", []))
            for c in entry.get("conditional", []):
                if "if_present" in c and c["if_present"] in (v or {}) and "after" in c:
                    after = c["after"]
            if after and when not in after:
                out.append(f"then {k} cannot read the output of when {when}")
            for g in entry.get("needs_given", []):
                if g not in givens:
                    out.append(f"then {k} needs a {g} given")
    return out


def fixture_ids(r: dict) -> list[tuple[str, str]]:
    out = []
    for g in r.get("given", []):
        for k, v in g.items():
            v = v or {}
            for name in ("state", "plant", "fixture", "question"):
                if name in v and k != "config":
                    out.append((f"{k}.{name}", f"{v.get('name', '')}:{v[name]}" if k == "repo" else str(v[name])))
    return out


# ---------- sources ----------


def section0_ids() -> list[str]:
    text = SPEC.read_text()
    sec = text.split("## 0.", 1)[1].split("\n## 1.", 1)[0]
    return re.findall(r"\*\*((?:G|P|R)\d+)\.\*\*", sec)


def qbc_ids() -> tuple[list[str], list[str]]:
    live, withdrawn = [], []
    for n, body in re.findall(r"^- QBC-(\d+)\.\s*(.*)$", SPEC.read_text(), re.M):
        (withdrawn if body.startswith("Withdrawn") else live).append(f"QBC-{n}")
    return live, withdrawn


def plan_tasks() -> dict[str, dict]:
    """Task id -> {title, proves, leaves: {n: text}}. Leaves are the leaf bullets under "Done when", numbered from 1; a stated outcome on the "Done when" line itself, before its sub-bullets, is leaf 0."""
    tasks: dict[str, dict] = {}
    cur = None
    in_done = False
    bullets: list[tuple[int, str]] = []

    def close():
        if cur is None:
            return
        leaves = {}
        n = 0
        for i, (ind, txt) in enumerate(bullets):
            nxt = bullets[i + 1][0] if i + 1 < len(bullets) else -1
            if nxt <= ind:
                n += 1
                leaves[n] = txt
        if tasks[cur].get("lead_leaf"):
            leaves[0] = tasks[cur]["lead_leaf"]
        tasks[cur]["leaves"] = dict(sorted(leaves.items()))

    for line in PLAN.read_text().splitlines():
        m = re.match(r"^- \[ \] \*\*([a-h]\d+)\.\s*(.*?)\*\*", line)
        if m:
            close()
            cur, in_done, bullets = m.group(1), False, []
            tasks[cur] = {"title": m.group(2), "proves": [], "lead": ""}
            continue
        if cur is None:
            continue
        if line.startswith("#") or (line and not line.startswith(" ")):
            close()
            cur = None
            continue
        if re.match(r"^  - Proves:", line):
            tasks[cur]["proves"] = re.findall(r"\b(?:[GPR]\d+)\b", line.split("QBC")[0]) + [
                f"QBC-{q}" for q in re.findall(r"\d+", line.split("QBC:", 1)[1])
            ]
            continue
        if re.match(r"^  - Size:", line):
            in_done = False
            continue
        dm = re.match(r"^  - Done when(.*)$", line)
        if dm:
            in_done = True
            lead = dm.group(1).strip().rstrip(":").lstrip(",").strip()
            tasks[cur]["lead"] = lead
            if lead and not line.rstrip().endswith(":"):
                bullets.append((2, lead))  # an inline "Done when X." is the task's only leaf
            elif len(lead) > 40:
                tasks[cur]["lead_leaf"] = lead  # a stated outcome before the sub-bullets is leaf 0
            continue
        if in_done:
            bm = re.match(r"^( +)- (.*)$", line)
            if bm and len(bm.group(1)) >= 2:
                bullets.append((len(bm.group(1)), bm.group(2).strip()))
    close()
    return tasks


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def spec_refs() -> dict[str, str]:
    """spec_ref id -> text, from packet-standards.md: each Applied-table row of each stage
    section ("<stage>.<part slug>"; the common table is "common") and each enforcement
    mechanism ("enforce.<n>")."""
    refs: dict[str, str] = {}
    stage, applied = None, False
    for line in STANDARDS.read_text().splitlines():
        h2 = re.match(r"^## (.*)$", line)
        if h2:
            title = h2.group(1)
            m = re.match(r"^(L\d|Review|Common)\b", title)
            stage = None if not m else {"Review": "review", "Common": "common"}.get(m.group(1), m.group(1))
            applied = stage == "common"
            continue
        if re.match(r"^### ", line):
            applied = stage is not None and line.strip() == "### Applied"
            continue
        if stage and applied:
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
            if cells and not set(cells[0]) <= set("-: ") and cells[0] not in ("Part", "Packet part", "Concern"):
                refs[f"{stage}.{slug(cells[0])}"] = f"{cells[0]}: {cells[1]}"
        m = re.match(r"^(\d+)\. \*\*(.+?)\*\*", line)
        if m:
            refs[f"enforce.{m.group(1)}"] = m.group(2).rstrip(".")
    return refs


# ---------- schema ----------


def param_schema(p: dict, catalog: dict) -> dict:
    t = p["type"]
    if "ref" in p:
        sec_key, param = p["ref"].split(".")
        for kind in ("given", "when", "then"):
            if sec_key in catalog[kind]:
                return {"enum": list(catalog[kind][sec_key]["params"][param]["values"])}
    if t == "enum":
        return {"enum": list(p["values"])}
    if t == "id":
        return {"type": "string", "pattern": ID_RE}
    if t == "key":
        return {"type": "string", "pattern": KEY_RE}
    if t == "string":
        return {"type": "string", "minLength": 1}
    if t == "integer":
        s = {"type": "integer"}
        if "minimum" in p:
            s["minimum"] = p["minimum"]
        return s
    if t in ("number", "boolean"):
        return {"type": t}
    if t == "any":
        return {}
    if t == "object":
        fields = p["fields"]
        return {"type": "object", "additionalProperties": False,
                "required": [k for k, v in fields.items() if v.get("required", True)],
                "properties": {k: param_schema(v, catalog) for k, v in fields.items()}}
    if t == "list":
        return {"type": "array", "minItems": 1, "items": param_schema({"type": p["items"]}, catalog)}
    raise ValueError(f"unknown param type {t}")


def step_schema(section: dict, catalog: dict, title: str) -> dict:
    props = {}
    for key, entry in section.items():
        params = entry.get("params", {})
        props[key] = {
            "description": entry["meaning"],
            "type": "object",
            "additionalProperties": False,
            "required": [k for k, v in params.items() if v.get("required", True)],
            "properties": {k: param_schema(v, catalog) for k, v in params.items()},
        }
        conds = []
        for c in entry.get("conditional", []):
            if "require_one_of" in c:
                props[key].setdefault("anyOf", []).extend({"required": [x]} for x in c["require_one_of"])
                continue
            if "if" in c:
                cond = {"properties": {k: {"const": v} for k, v in c["if"].items()}, "required": list(c["if"])}
            else:
                cond = {"required": [c["if_present"]]}
            conds.append({"if": cond, "then": {"required": c["require"]}})
        if conds:
            props[key]["allOf"] = conds
    return {
        "title": title,
        "type": "object",
        "minProperties": 1,
        "maxProperties": 1,
        "propertyNames": {"enum": sorted(section)},
        "properties": props,
    }


def build_schema(catalog: dict, trace_ids: list[str], refs: dict[str, str]) -> dict:
    # One definition of an acceptance row, shared by the work packet (acceptance[*]) and the plugin's own
    # criteria files. A criteria-file row is this row plus the plan's required fields (criteria_row).
    row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "scenario", "given", "when", "then", "traces_to", "verification"],
        "properties": {
            "id": {"type": "string", "pattern": r"^[A-Za-z0-9._-]+-AC\d+$"},
            "scenario": {"type": "string", "minLength": 1},
            "given": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/given"}},
            "when": {"$ref": "#/$defs/when"},
            "then": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/then"}},
            "traces_to": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": trace_ids}},
            "verification": {"enum": sorted(catalog["verification"])},
            "deterministic": {"type": "boolean"},
            "covers": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "integer", "minimum": 0}},
            "spec_ref": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": sorted(refs)}},
            "plan_gap": {"type": "string", "minLength": 1},
            "red_on_main": {"type": "string", "minLength": 1},
        },
    }
    criteria_row = {
        "allOf": [{"$ref": "#/$defs/row"}],
        "required": ["deterministic"],
        "anyOf": [{"required": ["covers"]}, {"required": ["spec_ref"]}],
        "properties": {"id": {"pattern": r"^[a-h]\d+-AC\d+$"}, "scenario": {"maxLength": 160}},
        "if": {"properties": {"id": {"pattern": "^h"}}},
        "else": {"properties": {"deterministic": {"const": True}}},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "docs/atdd/criteria.schema.json",
        "title": "Acceptance criteria of one plan slice (generated from catalog.yaml by build.py; do not edit)",
        "type": "object",
        "additionalProperties": False,
        "required": ["slice", "acceptance"],
        "properties": {
            "slice": {"enum": list(SLICES)},
            "acceptance": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/criteria_row"}},
        },
        "$defs": {
            "row": row,
            "criteria_row": criteria_row,
            "given": step_schema(catalog["given"], catalog, "given"),
            "when": step_schema(catalog["when"], catalog, "when"),
            "then": step_schema(catalog["then"], catalog, "then"),
        },
    }


def render_fields(fields: dict, freads: dict, key) -> str:
    out = ["# d0 field names", "",
           "The only field paths the packet, the result JSON, its jobs and the config may have, as the owner decided them for d0 "
           "(2026-11-25). Generated by `docs/atdd/build.py` from `docs/atdd/fields.yaml`; do not edit. "
           "Acceptance rows in `docs/atdd/criteria/` may read no other path; `build.py --check` fails on one.", ""]
    for schema, meaning in fields["schemas"].items():
        rows = [f for f in fields["fields"] if f["schema"] == schema]
        out += [f"## {schema}", "", meaning[0].upper() + meaning[1:] + ".", ""]
        cfg = schema == "config"
        out += ["| path | type |" + (" default |" if cfg else "") + " meaning | rows |", "|---|---|" + ("---|" if cfg else "") + "---|---|"]
        for f in rows:
            ids = sorted(set(freads.get((schema, f["path"]), [])), key=key)
            d = f.get("default", "the plan states none") if cfg else None
            d = json.dumps(d) if cfg and not isinstance(d, str) else d
            out.append(f"| `{f['path']}` | {f['type']} |" + (f" {d} |" if cfg else "") + f" {f['meaning']} | {', '.join(ids) or '-'} |")
        out.append("")
    gaps = [f"- {f['schema']} `{f['path']}` ({f['type']}) is a d0 field that no acceptance criterion reads yet."
            for f in fields["fields"] if not freads.get((f["schema"], f["path"]))]
    gaps += [f"- config `{f['path']}` has no default stated in the plan's d9 limits table." for f in fields["fields"]
             if f["schema"] == "config" and "default" not in f and f["type"] not in ("object",)]
    out += ["", "## Gaps", "", "Each line is a d0 field that no acceptance criterion tests, or a config key with no stated default.", ""]
    out += gaps or ["None."]
    return "\n".join(out) + "\n"


# ---------- checks and report ----------


def main() -> int:
    tasks = plan_tasks()
    if "--bullets" in sys.argv:
        for tid, t in tasks.items():
            print(f"{tid} {t['title']}  [proves: {', '.join(t['proves'])}]")
            for n, txt in t["leaves"].items():
                print(f"  {n}. {txt}")
        return 0

    catalog = yaml.safe_load(CATALOG.read_text())
    s0 = section0_ids()
    live_qbc, withdrawn = qbc_ids()
    refs = spec_refs()
    schema = build_schema(catalog, s0 + live_qbc, refs)
    SCHEMA.write_text(json.dumps(schema, indent=2) + "\n")
    errors: list[str] = []
    checked = subprocess.run([sys.executable, "-m", "check_jsonschema", "--schemafile", str(SCHEMA), *map(str, sorted(CRITERIA.glob("*.yaml")))], capture_output=True, text=True)
    if checked.returncode:
        errors += [ln.strip()[:300] for ln in (checked.stdout + checked.stderr).splitlines() if ln.strip()]

    rows: list[dict] = []
    for s in SLICES:
        f = CRITERIA / f"{s}.yaml"
        if not f.exists():
            errors.append(f"{f.relative_to(ROOT)}: missing")
            continue
        doc = yaml.safe_load(f.read_text())
        if isinstance(doc, dict) and doc.get("slice") != s:
            errors.append(f"{f.name}: slice must be {s!r}")
        for r in (doc or {}).get("acceptance", []) or []:
            if isinstance(r, dict):
                rows.append(r)

    errors += catalog_lint(catalog)
    fields = yaml.safe_load(FIELDS.read_text())
    flist = fields["fields"]
    seen_f = set()
    for f in flist:
        if f["schema"] not in fields["schemas"]:
            errors.append(f"fields.yaml {f['path']}: schema {f['schema']!r} is not one of {sorted(fields['schemas'])}")
        if (f["schema"], f["path"]) in seen_f:
            errors.append(f"fields.yaml {f['schema']} {f['path']}: listed twice")
        seen_f.add((f["schema"], f["path"]))
    fmatch = field_matcher(flist)
    freads: dict[tuple, list[str]] = defaultdict(list)
    seen = set()
    by_task: dict[str, list[dict]] = defaultdict(list)
    incompatible, weak, full_proves = [], [], []
    bound_parts = [0, 0]  # teaching parts with identifier tokens, all teaching parts
    unbound: list[str] = []  # rows with a teaching assertion that names no identifier token
    inventory: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    covered: dict[str, set[int]] = defaultdict(set)
    untaught, needs_kw, gaps, nondet = [], [], [], []
    for r in rows:
        rid = r.get("id", "?")
        task = rid.split("-AC")[0]
        if rid in seen:
            errors.append(f"{rid}: duplicate id")
        seen.add(rid)
        if task not in tasks:
            errors.append(f"{rid}: no task {task} in the plan")
            continue
        by_task[task].append(r)
        incompatible += [f"{rid}: {m}" for m in row_lint(r, catalog)]
        for schemas, path, _ in field_reads(r):
            hit = fmatch(schemas, path)
            if not hit:
                errors.append(f"[d0-fields] {rid}: {'/'.join(schemas)} path `{path}` is not a d0 field -> use a path from "
                              f"docs/atdd/fields.yaml (rendered in d0-fields.md); add a new one there only with the owner's decision . fields.yaml")
            elif norm_path(path) == hit[0]["path"] or len(hit) == 1 or any(re.search(r"(^|\.)\*(\.|$)", h["path"]) for h in hit):
                for h in hit[:1]:
                    freads[(h["schema"], h["path"])].append(rid)
        thens_all = [(k, v) for step in r.get("then", []) for k, v in step.items()]
        if thens_all and all(negative(k, v) for k, v in thens_all) and not r.get("red_on_main"):
            incompatible.append(f"{rid}: only negative checks and no red_on_main (catalog negative_checks)")
        for k, v in fixture_ids(r):
            inventory[k][v] += 1
        for step in r.get("then", []):
            for k, v in step.items():
                if k in TEACHING:
                    weak += [f"{rid}: {k}.{part} = {v[part]!r}" for part in ("wrong", "right", "prevent")
                             if isinstance((v or {}).get(part), str) and weak_part(v[part])]
                    for part in ("wrong", "right", "prevent"):
                        if isinstance((v or {}).get(part), str):
                            bound_parts[1] += 1
                            bound_parts[0] += bool(identifiers(v[part]))
                    if not any(identifiers((v or {}).get(p) or "") for p in ("wrong", "right", "prevent")):
                        unbound.append(rid)
        proves = set(tasks[task]["proves"])
        if len(proves) >= 4 and proves <= set(r.get("traces_to", [])):
            full_proves.append(rid)
        for n in r.get("covers", []):
            if n not in tasks[task]["leaves"]:
                errors.append(f"{rid}: covers {n}, but {task} has {len(tasks[task]['leaves'])} leaves")
            covered[task].add(n)
        thens = [(k, v or {}) for step in r.get("then", []) for k, v in step.items()]
        rejects = [k for k, v in thens if k in REJECTING and REJECTING[k](v)]
        if rejects and not any(k in TEACHING for k, _ in thens):
            untaught.append(f"{rid} ({', '.join(rejects)})")
        steps = list(r.get("given", [])) + [r.get("when", {})] + list(r.get("then", []))
        for step in steps:
            if isinstance(step, dict) and "needs_keyword" in step:
                needs_kw.append((rid, step["needs_keyword"]["reason"]))
        if r.get("plan_gap"):
            gaps.append((rid, r["plan_gap"]))
        if r.get("deterministic") is False:
            nondet.append(rid)

    traced: dict[str, list[str]] = defaultdict(list)
    by_ref: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        for ref in r.get("spec_ref", []):
            by_ref[ref].append(r["id"])
    errors += [f"catalog value no row uses: {u}" for u in unused_catalog(catalog, rows)]
    exempt = catalog.get("spec_ref_exempt", {})
    errors += [f"catalog spec_ref_exempt {x}: no such spec_ref" for x in exempt if x not in refs]
    refs_uncovered = [x for x in refs if not by_ref.get(x) and x not in exempt]
    for r in rows:
        for t in r.get("traces_to", []):
            traced[t].append(r["id"])

    no_rows = [t for t in tasks if t not in by_task]
    thin = []
    for t, info in tasks.items():
        miss = sorted(set(info["leaves"]) - covered[t])
        if miss and t in by_task:
            thin.append((t, miss))
    s0_untraced = [i for i in s0 if not traced.get(i)]
    qbc_untraced = [q for q in live_qbc if not traced.get(q)]

    def key(rid):
        t, n = rid.split("-AC")
        return (t[0], int(t[1:]), int(n))

    out = ["# ATDD coverage", "",
           "Generated by `docs/atdd/build.py` from `catalog.yaml`, `criteria/*.yaml`, the plan and the spec. Do not edit.", "",
           "Validation command (JSON Schema draft 2020-12, `check-jsonschema`), from the repository root:", "",
           "```", "uv run --script docs/atdd/build.py --check", "```", "",
           f"Result: {len(errors)} schema, catalog or reference errors; {len(untaught)} rejections without teaching; "
           f"{len(incompatible)} then-entries that cannot read their when or lack a given; "
           f"{len(weak)} one-word generic teaching parts.", "",
           f"Teaching parts: {bound_parts[1]}; {bound_parts[0]} name at least one identifier token that the message must contain "
           f"(catalog `terms.teaching match`); the rest state intent only and rely on the teaching shape plus the approval snapshot. "
           f"Teaching assertions naming no identifier at all ({len(unbound)}): {', '.join(sorted(set(unbound), key=key)) or 'none'}.", ""]
    for e in errors:
        out.append(f"- ERROR {e}")
    for u in untaught:
        out.append(f"- UNTAUGHT {u}")
    for u in incompatible:
        out.append(f"- INCOMPATIBLE {u}")
    for u in weak:
        out.append(f"- WEAK-TEACHING {u}")
    out += ["", "## Counts", "", "| Slice | Tasks | Tasks with rows | Criteria |", "|---|---|---|---|"]
    for s in SLICES:
        ts = [t for t in tasks if t[0] == s]
        out.append(f"| {s} | {len(ts)} | {sum(1 for t in ts if t in by_task)} | {sum(len(by_task[t]) for t in ts)} |")
    out.append(f"| all | {len(tasks)} | {len(by_task)} | {len(rows)} |")
    out += ["", "| Catalog | Entries |", "|---|---|"]
    for k in ("given", "when", "then"):
        out.append(f"| {k} | {len(catalog[k])} |")
    meth = defaultdict(int)
    for r in rows:
        meth[r.get("verification")] += 1
    out += ["", "Verification: " + ", ".join(f"{m} {meth[m]}" for m in sorted(catalog["verification"])) + ".",
            f"Non-deterministic rows (slice h only): {', '.join(sorted(nondet, key=key)) or 'none'}.", ""]

    out += ["## §0 items × criteria", "",
            "| Item | " + " | ".join(SLICES) + " | Total | Criteria |", "|---|" + "---|" * (len(SLICES) + 2)]
    for i in s0:
        ids = sorted(traced.get(i, []), key=key)
        per = [str(sum(1 for x in ids if x[0] == s)) for s in SLICES]
        out.append(f"| {i} | " + " | ".join(per) + f" | {len(ids)} | {', '.join(ids)} |")
    out += ["", f"§0 items traced by no criterion: {', '.join(s0_untraced) or 'none'}.", "",
            f"QBC ids traced by no criterion: {', '.join(qbc_untraced) or 'none'}. Withdrawn, not traceable: {', '.join(withdrawn)}.", ""]

    out += ["## Tasks whose \"done when\" has no row", "", ", ".join(no_rows) or "None.", "",
            "## Done-when leaves without a row", "",
            "Leaves are numbered by `build.py --bullets`.", ""]
    out += [f"- {t}: leaves {', '.join(map(str, m))}" for t, m in thin] or ["None."]
    out += ["", "## packet-standards.md stage outputs and enforcement × criteria", "",
            "Rows that prove a stage-output row or an enforcement mechanism of `docs/spec/packet-standards.md` "
            "(`spec_ref`); rows without `covers` have no \"done when\" leaf in the plan. Exempt rows are listed in the catalog's `spec_ref_exempt` with the reason.", "",
            "| spec_ref | Criteria |", "|---|---|"]
    out += [f"| {x} | {', '.join(sorted(by_ref.get(x, []), key=key)) or ('exempt: ' + exempt[x] if x in exempt else 'NONE')} |" for x in refs]
    share = defaultdict(lambda: [0, 0])
    for rid in full_proves:
        share[rid.split("-AC")[0]][0] += 1
    for t, rs in by_task.items():
        share[t][1] = len(rs)
    out += ["", "## Rows tracing their task's whole Proves line", "",
            "Rows whose `traces_to` holds every id of a task's Proves line (tasks with 4 or more ids). "
            "A row should cite only what it proves; a high share means the traces were copied, not judged.", ""]
    out += [f"- {t}: {a}/{n}" for t, (a, n) in sorted(share.items(), key=lambda x: key(x[0] + "-AC0")) if a] or ["None."]
    out += ["", "## Fixture inventory", "",
            "Distinct fixture ids the rows name, with how many rows name each; near-duplicates should be merged.", ""]
    for k in sorted(inventory):
        out.append(f"- {k}: " + ", ".join(f"{v} ({n})" for v, n in sorted(inventory[k].items())))
    out += ["", "## needs-keyword", ""]
    out += [f"- {rid}: {reason}" for rid, reason in sorted(needs_kw, key=lambda x: key(x[0]))] or ["None."]
    out += ["", "## Plan wording too vague or prescribing design", ""]
    out += [f"- {rid}: {g}" for rid, g in sorted(gaps, key=lambda x: key(x[0]))] or ["None."]
    COVERAGE.write_text("\n".join(out) + "\n")
    FIELDS_MD.write_text(render_fields(fields, freads, key))

    print(f"{len(rows)} criteria; {len(errors)} errors; {len(untaught)} untaught; "
          f"no rows: {no_rows or 'none'}; uncovered leaves: {len(thin)} tasks; "
          f"§0 untraced: {s0_untraced or 'none'}; spec_ref uncovered: {refs_uncovered or 'none'}; needs-keyword: {len(needs_kw)}; "
          f"incompatible: {len(incompatible)}; weak teaching: {len(weak)}; whole-Proves rows: {len(full_proves)}")
    if "--check" in sys.argv and (errors or untaught or no_rows or thin or s0_untraced or refs_uncovered or incompatible or weak or needs_kw):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
