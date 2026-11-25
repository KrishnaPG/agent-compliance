"""The triggered review step (QBC-36) and the owner map the packet carries (QBC-19, duplication row).

Triggers are facts the program reads from the item's whole diff, base to the builder's commit, so a
diff split across commits cannot dodge them (P3; the counter of the Review row in spec section 6.1):

- the changed-file list: ``git diff --name-only -z``;
- Python files: the modules each side imports, read by Python's own parser (``ast``);
- SQL files: the statements whose text changed that hold a DCL keyword, as sqlparse classifies it;
- every changed path: its CODEOWNERS owner (GitHub's file, gitignore patterns read by pathspec,
  the last matching line wins), for the domains a project declares by owner;
- the packet's tier, for the duplication check.

The domains and their defaults are one table, ``harness/review-triggers.json``; a project replaces a
domain in ``.brick-harness/review-triggers.json`` (P8). Findings are SARIF 2.1.0 results (the L5
format), triage severity mapped to ``level`` (ISTQB S1 critical and S2 major = error, S3 minor =
warning, S4 = note), each message in the teaching shape (QBC-53) and the run naming the packet
sha256. They are facts: nothing here changes "met" (P4, QBC-35).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from bhcore import HARNESS_DIR, HDIR, SCHEMA_DIR, HarnessError, _git, _teach

TABLE = HARNESS_DIR / "review-triggers.json"
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # GitHub's lookup order
LEVEL = {"S1": "error", "S2": "error", "S3": "warning", "S4": "note"}
LIMITS = {"findings_shown": 10, "message_chars": 300}  # defaults of limits.* (QBC-55)
STANDARD = "NIST SSDF SP 800-218 PW.7"


def limits(cfg_data: dict[str, Any]) -> dict[str, int]:
    return {**LIMITS, **{k: v for k, v in cfg_data.get("limits", {}).items() if k in LIMITS}}


def table(root: Path) -> dict[str, dict[str, Any]]:
    """The plugin's trigger table with the project's domains laid over it."""
    rows = json.loads(TABLE.read_text())["triggers"]
    over = root / HDIR / "review-triggers.json"
    if over.is_file():
        rows = {**rows, **json.loads(over.read_text()).get("triggers", {})}
    return rows


# ---------------------------------------------------------------- the owner map (CODEOWNERS)


def _codeowners(root: Path) -> list[tuple[Any, list[str]]]:
    path = next((root / p for p in CODEOWNERS if (root / p).is_file()), None)
    if path is None:
        return []
    import pathspec

    rules = []
    for line in path.read_text().splitlines():
        parts = line.split("#", 1)[0].split()
        if parts:
            rules.append((pathspec.GitIgnoreSpec.from_lines([parts[0]]), parts[1:]))
    return rules


def owners_of(root: Path, paths: list[str]) -> dict[str, list[str]]:
    """Each path's owners: the last CODEOWNERS line that matches it (GitHub's rule)."""
    rules = _codeowners(root)
    out = {}
    for p in paths:
        hit = [o for spec, o in rules if spec.match_file(p)]
        if hit and hit[-1]:
            out[p] = hit[-1]
    return out


def _published(root: Path, init: str) -> list[str]:
    """The names a package publishes: its ``__init__.py`` ``__all__`` (PEP 8's public interface)."""
    try:
        tree = ast.parse((root / init).read_text())
    except (OSError, SyntaxError, ValueError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            try:
                return [str(n) for n in ast.literal_eval(node.value)]
            except ValueError:
                return []
    return []


def packet_owners(root: Path, declared: list[str], cap: int) -> dict[str, list[str]]:
    """The owners of an item's declared paths and each owner's published interface: every package
    (``__init__.py`` with ``__all__``) under that owner's paths, as ``package: names``."""
    tracked = _git(root, "ls-files", "-z", "--", *declared).split("\0") if declared else []
    by_path = owners_of(root, [p for p in [*declared, *tracked] if p and p != "."])
    owners = sorted({o for os_ in by_path.values() for o in os_})
    if not owners:
        return {}
    inits = [p for p in _git(root, "ls-files", "-z", "--", "*__init__.py").split("\0") if p]
    owner_of_init = owners_of(root, inits)
    interfaces = []
    for init in inits:
        names = _published(root, init) if set(owner_of_init.get(init, [])) & set(owners) else []
        if names:
            pkg = str(Path(init).parent)
            line = f"{pkg} ({' '.join(owner_of_init[init])}): {', '.join(names)}"
            interfaces.append(line[:cap])
    return {"owners": owners, "interfaces": interfaces}


# ---------------------------------------------------------------- triggers on the whole diff


def _show(root: Path, rev: str, path: str) -> str:
    try:
        return _git(root, "show", f"{rev}:{path}")
    except HarnessError:  # the file does not exist on that side
        return ""


def _imports(text: str) -> set[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out |= {n.module} | {f"{n.module}.{a.name}" for a in n.names}
    return out


def _dcl_changed(before: str, after: str) -> bool:
    import sqlparse
    from sqlparse import tokens

    def stmts(text: str) -> set[str]:
        return {str(s).strip() for s in sqlparse.parse(text) if str(s).strip()}

    return any(
        t.ttype in tokens.Keyword.DCL
        for s in stmts(before) ^ stmts(after)
        for t in sqlparse.parse(s)[0].flatten()
    )


def triggers(root: Path, base: str, ref: str, tier: str) -> list[dict[str, str]]:
    """The review domains the item's whole diff ``base..ref`` touches, one fact per domain with the
    first path that set it. An empty list: no review runs."""
    rows = table(root)
    changed = [p for p in _git(root, "diff", "--name-only", "-z", base, ref).split("\0") if p]
    owners = owners_of(root, changed)
    hits: dict[str, str] = {}
    for p in changed:
        sides = (_show(root, base, p), _show(root, ref, p)) if p.endswith((".py", ".sql")) else ("", "")
        mods = _imports(sides[0]) | _imports(sides[1]) if p.endswith(".py") else set()
        for dom, row in rows.items():
            if dom in hits:
                continue
            api = next(
                (m for a in row.get("python_apis", []) for m in sorted(mods) if m == a or m.startswith(a + ".")),
                None,
            )
            if api:
                hits[dom] = f"{p} imports {api}"
            elif row.get("sql_dcl") and p.endswith(".sql") and _dcl_changed(*sides):
                hits[dom] = f"{p} changes a GRANT or REVOKE statement"
            elif set(owners.get(p, [])) & set(row.get("owners", [])):
                hits[dom] = f"{p} is owned by {' '.join(owners[p])}"
    for dom, row in rows.items():
        if tier in row.get("tiers", []) and dom not in hits:
            hits[dom] = f"the item is {tier}"
    return [{"domain": d, "detail": hits[d]} for d in rows if d in hits]


# ---------------------------------------------------------------- findings as SARIF facts


def sarif(findings: list[dict[str, Any]], item: str, digest: str, chars: int) -> dict[str, Any]:
    """The reviewer's findings as one SARIF 2.1.0 log, checked against the official schema. The
    summary is written ``wrong -> the right way, and how to prevent it`` (the review job schema)."""
    from jsonschema.validators import validator_for

    results = []
    for f in findings:
        wrong, _, right = f["summary"].partition("->")
        rule = f.get("rule") or "review"
        res: dict[str, Any] = {
            "ruleId": rule,
            "level": LEVEL.get(f.get("severity", ""), "warning"),
            "message": {"text": _teach(rule, wrong.strip(), right.strip(), STANDARD)[:chars]},
            "properties": {k: f[k] for k in ("severity", "evidence") if k in f},
        }
        file, _, line = (f.get("where") or "").partition(":")
        if file:
            loc: dict[str, Any] = {"artifactLocation": {"uri": file}}
            if line.split(":")[0].isdigit() and int(line.split(":")[0]) > 0:
                loc["region"] = {"startLine": int(line.split(":")[0])}
            res["locations"] = [{"physicalLocation": loc}]
        results.append(res)
    log = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "harness-reviewer", "informationUri": "https://csrc.nist.gov/pubs/sp/800/218/final"}},
                "results": results,
                "properties": {"packet_sha256": digest, "item": item},
            }
        ],
    }
    schema = json.loads((SCHEMA_DIR / "sarif-2.1.0.json").read_text())
    bad = next(iter(validator_for(schema)(schema).iter_errors(log)), None)
    if bad:
        raise HarnessError(f"review SARIF invalid at {bad.json_path}: {bad.message}")
    return log


def errors(log: dict[str, Any]) -> list[str]:
    """The error-level results (critical or major) as the builder's feedback lines."""
    out = []
    for r in log["runs"][0]["results"]:
        if r["level"] == "error":
            where = r.get("locations", [{}])[0].get("physicalLocation", {})
            at = where.get("artifactLocation", {}).get("uri", "")
            line = where.get("region", {}).get("startLine")
            out.append(f"{at}{f':{line}' if line else ''} {r['message']['text']}".strip())
    return out
