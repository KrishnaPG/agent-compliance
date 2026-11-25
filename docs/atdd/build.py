# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4.18", "pyyaml>=6"]
# ///
"""Generate criteria.schema.json from catalog.yaml, validate every criteria file, write coverage.md.

Mechanical, no agent. Run from the repository root:

    uv run --script docs/atdd/build.py            # regenerate schema and coverage.md
    uv run --script docs/atdd/build.py --check    # also exit 1 when anything is invalid or uncovered
    uv run --script docs/atdd/build.py --bullets  # print each task's numbered "Done when" leaves
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = ROOT / "docs/spec/quality-by-construction.md"
PLAN = ROOT / "docs/plan/v2-work-plan.md"
CATALOG = HERE / "catalog.yaml"
SCHEMA = HERE / "criteria.schema.json"
COVERAGE = HERE / "coverage.md"
CRITERIA = HERE / "criteria"
SLICES = "abcdefgh"
STANDARDS = ROOT / "docs/spec/packet-standards.md"

ID_RE = r"^[a-z0-9][a-z0-9_.-]*$"
KEY_RE = r"^[A-Za-z0-9_.\[\]*-]+$"
REJECTING = {
    "exit_code": lambda p: p.get("code", 0) != 0,
    "met": lambda p: p.get("status") in {"unmet", "stuck", "not_checked"},
    "schema_valid": lambda p: p.get("valid") is False,
    "refused": lambda p: True,
}
TEACHING = {"teaching", "refused"}


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


def spec_refs() -> list[str]:
    """The stage-output rows and enforcement mechanisms of packet-standards.md, as spec_ref ids."""
    text = STANDARDS.read_text()
    stages = re.findall(r"^\| (L\d|Review)\b", text, re.M)
    mech = re.findall(r"^(\d+)\. \*\*", text.split("How \"one packet", 1)[1], re.M) if "How \"one packet" in text else []
    return [f"stage:{'review' if s == 'Review' else s}" for s in stages] + [f"enforce:{n}" for n in mech]


# ---------- schema ----------


def param_schema(p: dict, catalog: dict) -> dict:
    t = p["type"]
    if "ref" in p:
        sec_key, param = p["ref"].split(".")
        for kind in ("given", "when", "then"):
            if sec_key in catalog[kind]:
                return {"enum": catalog[kind][sec_key]["params"][param]["values"]}
    if t == "enum":
        return {"enum": p["values"]}
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
    return {
        "title": title,
        "type": "object",
        "minProperties": 1,
        "maxProperties": 1,
        "propertyNames": {"enum": sorted(section)},
        "properties": props,
    }


def build_schema(catalog: dict, trace_ids: list[str], refs: list[str]) -> dict:
    row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "scenario", "given", "when", "then", "traces_to", "method", "deterministic"],
        "anyOf": [{"required": ["covers"]}, {"required": ["spec_ref"]}],
        "properties": {
            "id": {"type": "string", "pattern": r"^[a-h]\d+-AC\d+$"},
            "scenario": {"type": "string", "minLength": 1, "maxLength": 160},
            "covers": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "integer", "minimum": 0}},
            "given": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/given"}},
            "when": {"$ref": "#/$defs/when"},
            "then": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/then"}},
            "traces_to": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": trace_ids}},
            "method": {"enum": sorted(catalog["methods"])},
            "deterministic": {"type": "boolean"},
            "spec_ref": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": refs}},
            "plan_gap": {"type": "string", "minLength": 1},
        },
        "if": {"properties": {"id": {"pattern": "^h"}}},
        "else": {"properties": {"deterministic": {"const": True}}},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "docs/atdd/criteria.schema.json",
        "title": "Acceptance criteria of one plan slice (generated from catalog.yaml by build.py; do not edit)",
        "type": "object",
        "additionalProperties": False,
        "required": ["slice", "criteria"],
        "properties": {
            "slice": {"enum": list(SLICES)},
            "criteria": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/row"}},
        },
        "$defs": {
            "row": row,
            "given": step_schema(catalog["given"], catalog, "given"),
            "when": step_schema(catalog["when"], catalog, "when"),
            "then": step_schema(catalog["then"], catalog, "then"),
        },
    }


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
    validator = Draft202012Validator(schema)

    errors: list[str] = []
    rows: list[dict] = []
    for s in SLICES:
        f = CRITERIA / f"{s}.yaml"
        if not f.exists():
            errors.append(f"{f.relative_to(ROOT)}: missing")
            continue
        doc = yaml.safe_load(f.read_text())
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            errors.append(f"{f.name}: /{'/'.join(map(str, e.path))}: {e.message[:200]}")
        if isinstance(doc, dict) and doc.get("slice") != s:
            errors.append(f"{f.name}: slice must be {s!r}")
        for r in (doc or {}).get("criteria", []) or []:
            if isinstance(r, dict):
                rows.append(r)

    seen = set()
    by_task: dict[str, list[dict]] = defaultdict(list)
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
    refs_uncovered = [x for x in refs if not by_ref.get(x)]
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
           "Validation command (JSON Schema draft 2020-12, `jsonschema` library), from the repository root:", "",
           "```", "uv run --script docs/atdd/build.py --check", "```", "",
           f"Result: {len(errors)} schema or reference errors; {len(untaught)} rejections without teaching.", ""]
    for e in errors:
        out.append(f"- ERROR {e}")
    for u in untaught:
        out.append(f"- UNTAUGHT {u}")
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
        meth[r.get("method")] += 1
    out += ["", "Methods: " + ", ".join(f"{m} {meth[m]}" for m in sorted(catalog["methods"])) + ".",
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
            "(`spec_ref`); rows without `covers` have no \"done when\" leaf in the plan yet.", "",
            "| spec_ref | Criteria |", "|---|---|"]
    out += [f"| {x} | {', '.join(sorted(by_ref.get(x, []), key=key)) or 'NONE'} |" for x in refs]
    out += ["", "## needs-keyword", ""]
    out += [f"- {rid}: {reason}" for rid, reason in sorted(needs_kw, key=lambda x: key(x[0]))] or ["None."]
    out += ["", "## Plan wording too vague or prescribing design", ""]
    out += [f"- {rid}: {g}" for rid, g in sorted(gaps, key=lambda x: key(x[0]))] or ["None."]
    COVERAGE.write_text("\n".join(out) + "\n")

    print(f"{len(rows)} criteria; {len(errors)} errors; {len(untaught)} untaught; "
          f"no rows: {no_rows or 'none'}; uncovered leaves: {len(thin)} tasks; "
          f"§0 untraced: {s0_untraced or 'none'}; spec_ref uncovered: {refs_uncovered or 'none'}; needs-keyword: {len(needs_kw)}")
    if "--check" in sys.argv and (errors or untaught or no_rows or thin or s0_untraced or refs_uncovered):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
