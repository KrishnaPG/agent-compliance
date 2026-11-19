"""SG-19: the rule catalog's checks run with every item's measurement.

The catalog ships checks beside its rules: ``<catalog root>/checks/index.json`` lists
``{rule, pack, ecosystem, tool, file, binds}``; ``file`` is an ast-grep rule file. This module
finds the catalog root, detects the stack, runs the checks over the item's own and changed
files and returns ``rules.violations``; it also chooses the judgment rules of a work packet,
lists the suppressions a ref added and builds the class-share facts.

OSS checked (2026-11-19): ast-grep 0.51.3 (MIT, release asset digest pinned in
``checkers.json``) runs a rule file with ``scan --rule FILE --json PATHS`` and needs no
project config; Semgrep and ruff/eslint were not chosen as the one runner because ast-grep
is a single static binary for Python, TypeScript and SQL-adjacent trees with one JSON shape.
Nothing here is a linter: the harness only downloads, verifies, runs and counts.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from bhcore import (
    HARNESS_DIR,
    PLUGIN_ROOT,
    HarnessError,
    _git,
    _own_paths,
    _standard_layers,
    all_findings,
    load_features,
    packet_context,
)

EXT = {
    "python": (".py",),
    "typescript": (".ts", ".tsx", ".js", ".jsx", ".mjs"),
    "sql": (".sql",),
}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}
RULE_ID = r"[A-Z]{2}-\d+"
ROW = re.compile(rf"^\|\s*({RULE_ID})\s*\|\s*(.+?)\s*\|")
# Facts a check may bind, each inferred from the code: files that define routes or an app.
ENTRY = re.compile(r"\b(?:APIRouter|FastAPI)\(|\bRouter\(")
MARKERS = (
    r"noqa|nosemgrep|type:\s*ignore|eslint-disable|ast-grep-ignore|pylint:\s*disable"
    r"|@ts-ignore|@ts-expect-error|nosec"
)
# Catalog domains a work item touches, by words in its id, paths and kind (simple on purpose).
WORDS = {
    r"queue|event|outbox|webhook|message|relay|consumer": ("HO", "RL"),
    r"auth|token|secret|login|tenant|key": ("ID",),
    r"db|sql|migrat|schema|store|repo": ("DS", "LC"),
    r"worker|lock|concurr|thread|async": ("CI", "RL"),
    r"log|metric|trace|alert": ("OB",),
    r"bench|perf|cache": ("PF",),
    r"deploy|release|image": ("SC", "PL"),
}
BASE_DOMAINS = ("NO", "CF")


# ---------------------------------------------------------------- catalog and stack


def catalog_root(cfg: Any) -> Path:
    """The directory holding ``catalog/`` and ``checks/``: ``standards.catalog`` when it is a
    path (it holds a ``/``), else this plugin's own catalog (unset, a ``<placeholder>`` or
    the plugin's name), so a project configures nothing to get the rules and checks."""
    c = cfg.data.get("standards", {}).get("catalog", "")
    return (cfg.dir / c).resolve() if "/" in c and not c.startswith("<") else PLUGIN_ROOT


def load_index(cfg: Any) -> list[dict[str, Any]]:
    """The catalog's checks (``checks/index.json``); none when the catalog ships none."""
    root = catalog_root(cfg)
    try:
        doc = json.loads((root / "checks" / "index.json").read_text())
        return [dict(c, root=str(root)) for c in doc.get("checks", [])]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def _files(root: Path) -> list[Path]:
    out: list[Path] = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in SKIP_DIRS]
        out += [Path(d) / n for n in names]
    return out


def detect(root: Path) -> tuple[set[str], set[str]]:
    """(ecosystems, packs) the project's stack shows: pyproject.toml or *.py is python,
    package.json or tsconfig.json typescript, *.sql or a migrations directory sql (and the
    postgresql pack)."""
    names: set[str] = set()
    migrations = False
    for _, dirs, files in os.walk(root):
        migrations |= "migrations" in dirs
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in SKIP_DIRS]
        names |= set(files)
    eco = set()
    if "pyproject.toml" in names or any(n.endswith(".py") for n in names):
        eco.add("python")
    if names & {"package.json", "tsconfig.json"}:
        eco.add("typescript")
    sql = migrations or any(n.endswith(".sql") for n in names)
    if sql:
        eco.add("sql")
    return eco, ({"postgresql"} if sql else set())


def entry_modules(root: Path) -> list[str]:
    """Files that define routes or an app (FastAPI/Starlette ``APIRouter``/``FastAPI(``,
    Express ``Router(``): the trust-boundary entry modules, inferred from the code."""
    out = []
    for p in _files(root):
        if p.suffix in EXT["python"] + EXT["typescript"] and p.stat().st_size < 1_000_000:
            try:
                if ENTRY.search(p.read_text(errors="ignore")):
                    out.append(p.relative_to(root).as_posix())
            except OSError:
                pass
    return sorted(out)


OPT_OUT = re.compile(rf"^- ({RULE_ID}) not-applicable: (.*\S)\s*$")


def _opt_outs(cfg: Any) -> dict[str, str]:
    """Rules the overlay opts out of the checks, in the catalog's form (checks/README.md):
    lines ``- <RULE-ID> not-applicable: <reason>`` under the heading ``## Check opt-outs``.
    ``{rule: reason}``; a line without a reason opts nothing out."""
    out: dict[str, str] = {}
    ov = _standard_layers(cfg).get("overlay")
    inside = False
    for line in ov.read_text(errors="ignore").splitlines() if ov and ov.is_file() else []:
        if line.startswith("#"):
            inside = line.rstrip() == "## Check opt-outs"
        elif inside and (m := OPT_OUT.match(line)):
            out[m.group(1)] = m.group(2).strip()
    return out


def _selected(cfg: Any, root: Path) -> list[dict[str, Any]]:
    """Checks that apply: base ones, and ecosystem/pack ones when the stack is detected."""
    eco, packs = detect(root)
    packs |= set(cfg.data.get("standards", {}).get("packs", []))
    out = [c for c in load_index(cfg) if c["ecosystem"] in eco and c["pack"] in {"base"} | packs]
    off = _opt_outs(cfg)
    return [c for c in out if c["rule"] not in off]


def _facts(root: Path) -> dict[str, list[str]]:
    return {"entry_modules": entry_modules(root)}


def unbound_gaps(cfg: Any) -> list[dict[str, Any]]:
    """Owner-decides gaps for project facts a selected check binds and the code does not show."""
    if not load_index(cfg):
        return []
    facts, need = _facts(cfg.dir), {}
    for c in _selected(cfg, cfg.dir):
        for f in c.get("binds", []):
            if not facts.get(f):
                need.setdefault(f, []).append(c["rule"])
    return [
        {
            "id": f"check:unsettled-area:rules-{f}",
            "kind": "unsettled-area",
            "summary": f"project fact {f} is not shown by the code; checks {', '.join(sorted(r))} are not run",
            "tag": "owner-decides",
            "evidence": [],
            "source": "check",
            "looked_in": ["route or app definitions (APIRouter, FastAPI(, Router()"],
            "area": f,
        }
        for f, r in sorted(need.items())
    ]


# ---------------------------------------------------------------- the checker


def checker(cfg: Any) -> tuple[list[str] | None, str, str]:
    """(command, version label, why-not). ``checks.checker`` in the config overrides the pinned
    tool (tests); else the pinned release is downloaded once and verified by sha256."""
    own = cfg.data.get("checks", {}).get("checker")
    if own:
        return [str((cfg.dir / own).resolve())], "configured", ""
    spec = json.loads((HARNESS_DIR / "checkers.json").read_text())["ast-grep"]
    cache = Path.home() / ".cache" / "brick-harness" / "bin" / f"ast-grep-{spec['version']}"
    try:
        return [str(ensure(spec, cache))], f"ast-grep {spec['version']}", ""
    except HarnessError as e:
        return None, "", str(e)


def ensure(spec: dict[str, Any], cache: Path) -> Path:
    """The pinned binary in ``cache``, downloaded and sha256-verified on first use. A digest
    mismatch leaves nothing in the cache and raises (a supply-chain check, not a gate)."""
    exe = cache / spec["member"]
    zpath = cache / "release.zip"
    if not (spec["platform"] == f"{platform.system()}-{platform.machine()}".lower()):
        raise HarnessError(
            f"checker: no pinned release asset for {platform.system()}-{platform.machine()}"
        )
    if not (exe.exists() and zpath.exists() and _sha(zpath) == spec["sha256"]):
        try:
            with urllib.request.urlopen(spec["url"], timeout=120) as r:
                data = r.read()
        except OSError as e:
            raise HarnessError(f"checker: download failed: {e}") from e
        if hashlib.sha256(data).hexdigest() != spec["sha256"]:
            raise HarnessError(
                "checker: sha256 of the downloaded release does not match the pin; not run"
            )
        cache.mkdir(parents=True, exist_ok=True)
        zpath.write_bytes(data)
        with zipfile.ZipFile(zpath) as z:
            exe.write_bytes(z.read(spec["member"]))
        exe.chmod(0o755)
    return exe


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- running the checks


def active(cfg: Any) -> bool:
    """Whether the catalog ships checks (then ``rules.violations == 0`` is part of done)."""
    return bool(load_index(cfg))


def item_targets(cfg: Any, targets: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    """The item's plan targets, plus ``rules.violations == 0`` when the catalog ships checks."""
    mine = [t for t in targets if t["item"] == item]
    return mine + (
        [{"item": item, "metric": "rules.violations", "op": "==", "value": 0}]
        if active(cfg)
        else []
    )


def _scope(root: Path, brick: dict[str, Any], changed: list[str]) -> set[str]:
    """The item's owned files and the files its ref changed (root-relative, existing)."""
    out = {c for c in changed if (root / c).is_file()}
    for p in _own_paths(brick):
        base = root / p.rstrip("/")
        out |= {
            x.relative_to(root).as_posix() for x in ([base] if base.is_file() else _files(base))
        }
    return out


def run_checks(cfg: Any, root: Path, brick: dict[str, Any], changed: list[str]) -> dict[str, Any]:
    """Run the selected checks over the item's scope. Returns ``{violations, error, by_rule,
    findings, skipped, opted_out, checker}``; ``violations`` is None when the checker cannot
    run (then ``error`` says why and the target is unmet)."""
    opted = _opt_outs(cfg)
    out: dict[str, Any] = {"violations": None, "by_rule": {}, "findings": [], "skipped": []}
    out["opted_out"] = opted
    cmd, label, why = checker(cfg)
    if cmd is None:
        return {**out, "error": why}
    out["checker"] = label
    scope, facts = _scope(root, brick, changed), _facts(root)
    timeout = float(cfg.commands_for(brick).get("timeout_s", 600))
    total = 0
    for c in _selected(cfg, root):
        files = sorted(f for f in scope if f.endswith(EXT[c["ecosystem"]]))
        for fact in c.get("binds", []):
            files = [f for f in files if f in facts.get(fact, [])]
            if not facts.get(fact):
                out["skipped"].append({"rule": c["rule"], "why": f"project fact {fact} not found"})
                files = []
        for i in range(0, len(files), 200):
            try:
                p = subprocess.run(
                    [*cmd, "scan", "--rule", str(Path(c["root"]) / c["file"]), "--json", *files[i : i + 200]],
                    cwd=root, capture_output=True, text=True, timeout=timeout,
                )  # fmt: skip
                hits = json.loads(p.stdout or "[]")
                if p.returncode not in (0, 1) or not isinstance(hits, list):
                    raise ValueError(p.stderr.strip()[-200:])
            except (OSError, ValueError, subprocess.TimeoutExpired) as e:
                return {**out, "error": f"rules: checker failed on {c['rule']}: {e}"}
            total += len(hits)
            if hits:
                out["by_rule"][c["rule"]] = out["by_rule"].get(c["rule"], 0) + len(hits)
            out["findings"] += [
                {"rule": c["rule"], "file": h.get("file"), "line": h["range"]["start"]["line"] + 1}
                for h in hits
            ][:20]
    out["findings"] = out["findings"][:20]
    return {**out, "violations": total, "error": None}


def suppressions(cfg: Any, top: Path, sha: str) -> list[dict[str, Any]]:
    """Suppression markers the ref added (``git diff`` added lines): a fact, never scored."""
    pat = re.compile(
        "|".join([MARKERS, *map(re.escape, cfg.data.get("standards", {}).get("suppressions", []))])
    )
    try:
        diff = _git(top, "diff", "-U0", "--no-renames", _git(top, "merge-base", "HEAD", sha), sha)
    except HarnessError:
        return []
    out, path, n = [], "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("@@"):
            n = int(re.search(r"\+(\d+)", line).group(1)) - 1  # type: ignore[union-attr]
        elif line.startswith("+") and path:
            n += 1
            if pat.search(line):
                out.append({"file": path, "line": n, "text": line[1:].strip()[:120]})
    return out[:200]


# ---------------------------------------------------------------- the work packet's rules


def rule_rows(cfg: Any, packs: set[str]) -> dict[str, str]:
    """``{rule id: one line}`` from the catalog's base rows, the packs' rows and the overlay."""
    root = catalog_root(cfg)
    files = sorted((root / "catalog" / "base").glob("*.md"))
    for p in sorted(packs):
        files += sorted((root / "catalog" / "packs" / p).glob("*.md"))
    files += [p for p in _standard_layers(cfg).values() if p.is_file()]
    rows: dict[str, str] = {}
    for f in files:
        for line in f.read_text(errors="ignore").splitlines():
            m = ROW.match(line)
            if m:
                rows.setdefault(m.group(1), re.split(r"(?<=[.;:]) ", m.group(2))[0][:160])
    return rows


def item_tags(cfg: Any, brick: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(catalog domains, packs) of an item: from its words (id, paths, kind), its ecosystem
    and ``standards.packs``."""
    text = " ".join([brick["id"], brick.get("kind", ""), *_own_paths(brick)]).lower()
    dom = set(BASE_DOMAINS)
    for pat, ds in WORDS.items():
        if re.search(pat, text):
            dom |= set(ds)
    if brick.get("kind") == "system":
        dom |= {"RL", "OB"}
    packs = set(cfg.data.get("standards", {}).get("packs", []))
    return dom, packs | ({"postgresql"} if brick.get("ecosystem") == "sql" else set())


def classes(cfg: Any, bricks: list[dict[str, Any]], root: Path) -> dict[str, set[str]]:
    """Rules in use split into enforced (a check exists), embodied (a brick names it in
    ``embodies``) and judgment (the rest); overlay opt-outs are left out."""
    _, packs = detect(root)
    packs |= set(cfg.data.get("standards", {}).get("packs", []))
    use = set(rule_rows(cfg, packs)) - set(_opt_outs(cfg))
    enforced = {c["rule"] for c in load_index(cfg) if c["pack"] in {"base"} | packs} & use
    embodied = {r for b in bricks for r in b.get("embodies", [])} & use - enforced
    return {"enforced": enforced, "embodied": embodied, "judgment": use - enforced - embodied}


def packet_rules(
    cfg: Any, brick: dict[str, Any], bricks: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """The packet's rules: the item's own ``rules`` first, then judgment rules chosen by the
    item's tags (domains, packs), most often broken in findings first, at most
    ``limits.packet_rules`` in all, each ``{id, text}``."""
    dom, packs = item_tags(cfg, brick)
    rows = rule_rows(cfg, packs)
    cls = classes(cfg, bricks, cfg.dir)
    broken: dict[str, int] = {}
    for f in _findings(cfg):
        if f.get("rule"):
            broken[f["rule"]] = broken.get(f["rule"], 0) + 1
    used = {
        r
        for d in brick.get("depends_on", [])
        for b in bricks
        if b["id"] == d
        for r in b.get("embodies", [])
    }
    pick = sorted(
        (r for r in cls["judgment"] if r[:2] in dom and r not in used),
        key=lambda r: (-broken.get(r, 0), r),
    )
    ids = list(dict.fromkeys([*brick.get("rules", []), *pick]))[: cfg.limit("packet_rules")]
    return [{"id": r, "text": rows.get(r, "")} for r in ids]


def _findings(cfg: Any) -> list[dict[str, Any]]:
    try:
        return all_findings(cfg)
    except HarnessError:
        return []


# ---------------------------------------------------------------- facts for the report


def rule_facts(cfg: Any, bricks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Facts: class shares of the rules in use, judgment rules broken in two or more findings
    (check candidates) and the overlay's opt-outs with their reasons."""
    cls = classes(cfg, bricks, cfg.dir)
    n = sum(map(len, cls.values()))
    if not n:
        return []
    broken: dict[str, int] = {}
    for f in _findings(cfg):
        if f.get("rule") in cls["judgment"]:
            broken[f["rule"]] = broken.get(f["rule"], 0) + 1
    out: list[dict[str, Any]] = [
        {"kind": "rule-classes", "in_use": n}
        | {k: f"{len(v)} ({100 * len(v) // n}%)" for k, v in cls.items()}
    ]
    cand = sorted((r for r, c in broken.items() if c >= 2), key=lambda r: (-broken[r], r))
    if cand:
        out.append(
            {"kind": "check-candidates", "rules": ", ".join(f"{r} x{broken[r]}" for r in cand)}
        )
    out += [
        {"kind": "rule-not-applicable", "rule": r, "reason": why}
        for r, why in sorted(_opt_outs(cfg).items())
    ]
    return out


# ---------------------------------------------------------------- review of a sellable feature


def feature_review(cfg: Any, feature: str) -> dict[str, Any]:
    """What a fresh reviewer needs for a feature that became sellable: the paths of its items
    (the acceptance item's dependency closure), the plan commit the diff starts from, and the
    catalog domains and packs of those items; the reviewer reads ``git diff BASE HEAD -- PATHS``."""
    ctx = packet_context(cfg)
    by_id, top = ctx["bricks"], ctx["top"]
    feat = next((f for f in load_features(cfg) if f["id"] == feature), None)
    if feat is None or top is None:
        raise HarnessError(f"unknown feature {feature}" if feat is None else "not a git repository")
    seen, todo = set(), [feat["acceptance"]]
    while todo:
        i = todo.pop()
        if i not in seen and i in by_id:
            seen.add(i)
            todo += by_id[i].get("depends_on", [])
    paths = sorted({p for i in seen for p in _own_paths(by_id[i])})
    dom: set[str] = set()
    packs: set[str] = set()
    for i in seen:
        d, p = item_tags(cfg, by_id[i])
        dom |= d
        packs |= p
    base = ctx["plan_head"] or _git(top, "rev-list", "--max-parents=0", "HEAD").splitlines()[0]
    return {
        "feature": feature,
        "items": sorted(seen),
        "paths": paths,
        "base": base,
        "domains": sorted(dom),
        "packs": sorted(packs),
        "diff": f"git diff {base} HEAD -- " + " ".join(paths),
    }
