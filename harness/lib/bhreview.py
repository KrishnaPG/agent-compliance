"""The triggered review step (QBC-36) and the touched owners' interfaces in the packet (QBC-19,
duplication row).

Triggers are facts the program reads from the item's whole diff, base to the builder's commit, so a
diff split across commits cannot dodge them (P3; the counter of the Review row in section 6.1).
Nothing here keeps a name or pattern list (QBC-18); each trigger comes from data that is already
maintained or declared:

- secrets, keys and auth: a finding of the flake8-bandit (``S``) rules the plugin's ruff preset
  enables (``bhpresets``), present on one side of the diff and not the other;
- grants: a changed SQL statement holding a DCL keyword (GRANT, REVOKE), as sqlparse classifies it;
- what the project declares in ``review.triggers`` (config, P8): a CODEOWNERS owner (GitHub's owner
  syntax, ``@team`` or an e-mail) whose code the diff touches, or a gitignore path pattern;
- the packet's tier: design-affecting items get the duplication check (section 6.1).

Money and any other domain no maintained tool sees are the project's to declare there. Owners come
from the one owner map (``bhpresets.owner_map``). Findings are SARIF 2.1.0 results (the L5 format),
triage severity mapped to ``level`` (ISTQB S1 critical and S2 major = error, S3 minor = warning,
S4 = note), each message in the teaching shape (QBC-53), the run naming the packet sha256. They are
facts: nothing here changes "met" (P4, QBC-35).
"""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bhcore import SCHEMA_DIR, HarnessError, _git, _teach

LEVEL = {"S1": "error", "S2": "error", "S3": "warning", "S4": "note"}
LIMITS = {"findings_shown": 10, "message_chars": 300}  # defaults of limits.* (QBC-55)
STANDARD = "NIST SSDF SP 800-218 PW.7"


def limits(cfg_data: dict[str, Any]) -> dict[str, int]:
    return {**LIMITS, **{k: v for k, v in cfg_data.get("limits", {}).items() if k in LIMITS}}


# ---------------------------------------------------------------- owners: the one owner map


def unit_owners(root: Path) -> dict[str, tuple[str, str]]:
    """Each owner unit's directory (relative, with a trailing slash) -> (owner, dotted package), from
    ``bhpresets.owner_map`` (CODEOWNERS, then OpenAPI tags, then the folder name)."""
    import bhpresets

    preset = bhpresets.presets().get("python")
    if not preset:
        return {}
    dirs = {
        f"{name}.{u.name}": u.relative_to(root).as_posix() + "/"
        for name, d in bhpresets.root_packages(root)
        for u in d.iterdir()
        if (u / "__init__.py").is_file()
    }
    return {
        dirs[unit]: (owner, unit)
        for owner, o in bhpresets.owner_map(root, preset).items()
        for unit in o["units"]
        if unit in dirs
    }


def owner_of(units: dict[str, tuple[str, str]], path: str) -> tuple[str, str] | None:
    return next((v for d, v in units.items() if path.startswith(d) or path + "/" == d), None)


def _published(init: Path) -> list[str]:
    """The names a package publishes: its ``__init__.py`` ``__all__`` (PEP 8's public interface)."""
    try:
        tree = ast.parse(init.read_text())
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
    """The owners of an item's declared paths and each touched owner's published interface: its
    units' ``__all__`` names, as ``package (owner): names``."""
    units = unit_owners(root)
    tracked = [p for p in _git(root, "ls-files", "-z", "--", *declared).split("\0") if p] if declared else []
    hit = {o for p in [*declared, *tracked] if p and p != "." and (o := owner_of(units, p))}
    owners = sorted({o for o, _ in hit})
    if not owners:
        return {}
    interfaces = []
    for d, (owner, unit) in sorted(units.items()):
        names = _published(root / d / "__init__.py") if owner in owners else []
        if names:
            interfaces.append(f"{unit} ({owner}): {', '.join(names)}"[:cap])
    return {"owners": owners, "interfaces": interfaces}


# ---------------------------------------------------------------- triggers on the whole diff


def _show(root: Path, rev: str, path: str) -> str | None:
    try:
        return _git(root, "show", f"{rev}:{path}") + "\n"
    except HarnessError:  # the file does not exist on that side
        return None


def _ruff_s(files: dict[str, str]) -> set[tuple[str, str, str]]:
    """(rule, path, source line) of every finding of the preset's flake8-bandit rules, run by the
    preset's pinned ruff over the given file texts."""
    import bhpresets

    preset = bhpresets.presets().get("python", {})
    codes = [c for c in preset.get("ruff", {}).get("extend-select", []) if c.startswith("S")]
    ruff = next((t for t in preset.get("tools", []) if t.startswith("ruff==")), None)
    if not (files and codes and ruff):
        return set()
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in files.items():
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / rel).write_text(text)
        cmd = ["uvx", ruff.replace("==", "@"), "check", "--isolated", "--no-cache", "--select", ",".join(codes)]
        p = subprocess.run([*cmd, "--output-format", "json", "."], cwd=tmp, capture_output=True, text=True)
        if p.returncode not in (0, 1):
            raise HarnessError(f"ruff for the review triggers failed: {p.stderr.strip()[:300]}")
        out = set()
        for f in json.loads(p.stdout or "[]"):
            rel = Path(f["filename"]).resolve().relative_to(Path(tmp).resolve()).as_posix()
            line = files[rel].splitlines()[f["location"]["row"] - 1].strip()
            out.add((f["code"], rel, line))
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


def triggers(root: Path, cfg_data: dict[str, Any], base: str, ref: str, tier: str) -> list[dict[str, str]]:
    """The review domains the item's whole diff ``base..ref`` touches, one fact per domain with the
    first path that set it. An empty list: no review runs."""
    import pathspec

    changed = [p for p in _git(root, "diff", "--name-only", "-z", base, ref).split("\0") if p]
    sides = {p: (_show(root, base, p), _show(root, ref, p)) for p in changed if p.endswith((".py", ".sql"))}
    hits: dict[str, str] = {}
    py = [p for p in sides if p.endswith(".py")]
    found = _ruff_s({p: t for p in py if (t := sides[p][0]) is not None}) ^ _ruff_s(
        {p: t for p in py if (t := sides[p][1]) is not None}
    )
    if found:
        code, path, _ = sorted(found)[0]
        hits["secrets"] = f"{path}: ruff {code} finding changed"
    sql = next((p for p in sides if p.endswith(".sql") and _dcl_changed(*(t or "" for t in sides[p]))), None)
    if sql:
        hits["grants"] = f"{sql} changes a GRANT or REVOKE statement"
    units = unit_owners(root)
    for t in cfg_data.get("review", {}).get("triggers", []):
        if "@" in t:  # a CODEOWNERS owner (GitHub's owner syntax)
            p = next((p for p in changed if (o := owner_of(units, p)) and o[0] == t), None)
        else:
            spec = pathspec.PathSpec.from_lines("gitignore", [t])
            p = next((p for p in changed if spec.match_file(p)), None)
        if p:
            hits.setdefault(t, f"{p} is under review.triggers {t}")
    if tier == "design-affecting":
        hits["duplication"] = f"the item is {tier}"
    return [{"domain": d, "detail": v} for d, v in hits.items()]


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
