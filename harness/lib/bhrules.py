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
import tomllib
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
    all_findings,
    overlay_file,
    tool_cache,
)

EXT = {
    "python": (".py",),
    "typescript": (".ts", ".tsx", ".js", ".jsx", ".mjs"),
    "sql": (".sql",),
}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}
RULE_ID = r"[A-Z]{2}-\d+"
ROW = re.compile(rf"^\|\s*({RULE_ID})\s*\|\s*(.+?)\s*\|")
# Facts a check may bind, each inferred from the code: files that define routes or an app,
ENTRY = re.compile(r"\b(?:APIRouter|FastAPI)\(|\bRouter\(")
# ... and the files that own the outbox table: SQL naming a table whose name holds "outbox"
# after INTO, FROM, UPDATE, TABLE or EXISTS (INSERT INTO / DELETE FROM / CREATE TABLE [IF NOT
# EXISTS] / UPDATE, which is also how the relay marks rows sent); a Python ORM ``class
# ...Outbox...`` or ``__tablename__ = "...outbox..."``; a ``Table(`` / ``pgTable(`` /
# ``sqliteTable(`` / ``mysqlTable(`` declaration whose first argument holds "outbox".
OUTBOX = re.compile(
    r"""(?ix)
      \b(?:INTO|FROM|UPDATE|TABLE|EXISTS)\s+["`\[]?[\w.]*outbox
    | \bclass\s+\w*outbox\w*\s*[(:]
    | __tablename__\s*=\s*["'][\w.]*outbox
    | \b(?:Table|pgTable|sqliteTable|mysqlTable)\(\s*["'][\w.]*outbox
    """
)
MARKERS = (
    r"noqa|nosemgrep|type:\s*ignore|eslint-disable|ast-grep-ignore|pylint:\s*disable"
    r"|@ts-ignore|@ts-expect-error|nosec"
)


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


def _modules_matching(root: Path, pat: re.Pattern[str]) -> list[str]:
    out = []
    for p in _files(root):
        if p.suffix in EXT["python"] + EXT["typescript"] and p.stat().st_size < 1_000_000:
            try:
                if pat.search(p.read_text(errors="ignore")):
                    out.append(p.relative_to(root).as_posix())
            except OSError:
                pass
    return sorted(out)


def entry_modules(root: Path) -> list[str]:
    """Files that define routes or an app (FastAPI/Starlette ``APIRouter``/``FastAPI(``,
    Express ``Router(``): the trust-boundary entry modules, inferred from the code."""
    return _modules_matching(root, ENTRY)


def outbox_modules(root: Path) -> list[str]:
    """Python and TypeScript files that own the outbox table (``OUTBOX`` above): they define
    it or write, update, delete from or read it, which is where the relay publishes."""
    return _modules_matching(root, OUTBOX)


OPT_OUT = re.compile(rf"^- ({RULE_ID}) not-applicable: (.*\S)\s*$")


def _opt_outs(cfg: Any) -> dict[str, str]:
    """Rules the overlay opts out of the checks, in the catalog's form (checks/README.md):
    lines ``- <RULE-ID> not-applicable: <reason>`` under the heading ``## Check opt-outs``.
    ``{rule: reason}``; a line without a reason opts nothing out."""
    out: dict[str, str] = {}
    ov = overlay_file(cfg)
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
    return {"entry_modules": entry_modules(root), "outbox_modules": outbox_modules(root)}


LOOKED_IN = {
    "entry_modules": ["route or app definitions (APIRouter, FastAPI(, Router()"],
    "outbox_modules": ["outbox table definitions or SQL on an outbox table (OUTBOX pattern)"],
}


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
            "looked_in": LOOKED_IN[f],
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
    cache = tool_cache() / "bin" / f"ast-grep-{spec['version']}"
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
            # a bound module is the rule's one allowed place: scan every module except those
            files = [f for f in files if f not in facts.get(fact, [])]
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


def rules_file(cfg: Any) -> Path:
    """The rules a plan, packet or review cites: ``catalog/rules.toml`` under the catalog root."""
    return catalog_root(cfg) / "catalog" / "rules.toml"


# The closed set of fact tags (QBC-103): ``always`` is the core every item gets.
TAGS = (
    "always", "messaging", "network-client", "http-server", "database", "auth", "deploy",
    "concurrency", "money", "time", "config", "dependency-change", "defect",
)  # fmt: skip
CORE_MAX = 10  # QBC-103: the always core holds at most 10 rules


def rules_doc(cfg: Any) -> dict[str, Any]:
    """``catalog/rules.toml`` parsed: ``standards``, ``tags`` and ``house`` tables (empty if
    absent). A tag outside the closed set ``TAGS``, in ``[tags.*]`` or a rule's ``applies``, and
    a core of more than ``CORE_MAX`` rules are catalog errors (QBC-103)."""
    f = rules_file(cfg)
    doc = tomllib.loads(f.read_text()) if f.is_file() else {}
    bad = sorted(set(doc.get("tags", {})) - set(TAGS)) + [
        f"{k}: {t}" for k, v in doc.get("house", {}).items() for t in v.get("applies", []) if t not in TAGS
    ]
    core = [k for k, v in doc.get("house", {}).items() if "always" in v.get("applies", [])]
    if bad or len(core) > CORE_MAX:
        raise HarnessError(
            f"[catalog-tags] {f}: tags outside the closed set ({', '.join(bad) or 'none'}) or a core of"
            f" {len(core)} rules (at most {CORE_MAX}) -> use only {', '.join(TAGS)} . QBC-103"
        )
    return doc


def rule_rows(cfg: Any) -> dict[str, str]:
    """``{rule id: one line}``: each house rule's ``right`` way (else its text's first clause),
    each standard as ``<title> <version>: <url>`` (a ``<standard>:<section>`` id takes its
    standard's line), then the overlay's rows."""
    data = rules_doc(cfg)
    rows = {k: f"{v['title']} {v['version']}: {v['url']}" for k, v in data.get("standards", {}).items()}
    rows |= {k: (v.get("right") or _first(v["text"]))[:160] for k, v in data.get("house", {}).items()}
    if ov := overlay_file(cfg):
        for line in ov.read_text(errors="ignore").splitlines():
            m = ROW.match(line)
            if m:
                rows.setdefault(m.group(1), _first(m.group(2)))
    return rows


def _first(text: str) -> str:
    """A rule's first clause, at most 160 characters: the packet's one line per rule."""
    return re.split(r"(?<=[.;:]) ", text)[0][:160]


def rule_text(rows: dict[str, str], rid: str) -> str:
    std, sep, section = rid.partition(":")
    return rows.get(rid) or (f"{section} of {rows[std]}" if sep and std in rows else "")


def rule_detail(cfg: Any, rid: str) -> str:
    """The whole rule as ``bh rule ID`` prints it: text, why, the right way, the question, what
    embodies it, where it applies, and each citation as its standard's title, section, summary
    and URL (provenance). An overlay row prints as the overlay states it."""
    data = rules_doc(cfg)
    std = data.get("standards", {})
    r = data.get("house", {}).get(rid)
    if r is None:
        line = rule_text(rule_rows(cfg), rid)
        if not line:
            raise HarnessError(f"[rule-unknown] {rid} is not in {rules_file(cfg)} or the overlay")
        return f"{rid}: {line}\n"
    out = [f"{rid}: {r['text']}"]
    out += [f"{k.capitalize()}: {r[k]}" for k in ("why", "right", "question", "embodied_by") if r.get(k)]
    out.append("Applies: " + (", ".join(r.get("applies", [])) or "when the plan pins it"))
    for c in r.get("cites", []):
        key, _, section = c.partition(":")
        s = std.get(key, {})
        out.append(f"Cites: {s.get('title', key)} {s.get('version', '')}, {section}".rstrip(", "))
        out += [f"  {s['summary']}"] if s.get("summary") else []
        out += [f"  {s['url']}"] if s.get("url") else []
    return "\n".join(out) + "\n"


def classes(cfg: Any, bricks: list[dict[str, Any]], root: Path) -> dict[str, set[str]]:
    """Rules in use (the union of the items' ``rules`` and the enforced check rules, overlay
    opt-outs left out) split into enforced (a check exists), embodied (an item names it in
    ``embodies``) and judgment (the rest)."""
    enforced = {c["rule"] for c in _selected(cfg, root)}
    use = ({r for b in bricks for r in _pins(b)} | enforced) - set(_opt_outs(cfg))
    embodied = {r for b in bricks for r in b.get("embodies", [])} & use - enforced
    return {"enforced": enforced & use, "embodied": embodied, "judgment": use - enforced - embodied}


# ---------------------------------------------------------------- which rules apply: fact tags
#
# Facts decide, not an agent: static analysers turn rule packs on by the detected language and
# framework (Semgrep, CodeQL), and risk-based test selection (ISTQB) takes its triggers from what
# the change touches. A house rule's ``applies`` names tags from the closed set ``[tags.*]`` of
# rules.toml; ``always`` is the small core every item gets. The program derives an item's tags
# at 0 tokens from three sources, erring toward recall: (a) the stack, the lock files' packages
# and the config's ``standards.stack`` through the tags' ``names``; (b) the contract, the item's
# declared ``interfaces`` kinds, the tools it declares (``oss_checked``), its kind, and the
# imports, file kinds and code facts of its owned paths; (c) the diff, the imports a change adds
# and the kinds of the files it touches. The packet gets the core, (a) and (b); ``bh rules
# --diff`` and the review add (c). The planner only adds rules (``rules``, each with a reason);
# only the overlay removes one, with a reason. A finding whose rule was not selected is a
# ``selector_miss`` fact naming the missing tag, so the tag table is corrected from measurements.

IMPORT = re.compile(
    r"""^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))
      | (?:\bfrom\s+|\brequire\(\s*|\bimport\s+)["']([^"'./][^"']*)["']""",
    re.M | re.X,
)


def _imports_in(text: str) -> set[str]:
    """Top-level module and package names ``text`` imports (Python ``import``/``from``; JS and
    TS ``from "x"``, ``import "x"``, ``require("x")``; a scoped npm name keeps its scope)."""
    out: set[str] = set()
    for m in IMPORT.finditer(text):
        name = next(g for g in m.groups() if g)
        parts = name.split("/") if m.group(3) else name.split(".")
        out.add(_norm("/".join(parts[:2]) if name.startswith("@") else parts[0]))
    return out


def _code(path: Path) -> bool:
    return path.suffix in EXT["python"] + EXT["typescript"] and path.is_file() and path.stat().st_size < 1_000_000


def _import_names(root: Path, files: set[str]) -> set[str]:
    """The names the files import."""
    return {n for f in files if _code(root / f) for n in _imports_in((root / f).read_text(errors="ignore"))}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _kind_tags(tags: dict[str, Any], files: list[str]) -> dict[str, list[str]]:
    """``{tag: [file]}``: files whose name or path matches a tag's ``files`` globs."""
    from fnmatch import fnmatch

    out: dict[str, list[str]] = {}
    for t, spec in tags.items():
        hit = [f for f in files if any(fnmatch(f, g) or fnmatch(f.rsplit("/", 1)[-1], g) for g in spec.get("files", []))]
        if hit:
            out[t] = hit[:3]
    return out


def _name_tags(tags: dict[str, Any], names: set[str]) -> dict[str, list[str]]:
    """``{tag: [name]}``: imported or declared names in a tag's ``names``."""
    out: dict[str, list[str]] = {}
    for t, spec in tags.items():
        hit = sorted(names & {_norm(n) for n in spec.get("names", [])})
        if hit:
            out[t] = hit[:3]
    return out


def _tags_of(tags: dict[str, Any], names: set[str], files: list[str]) -> dict[str, list[str]]:
    out = _name_tags(tags, names)
    for t, ev in _kind_tags(tags, files).items():
        out.setdefault(t, []).extend(ev)
    return out


def stack_tags(cfg: Any, versions: dict[str, str] | None = None) -> dict[str, list[str]]:
    """(a) The tags the project's stack shows: its lock files' packages and ``standards.stack``."""
    if versions is None:
        from bhcore import lock_versions

        versions = lock_versions(cfg.files("lockfiles"))
    declared = {re.split(r"[=@<>~! ]", s.lstrip("@"), maxsplit=1)[0] for s in cfg.data.get("standards", {}).get("stack", [])}
    names = {_norm(n) for n in versions} | {_norm(n) for n in declared if n}
    return _name_tags(rules_doc(cfg).get("tags", {}), names)


def contract_tags(cfg: Any, brick: dict[str, Any], rev: str | None = None) -> dict[str, list[str]]:
    """(b) The tags the item's contract shows: its ``interfaces`` kinds, declared tools, kind, and
    the imports, file kinds and code facts (entry, outbox modules) of its owned paths, in the
    working tree or, with ``rev``, as committed there (the state a diff from ``rev`` starts at)."""
    tags = rules_doc(cfg).get("tags", {})
    root = cfg.dir
    if rev is None:
        owned = _scope(root, brick, [])
        names = _import_names(root, owned)
    else:
        own = _own_paths(brick)
        try:
            owned = set(_git(root, "ls-tree", "-r", "--name-only", "--full-name", rev, "--", *own).splitlines()) if own else set()
            top = _git(root, "rev-parse", "--show-prefix")
            owned = {f[len(top):] for f in owned if f.startswith(top)}
        except HarnessError:
            owned = set()
        names = {n for f in owned if Path(f).suffix in EXT["python"] + EXT["typescript"] for n in _imports_in(_git(root, "show", f"{rev}:./{f}"))}
    names |= {_norm(o.get("tool", "")) for o in brick.get("oss_checked", [])}
    out = _tags_of(tags, names, sorted(owned | set(_own_paths(brick))))
    kinds = {i.get("kind") for i in brick.get("interfaces", [])}
    facts = _facts(root) if owned and any(s.get("facts") for s in tags.values()) else {}
    for t, s in tags.items():
        ev = [f"interface {k}" for k in sorted(kinds & set(s.get("interfaces", [])))]
        ev += sorted(owned & {m for f in s.get("facts", []) for m in facts.get(f, [])})[:3]
        ev += [f"kind {brick['kind']}"] if brick.get("kind") in s.get("kinds", []) else []
        if ev:
            out.setdefault(t, []).extend(ev)
    return out


def diff_tags(cfg: Any, base: str = "HEAD", ref: str | None = None) -> dict[str, list[str]]:
    """(c) The tags a change shows: imports on its added lines and the kinds of the files it
    touches. ``ref`` None: the working tree against ``base``, untracked files whole (``bh rules
    --diff``); ``ref`` set: ``git diff base ref`` only (a build commit the review judges while
    the tree is elsewhere)."""
    root = cfg.dir
    try:
        diff = _git(root, "diff", "-U0", "--no-renames", base, *([ref] if ref else []), "--", ".")
        new = [] if ref else _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    except HarnessError:
        return {}
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    touched = [ln[6:] for ln in diff.splitlines() if ln.startswith("+++ b/")] + new
    names = _imports_in(added) | {n for f in new if _code(root / f) for n in _imports_in((root / f).read_text(errors="ignore"))}
    return _tags_of(rules_doc(cfg).get("tags", {}), names, touched)


def _pins(brick: dict[str, Any]) -> dict[str, str]:
    """The planner's added rules: ``{id: reason}`` (a bare id has no reason)."""
    return {r if isinstance(r, str) else r["id"]: "" if isinstance(r, str) else r.get("reason", "") for r in brick.get("rules", [])}


def select_rules(
    cfg: Any,
    brick: dict[str, Any],
    bricks: list[dict[str, Any]],
    versions: dict[str, str] | None = None,
    diff: dict[str, list[str]] | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Which rules apply to ``brick``, with no agent: ``{item, tags: {source: {tag: evidence}},
    chosen, added_by_diff}``. Chosen: the planner's added rules, then the house rules one of
    whose ``applies`` tags the core, the stack or the contract shows (and the diff, when given),
    less overlay opt-outs and rules a brick it depends on ``embodies``. Order: added, then most
    broken in findings, then round-robin over the core and the domains in catalog order, so each
    applying domain's first rules come first. ``chosen`` is the first ``limits.packet_rules``;
    ``more`` the rest, never dropped for size (QBC-105 (iv)); ``added_by_diff`` every rule the
    diff's tags add; with ``base`` the contract's code facts are read as committed at ``base``,
    where the diff starts, so the diff's own imports count as added."""
    house = rules_doc(cfg).get("house", {})
    src = {"core": {"always": ["every item"]}, "stack": stack_tags(cfg, versions), "contract": contract_tags(cfg, brick, base)}
    if diff is not None:
        src["diff"] = diff
    off = set(_opt_outs(cfg))
    used = {r for d in brick.get("depends_on", []) for x in bricks if x["id"] == d for r in x.get("embodies", [])}
    pins = _pins(brick)

    def pick(tags: set[str]) -> list[str]:
        hit = [k for k, v in house.items() if set(v.get("applies", [])) & tags]
        return [r for r in dict.fromkeys([*pins, *hit]) if r not in off and r not in used]

    broken: dict[str, int] = {}
    for f in _findings(cfg):
        if f.get("rule"):
            broken[f["rule"]] = broken.get(f["rule"], 0) + 1

    def domain(r: str) -> str:
        return "core" if house.get(r, {}).get("applies") == ["always"] else r.split("-")[0]

    order = ["core", *dict.fromkeys(r.split("-")[0] for r in house)]

    def ranked(ids: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        rank = {}
        for r in ids:
            rank[r] = seen.get(domain(r), 0)
            seen[domain(r)] = rank[r] + 1
        key = lambda r: (r not in pins, -broken.get(r, 0), rank[r], order.index(domain(r)) if domain(r) in order else len(order), r)  # noqa: E731
        return sorted(ids, key=key)

    base_tags = set().union(*(src[k] for k in ("core", "stack", "contract")))
    every = ranked(pick(base_tags | set(src.get("diff", {}))))
    cap = cfg.limit("packet_rules")
    chosen = every[:cap]
    out: dict[str, Any] = {"item": brick["id"], "tags": src, "chosen": chosen, "more": every[cap:]}
    if pins:
        out["added"] = pins
    if diff is not None:
        planned = set(pick(base_tags))
        out["added_by_diff"] = [r for r in every if r not in planned]
    return out


def project_rules(cfg: Any) -> list[dict[str, str]]:
    """The rules an agent job about the whole project gets (gaps, judge): the core and the
    stack's selection, as a packet lists them (full lines, then titles); never the whole catalog
    (QBC-106). ``bh rule ID`` prints any rule in full."""
    try:
        from bhcore import packet_context

        bricks = list(packet_context(cfg)["bricks"].values())
    except HarnessError:
        bricks = []
    return packet_rules(cfg, {"id": "(project)"}, bricks)


def selector_misses(
    cfg: Any, brick: dict[str, Any], selected: list[str], findings: list[dict[str, Any]], base: str | None = None
) -> list[dict[str, Any]]:
    """Facts for the run result: a finding whose house rule was not in the item's packet is a
    ``selector_miss`` naming the rule and the tags it applies by that the item's sources missed
    (none: it applies only when the planner adds it). ``selected`` is every id the packet lists;
    ``base`` reads the contract's code facts before the diff, as ``select_rules`` does, so a
    review run with HEAD checked out still names the tag the diff brought in."""
    house = rules_doc(cfg).get("house", {})
    have = {"always"} | set(stack_tags(cfg)) | set(contract_tags(cfg, brick, base))
    out = []
    for r in dict.fromkeys(f.get("rule") for f in findings if f.get("rule") in house and f.get("rule") not in selected):
        miss = sorted(set(house[r].get("applies", [])) - have)
        out.append({"kind": "selector_miss", "item": brick["id"], "rule": r, "missing_tag": ", ".join(miss) or "none: it applies only when added"})
    return out


def packet_rules(
    cfg: Any, brick: dict[str, Any], bricks: list[dict[str, Any]], versions: dict[str, str] | None = None
) -> list[dict[str, str]]:
    """The packet's rules (``select_rules``): ``{id, text}``, the chosen with their one line and
    the rest by id and title only (``title``), to read with ``bh rule ID`` (QBC-105 (iv))."""
    rows = rule_rows(cfg)
    sel = select_rules(cfg, brick, bricks, versions)
    return [{"id": r, "text": rule_text(rows, r)} for r in sel["chosen"]] + [
        {"id": r, "text": title(rows, r)} for r in sel["more"]
    ]


def title(rows: dict[str, str], rid: str) -> str:
    """A rule's title: its line up to the first ``;``, ``,`` or ``:``, at most 60 characters, and
    where to read the rest."""
    return re.split(r"[;,:]", rule_text(rows, rid), maxsplit=1)[0][:60].rstrip() + f" (bh rule {rid})"


def rule_cmd(config: str, rid: str) -> str:
    """``bh rule ID``: the whole rule (``rule_detail``), read just in time by a builder."""
    from bhcore import Config

    return rule_detail(Config(config, partial=True), rid)


def rules_cmd(config: str, item: str | None, at: str | None = None, diff: list[str] | None = None) -> str:
    """``bh rules [--item X] [--at REV] [--diff [BASE [REF]]]``: the item's (else the project's)
    tags by source with their evidence and its chosen rules with their lines, as JSON, at 0
    tokens; ``--diff`` adds the tags (c) of the change (the working tree against BASE, default
    HEAD, or BASE..REF) and lists the rules it adds in ``added_by_diff`` (QBC-105 (i): the
    builder's self-check before finishing). With ``--at``
    the project is read at that commit from a detached ``git worktree`` (removed after), so a
    human or a history replay gets the selection of any past commit with no agent."""
    import tempfile

    from bhcore import Config, git_top, lock_versions, packet_context

    def run(conf: Path) -> str:
        cfg = Config(conf)
        ctx = packet_context(cfg)
        b = ctx["bricks"].get(item) if item else {"id": "(project)"}
        if b is None:
            raise HarnessError(f"[rules-unknown-item] {item} is not in the plan -> run bh plan first")
        dt = diff_tags(cfg, *(diff or ["HEAD"])) if diff is not None else None
        base = (diff or ["HEAD"])[0] if diff is not None else None
        sel = select_rules(cfg, b, list(ctx["bricks"].values()), lock_versions(cfg.files("lockfiles")), dt, base)
        rows = rule_rows(cfg)
        sel["chosen"] = [{"id": r, "text": rule_text(rows, r)} for r in sel["chosen"]]
        sel["more"] = [{"id": r, "text": title(rows, r)} for r in sel["more"]]
        return json.dumps(sel, indent=2) + "\n"

    conf = Path(config).resolve()
    if not at:
        return run(conf)
    top = git_top(conf.parent)
    if top is None:
        raise HarnessError("--at needs a git repository")
    with tempfile.TemporaryDirectory(prefix="bh-rules-") as d:
        wt = Path(d) / "tree"
        _git(top, "worktree", "add", "--detach", "--quiet", str(wt), at)
        try:
            return run(wt / conf.relative_to(top))
        finally:
            _git(top, "worktree", "remove", "--force", str(wt))


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
