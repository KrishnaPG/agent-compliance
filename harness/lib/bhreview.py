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
- the packet's tier: a design-affecting item (R6, ISTQB risk-based testing) gets the architecture
  review, its whole diff against the packet's rule lines, and the duplication check (section 6.1);
- the packet's kind: a defect fix gets the root-cause review (rule NO-12) at any tier.

Every review judges the diff against exactly the packet's rule lines, the ones its builder got.

Money and any other domain no maintained tool sees are the project's to declare there. Owners come
from the one owner index (``owner_index``: CODEOWNERS, the import-linter contracts, the packages and
the OpenAPI documents). Findings are SARIF 2.1.0 results (the L5 format),
triage severity mapped to ``level`` (ISTQB S1 critical and S2 major = error, S3 minor = warning,
S4 = note), each message in the teaching shape (QBC-53), the run naming the packet sha256. They are
facts: nothing here changes "met" (P4, QBC-35).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bhcore import SCHEMA_DIR, HarnessError, _git, _teach, default_branch

LEVEL = {"S1": "error", "S2": "error", "S3": "warning", "S4": "note"}
LIMITS = {"findings_shown": 10, "message_chars": 300}  # defaults of limits.* (QBC-55)
STANDARD = "NIST SSDF SP 800-218 PW.7"


def limits(cfg_data: dict[str, Any]) -> dict[str, int]:
    return {**LIMITS, **{k: v for k, v in cfg_data.get("limits", {}).items() if k in LIMITS}}


# ---------------------------------------------------------------- owners: the one owner map


def _tracked(root: Path) -> list[str]:
    """The project's files, tracked or new and not ignored (git's view: no vendored tree is walked)."""
    try:
        return [p for p in _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0") if p]
    except HarnessError:
        return []


def owner_index(root: Path) -> dict[str, Any]:
    """The project's owners, read from its standard files at 0 tokens, as ``{codeowners, units,
    ops}``. ``units``: each owner unit's directory or file (relative, a directory with a trailing
    slash) -> ``(owner, label, interface file)``, from, later sources winning on the same path:
    the Python preset's owner map (``bhpresets.owner_map``: CODEOWNERS, OpenAPI handler tags, the
    folder name); each PyPA src-layout package (``<project>/src/<pkg>``, owned by its project
    folder); each import-linter contract module; and each folder or file named for an owner the
    OpenAPI documents declare (``x-owner`` or a tag). ``ops``: owner -> its published operations."""
    import bhpresets
    from bhrules import EXT

    code = {x for v in EXT.values() for x in v}
    files = _tracked(root)
    units: dict[str, tuple[str, str, str]] = {}
    if preset := bhpresets.presets().get("python"):
        dirs = {
            f"{name}.{u.name}": u.relative_to(root).as_posix()
            for name, d in bhpresets.root_packages(root)
            for u in d.iterdir()
            if (u / "__init__.py").is_file()
        }
        for owner, o in bhpresets.owner_map(root, preset).items():
            for unit in o["units"]:
                if unit in dirs:
                    units[dirs[unit] + "/"] = (owner, unit, dirs[unit] + "/__init__.py")
    inits = [f for f in files if f.endswith("/__init__.py")]
    for f in inits:
        parts = f.split("/")
        if len(parts) >= 3 and parts[-3] == "src":  # <project>/src/<pkg>/__init__.py (PyPA src layout)
            project = "/".join(parts[:-3])
            units.setdefault((project + "/") if project else f.rsplit("/", 1)[0] + "/", (Path(project).name or parts[-2], parts[-2], f))
    for mod in bhpresets.importlinter_modules(root):
        tail = "/" + mod.replace(".", "/") + "/__init__.py"
        for f in inits:
            if ("/" + f).endswith(tail):
                units[f[: -len("__init__.py")]] = (mod.rsplit(".", 1)[-1], mod, f)
    ops: dict[str, list[dict[str, str]]] = {}
    docs = [root / f for f in files if re.fullmatch(r"(?:.*/)?openapi\.(?:ya?ml|json)", f)]
    for op in bhpresets.openapi_ops(root, docs):
        ops.setdefault(op["owner"], []).append(op)
    for f in files:  # a folder or file named for a declared owner (``apps/<owner>/``, ``<owner>.sql``)
        parts = f.split("/")
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            name = part.split(".", 1)[0] if last and Path(part).suffix in code else part
            if name in ops and not (last and name == part):
                key = "/".join(parts[: i + 1]) + ("/" if i < len(parts) - 1 else "")
                if key not in units or units[key][0] != name:
                    units[key] = (name, name, "")
    rules = bhpresets._codeowners(root, preset["owner_files"]) if preset else []
    return {"codeowners": rules, "units": units, "ops": ops}


def owner_of(index: dict[str, Any], path: str) -> str | None:
    """A path's owner: CODEOWNERS' last matching line (GitHub's rule), else the deepest owner unit
    holding it."""
    who = None
    for spec, owner in index["codeowners"]:
        if spec.match_file(path) or spec.match_file(path.rstrip("/") + "/"):
            who = owner
    if who:
        return who
    hit = [k for k in index["units"] if path == k or path.startswith(k) or path + "/" == k]
    return index["units"][max(hit, key=len)][0] if hit else None


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


def packet_owners(root: Path, paths: list[str], cap: int) -> dict[str, list[str]]:
    """The owners of the given paths (an item's declared paths, or a diff's changed files) and
    each touched owner's published interface, one line each, at most ``cap`` characters: its
    packages' ``__all__`` names (PEP 8), as ``package (owner): names``, and its OpenAPI operations,
    as ``file (owner): operationId METHOD /path; ...``. A path no owner holds adds nothing."""
    index = owner_index(root)
    tracked = [p for p in _git(root, "ls-files", "-z", "--", *paths).split("\0") if p] if paths else []
    owners = sorted({o for p in [*paths, *tracked] if p and p != "." and (o := owner_of(index, p))})
    if not owners:
        return {}
    interfaces = []
    for d, (_, unit, init) in sorted(index["units"].items()):
        names = _published(root / init) if init and owner_of(index, d) in owners else []
        owner = owner_of(index, d)
        if names:
            interfaces.append(f"{unit} ({owner}): {', '.join(names)}"[:cap])
    for owner in owners:
        by_file: dict[str, list[str]] = {}
        for op in index["ops"].get(owner, []):
            by_file.setdefault(op["file"], []).append(f"{op['id']} {op['route']}".strip())
        interfaces += [f"{f} ({owner}): {'; '.join(o)}"[:cap] for f, o in by_file.items()]
    return {"owners": owners, "interfaces": list(dict.fromkeys(interfaces))}


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


def triggers(
    root: Path, cfg_data: dict[str, Any], base: str, ref: str, tier: str, kind: str = "slice"
) -> list[dict[str, str]]:
    """The review domains the item's whole diff ``base..ref`` touches, one fact per domain with the
    first path that set it. An empty list: no review runs. A design-affecting item is judged
    against its packet's rules and for duplication; a defect fix, at any tier, for its root cause."""
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
    index = owner_index(root)
    for t in cfg_data.get("review", {}).get("triggers", []):
        if "@" in t:  # a CODEOWNERS owner (GitHub's owner syntax)
            p = next((p for p in changed if owner_of(index, p) == t), None)
        else:
            spec = pathspec.PathSpec.from_lines("gitignore", [t])
            p = next((p for p in changed if spec.match_file(p)), None)
        if p:
            hits.setdefault(t, f"{p} is under review.triggers {t}")
    if tier == "design-affecting":
        hits["duplication"] = f"the item is {tier}"
    if kind == "defect":  # the fix is judged on whether it fixes the design (rule NO-12, Google SRE ch. 15 root cause)
        hits["root cause"] = "the item is a defect fix"
    return [{"domain": d, "detail": v} for d, v in hits.items()]


# ---------------------------------------------------------------- severity from the rule (QBC-114)

RANK = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
CITE = re.compile(r"([\w./-]+):(\d+)")


def _cited(root: Path, ref: str, reason: str, where: str) -> bool:
    """True when ``reason`` cites a ``file:line`` other than the finding's own ``where`` that exists
    in the reviewed tree at ``ref``: the evidence a lowering rests on, checkable by anyone."""
    for path, line in CITE.findall(reason or ""):
        text = _show(root, ref, path)
        if f"{path}:{line}" != where and text is not None and 0 < int(line) <= len(text.splitlines()):
            return True
    return False


def settle(
    findings: list[dict[str, Any]], meta: dict[str, dict[str, str]], root: Path, ref: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Each finding on a house rule takes the rule's default ``severity`` (SARIF
    ``defaultConfiguration.level``, Semgrep rule ``severity``), not the reviewer's feel. The reviewer
    may lower it only with a ``severity_reason`` citing a file:line of the reviewed tree that shows
    the rule does not apply at full weight, and raise it only with ``reproduced`` evidence; anything
    else is set back to the default. A finding on a triggered domain or an overlay row keeps the
    reviewer's triage. ``meta`` is ``bhrules.rule_meta``. Returns the settled findings and one
    record per change or refusal."""
    out, changes = [], []
    for f in findings:
        rule = meta.get(f.get("rule") or "")
        if rule is None:
            out.append(f)
            continue
        default, asked = rule["severity"], f.get("severity") or rule["severity"]
        sev, why = asked, ""
        if RANK[asked] < RANK[default] and f.get("evidence") != "reproduced":
            sev, why = default, "raise refused: only reproduced evidence raises a rule's default"
        elif RANK[asked] > RANK[default]:
            if _cited(root, ref, f.get("severity_reason", ""), f.get("where", "")):
                why = f"lowered: {f['severity_reason']}"
            else:
                sev, why = default, "lowering refused: severity_reason cites no other file:line of the reviewed tree"
        if why or sev != f.get("severity"):
            changes.append({"rule": f["rule"], "where": f.get("where", ""), "asked": f.get("severity", ""), "severity": sev, "why": why or "the rule's default"})
        out.append({**f, "severity": sev})
    return out, changes


# ---------------------------------------------------------------- findings as SARIF facts


def _right(rule: str, rule_right: str, wrong: str, here: str, chars: int) -> str:
    """The rule's right way, then ``here: <the reviewer's concrete application>`` cut to what the
    message cap leaves once the wrong part keeps its first 60 characters; the rule's own text is
    never cut for it (QBC-115)."""
    room = chars - len(f"[{rule}]  ->  . bh rule {rule}") - len(rule_right) - min(len(wrong), 60) - len("; here: ")
    if not here or room < 20:
        return rule_right
    return f"{rule_right}; here: {here if len(here) <= room else here[: room - 3] + '...'}"


def sarif(
    findings: list[dict[str, Any]], item: str, digest: str, chars: int, meta: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    """The reviewer's findings as one SARIF 2.1.0 log, checked against the official schema. The
    summary is written ``wrong -> the right way, and how to prevent it`` (the review job schema).
    On a house rule (``meta``, ``bhrules.rule_meta``; QBC-115) the right way is the rule's own
    ``right`` text, then the reviewer's concrete application of it, so no finding teaches a weaker
    remedy than its rule, and the reference is ``bh rule <id>``; the rule goes in
    ``tool.driver.rules`` with its default level and that text as ``help``."""
    from jsonschema.validators import validator_for

    meta = meta or {}
    results, described = [], {}
    for f in findings:
        wrong, _, right = (x.strip() for x in f["summary"].partition("->"))
        rule = f.get("rule") or "review"
        ref = STANDARD
        if rule in meta:
            m = meta[rule]
            right, ref = _right(rule, m["right"].rstrip("."), wrong, right, chars), f"bh rule {rule}"
            described[rule] = {
                "id": rule,
                "defaultConfiguration": {"level": LEVEL[m["severity"]]},
                "help": {"text": m["right"]},
                "properties": {"severity": m["severity"]},
            }
        res: dict[str, Any] = {
            "ruleId": rule,
            "level": LEVEL.get(f.get("severity", ""), "warning"),
            "message": {"text": _teach(rule, wrong, right, ref)[:chars]},
            "properties": {k: f[k] for k in ("severity", "evidence", "severity_reason") if k in f},
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
                "tool": {
                    "driver": {
                        "name": "harness-reviewer",
                        "informationUri": "https://csrc.nist.gov/pubs/sp/800/218/final",
                        **({"rules": list(described.values())} if described else {}),
                    }
                },
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


def finished(log: dict[str, Any]) -> bool:
    """Whether the review ran to its end: SARIF 2.1.0 ``invocations[].executionSuccessful``."""
    return all(i.get("executionSuccessful", True) for i in log["runs"][0].get("invocations", []))


def admission(log: dict[str, Any] | None, override: str | None = None) -> dict[str, Any]:
    """Main's entry check (QBC-118): the one decision of whether a reviewed change enters the
    protected default branch, for the builder's merge, ``bh land`` and ``bh review`` in a pull
    request's required status check alike (G2). An open S1 or S2 finding (SARIF ``error``) is not
    admitted and goes back to its author in teach form; S3 and S4 are annotations. A review that
    did not finish is not admitted (main cannot judge an unreviewed change). No review (no trigger,
    0 tokens) is admitted. An owner ``override`` admits with its reason, which the caller records
    as a fact (GitHub ruleset bypass list with its audit)."""
    if log is None:
        return {"admitted": True, "reviewed": False, "blocking": [], "annotations": []}
    blocking = errors(log)
    if not finished(log):
        blocking.append(_teach("main-entry", "the review did not finish, so main cannot judge the change", "run the review again", "bh review BASE..HEAD"))
    notes = [r["message"]["text"] for r in log["runs"][0]["results"] if r["level"] != "error"]
    out = {"admitted": not blocking, "reviewed": True, "blocking": blocking, "annotations": notes}
    if blocking and override:
        out |= {"admitted": True, "override": override}
    return out


def refusal(blocking: list[str], what: str) -> str:
    """The teach-form line of a change main does not admit (QBC-118, QBC-53)."""
    return _teach(
        "main-entry",
        f"{what} has {len(blocking)} open S1/S2 review finding(s), so main does not admit it",
        "fix each finding in its design element, then review again",
        "meet the packet's rule lines while writing; an owner may admit it with bh land --override REASON",
    )


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


# ---------------------------------------------------------------- main's entry check on GitHub (QBC-119)

GITHUB_TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / ".github"
ENTRY_FILES = ("workflows/bh-review.yml", "rulesets/bh-main.json")
GITHUB_REMOTE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


def github_slug(root: Path) -> str | None:
    """``owner/repo`` of the ``origin`` remote when it is on GitHub, else None (no hosting)."""
    url = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=root, capture_output=True, text=True).stdout.strip()
    m = GITHUB_REMOTE.search(url)
    return m.group(1) if m else None


def repo_owner(slug: str) -> dict[str, Any] | None:
    """The repository owner as a ruleset bypass actor (``User``, or ``OrganizationAdmin`` for an
    organization's repository), read with ``gh api``; None when gh cannot read it."""
    p = subprocess.run(["gh", "api", f"repos/{slug}", "--jq", ".owner.type + \" \" + (.owner.id|tostring)"], capture_output=True, text=True)
    kind, _, oid = p.stdout.strip().partition(" ")
    if p.returncode != 0 or not oid.isdigit():
        return None
    if kind == "Organization":
        return {"actor_id": None, "actor_type": "OrganizationAdmin", "bypass_mode": "pull_request"}
    return {"actor_id": int(oid), "actor_type": "User", "bypass_mode": "pull_request"}


def install_entry(root: Path, approved: bool) -> dict[str, Any]:
    """Main's entry check as GitHub's own standard files (QBC-119), one setup write in the one
    setup question: a ruleset for the default branch (pull request required, the required status
    check ``bh-review``, the repository owner on the bypass list; GitHub's ruleset JSON, imported
    with ``gh api``) and the workflow whose job ``bh-review`` runs ``bh land --check`` on the pull
    request. Never over a file the project has. With no GitHub remote there is nothing to write:
    ``bh land`` is the path (P12)."""
    slug = github_slug(root)
    if slug is None:
        return {"written": [], "pending": []}
    missing = [f for f in ENTRY_FILES if not (root / ".github" / f).exists()]
    if not approved:
        return {"written": [], "pending": [f".github/{f}" for f in missing]}
    version = json.loads((GITHUB_TEMPLATES.parents[1] / ".claude-plugin" / "plugin.json").read_text())["version"]
    out: dict[str, Any] = {"written": [], "skipped": [f".github/{f}" for f in ENTRY_FILES if f not in missing]}
    for f in missing:
        text = (GITHUB_TEMPLATES / f).read_text()
        if f.endswith(".yml"):
            text = text.replace("__DEFAULT_BRANCH__", default_branch(root) or "main").replace("__PLUGIN_REF__", f"v{version}")
        else:
            doc = json.loads(text)
            owner = repo_owner(slug)
            doc["bypass_actors"] = [owner] if owner else []
            if not owner:
                out["note"] = "gh could not read the repository owner: add the owner to the ruleset's bypass list before importing it"
            text = json.dumps(doc, indent=2) + "\n"
        (root / ".github" / f).parent.mkdir(parents=True, exist_ok=True)
        (root / ".github" / f).write_text(text)
        out["written"].append(f".github/{f}")
    out["apply"] = f"gh api -X POST repos/{slug}/rulesets --input .github/rulesets/bh-main.json"
    return out
