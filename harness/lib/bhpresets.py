"""Write the plugin's linter presets into the project's own standard files (QBC-61 C + D, QBC-63).

A library with no entry point of its own: the setup inference calls ``apply`` (and
``record_owner`` for an ask-once answer).

The preset table is ``harness/checkers.json`` ``presets``, keyed by stack. For a stack it writes
the project's ``pyproject.toml`` (``[tool.ruff.lint]``, ``[tool.importlinter]``, or an existing
``.importlinter``), its ``.pre-commit-config.yaml`` (local hooks calling the tools the project's
own lockfile pins, so a sealed run needs no download) and the dev dependency group (through the
stack's own package manager). No plugin file is written.

Import boundaries are derived from the owner map (rung 2): owner units are the sub-packages of
each root package; a unit's owner is its CODEOWNERS owner (GitHub's last-match rule), else the
tag of the OpenAPI operations whose ``operationId`` names a module in it (the Connexion
convention), else the unit's own name. Each owner gets one import-linter ``private_modules``
contract: a module whose name starts with ``_`` (PEP 8 internal) is importable only from its
own package.

Ratchet (P11): findings that exist when a rule is first enabled become the baseline
(``[tool.ruff.lint.extend-per-file-ignores]``, each contract's ``ignore_imports``); a later run
only drops entries that no longer match, never adds.

Tools adopted: ruff, import-linter, pre-commit, uv; tomlkit and ruamel.yaml for round-trip edits;
pathspec for CODEOWNERS patterns (gitignore syntax).
"""

from __future__ import annotations

import configparser
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pathspec
import tomlkit
from ruamel.yaml import YAML

CHECKERS = Path(__file__).resolve().parent.parent / "checkers.json"
IMPORT_LINE = re.compile(r"^-\s+(\S+) -> (\S+) \(l\.")


def presets() -> dict[str, Any]:
    return json.loads(CHECKERS.read_text())["presets"]


def stacks(root: Path) -> list[str]:
    """The preset stacks whose marker file the project has."""
    return [s for s, p in presets().items() if (root / p["detect"]).is_file()]


def _run(cmd: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(shlex.split(cmd), cwd=root, capture_output=True, text=True)


# ---------------------------------------------------------------- owner map


def root_packages(root: Path) -> list[tuple[str, Path]]:
    """(name, dir) of each top-level import package, flat or src layout."""
    out = []
    for base in (root / "src", root):
        if base.is_dir():
            out += [(d.name, d) for d in sorted(base.iterdir()) if (d / "__init__.py").is_file()]
    return out


def _codeowners(root: Path, files: list[str]) -> list[tuple[pathspec.PathSpec, str]]:
    rules = []
    for f in files:
        p = root / f
        if p.is_file():
            for line in p.read_text().splitlines():
                parts = line.split("#", 1)[0].split()
                if len(parts) >= 2:
                    rules.append((pathspec.PathSpec.from_lines("gitignore", [parts[0]]), parts[1]))
            break  # GitHub reads the first CODEOWNERS it finds
    return rules


def _openapi_owners(root: Path, globs: list[str]) -> dict[str, str]:
    """module -> owner tag, from operations that name their handler (``operationId: pkg.mod.fn``)."""
    yaml = YAML(typ="safe")
    out: dict[str, str] = {}
    for g in globs:
        for f in sorted(root.glob(g)):
            doc = yaml.load(f.read_text()) or {}
            for ops in (doc.get("paths") or {}).values():
                for op in (ops or {}).values():
                    if isinstance(op, dict) and op.get("tags") and "." in str(op.get("operationId", "")):
                        out[op["operationId"].rsplit(".", 1)[0]] = op["tags"][0]
    return out


def owner_map(root: Path, preset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """owner -> {"units": [dotted packages], "source": how the owner was found}."""
    rules = _codeowners(root, preset["owner_files"])
    tags = _openapi_owners(root, preset["openapi_globs"])
    owners: dict[str, dict[str, Any]] = {}
    for name, d in root_packages(root):
        for unit in sorted(u for u in d.iterdir() if (u / "__init__.py").is_file()):
            dotted = f"{name}.{unit.name}"
            rel = unit.relative_to(root).as_posix() + "/"
            owner, source = unit.name, "package folder"
            for spec, who in rules:  # last match wins
                if spec.match_file(rel) or spec.match_file(rel + "__init__.py"):
                    owner, source = who, "CODEOWNERS"
            if source != "CODEOWNERS":
                tag = next((t for m, t in tags.items() if m == dotted or m.startswith(dotted + ".")), None)
                if tag:
                    owner, source = tag, "OpenAPI tag"
            o = owners.setdefault(owner, {"units": [], "source": source})
            o["units"].append(dotted)
    return owners


def record_owner(root: Path, preset: dict[str, Any], pattern: str, owner: str) -> str:
    """The ask-once answer, stored in the project's CODEOWNERS (the standard file)."""
    path = next((root / f for f in preset["owner_files"] if (root / f).is_file()), root / ".github" / "CODEOWNERS")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.is_file() else ""
    line = f"{pattern} {owner}"
    if line not in text.splitlines():
        path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")
    return str(path.relative_to(root))


def _slug(owner: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-")


def contracts(owners: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for owner, o in sorted(owners.items()):
        units = ", ".join(o["units"])
        out.append(
            {
                "id": f"owner-{_slug(owner)}",
                "name": f"[owner] the private (_name) modules of {units} belong to {owner}",
                "type": "private_modules",
                "packages_with_private_modules": o["units"],
                "broken_contract_guidance": (
                    f"[owner] code outside {owner} imports its private modules -> import {owner}'s "
                    f"published interface ({units}) or ask {owner} to publish the name; prevent it: "
                    "call another owner only through names without a leading _ . ref: PEP 8"
                ),
            }
        )
    return out


# ---------------------------------------------------------------- writers


def _table(doc: Any, *keys: str) -> Any:
    t = doc
    for k in keys:
        if k not in t:
            t[k] = tomlkit.table(is_super_table=k != keys[-1])
        t = t[k]
    return t


class PresetError(Exception):
    pass


def _ruff_findings(root: Path, preset: dict[str, Any]) -> dict[str, set[str]]:
    """file -> codes the project's ruff config reports (run while the ratchet table is absent)."""
    r = _run(f"{preset['run']} ruff check --exit-zero --no-cache --output-format json .", root)
    if r.returncode != 0:
        raise PresetError(f"ruff failed, the baseline is left as it was: {r.stderr.strip()[-300:]}")
    found: dict[str, set[str]] = {}
    for f in json.loads(r.stdout or "[]"):
        rel = Path(f["filename"]).resolve().relative_to(root.resolve()).as_posix()
        found.setdefault(rel, set()).add(f["code"])
    return found


def write_ruff(root: Path, preset: dict[str, Any], newly_run: bool) -> dict[str, Any]:
    """Enable the preset codes; the codes the build runs for the first time (every code when the
    ruff hook is new, else the newly enabled preset codes) get today's findings as their baseline,
    and a baseline entry that no longer matches is dropped."""
    path = root / "pyproject.toml"
    original = path.read_text()
    doc = tomlkit.parse(original)
    lint = _table(doc, "tool", "ruff", "lint")
    want = preset["ruff"]["extend-select"]
    had = list(lint.get("extend-select", []))
    new = [c for c in want if c not in had]
    lint["extend-select"] = had + new
    banned = _table(doc, "tool", "ruff", "lint", "flake8-tidy-imports", "banned-api")
    for api, msg in preset["ruff"]["banned-api"].items():
        if api not in banned:
            banned[api] = {"msg": msg}
    old = {k: list(v) for k, v in lint.get("extend-per-file-ignores", {}).items()}
    bare = tomlkit.parse(tomlkit.dumps(doc))  # ruff runs while the ratchet table is absent
    _table(bare, "tool", "ruff", "lint").pop("extend-per-file-ignores", None)
    path.write_text(tomlkit.dumps(bare))
    try:
        found = _ruff_findings(root, preset)
    except PresetError:
        path.write_text(original)
        raise
    base: dict[str, list[str]] = {}
    own = {f: c for f, c in old.items() if any(ch in f for ch in "*?[")}  # the project's globs stay
    for f in sorted((set(old) | set(found)) - set(own)):
        now = found.get(f, set())
        keep = [c for c in old.get(f, []) if any(x.startswith(c) for x in now)]
        added = sorted(c for c in now if (newly_run or any(c.startswith(n) for n in new)) and not any(c.startswith(k) for k in keep))
        if keep + added:
            base[f] = keep + added
    base = {**own, **base}
    if base and "extend-per-file-ignores" not in lint:
        lint["extend-per-file-ignores"] = tomlkit.table()
    if "extend-per-file-ignores" in lint:
        pfi = lint["extend-per-file-ignores"]
        for f in [f for f in pfi if f not in base]:
            del pfi[f]
        for f, codes in base.items():
            if list(pfi.get(f, [])) != codes:
                pfi[f] = codes
        if not base:
            del lint["extend-per-file-ignores"]
    path.write_text(tomlkit.dumps(doc))
    return {"enabled": new, "baseline": {f: c for f, c in base.items() if f not in own}}


def _lint_imports(root: Path, preset: dict[str, Any], cid: str) -> set[str]:
    r = _run(f"{preset['run']} lint-imports --no-cache --contract {cid}", root)
    if "Contracts:" not in r.stdout:
        raise PresetError(f"lint-imports failed, the baseline is left as it was: {(r.stdout + r.stderr).strip()[-300:]}")
    return {f"{m.group(1)} -> {m.group(2)}" for line in r.stdout.splitlines() if (m := IMPORT_LINE.match(line))}


def write_importlinter(root: Path, preset: dict[str, Any], owners: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Contracts from the owner map into ``.importlinter`` when the project has one, else pyproject."""
    ini = root / ".importlinter"
    roots = [n for n, _ in root_packages(root)]
    wanted = contracts(owners)
    if not wanted:
        return {"contracts": [], "baseline": {}}

    def load() -> tuple[Any, list[str], dict[str, list[str]]]:
        if ini.is_file():
            cp = configparser.ConfigParser()
            cp.read(ini)
            have = {s.split(":", 2)[2]: cp[s].get("ignore_imports", "").split() for s in cp.sections() if s.startswith("importlinter:contract:")}
            return cp, cp.get("importlinter", "root_packages", fallback="").split(), {k: [" ".join(v[i:i + 3]) for i in range(0, len(v), 3)] for k, v in have.items()}
        doc = tomlkit.parse((root / "pyproject.toml").read_text())
        il = doc.get("tool", {}).get("importlinter", {})
        return doc, list(il.get("root_packages", [])), {c.get("id"): list(c.get("ignore_imports", [])) for c in il.get("contracts", [])}

    def save(obj: Any, rp: list[str], ignores: dict[str, list[str]]) -> None:
        if ini.is_file():
            obj["importlinter"] = {**obj["importlinter"], "root_packages": "\n" + "\n".join(rp)} if obj.has_section("importlinter") else {"root_packages": "\n" + "\n".join(rp)}
            for c in wanted:
                obj[f"importlinter:contract:{c['id']}"] = {
                    "name": c["name"],
                    "type": c["type"],
                    "packages_with_private_modules": "\n" + "\n".join(c["packages_with_private_modules"]),
                    "broken_contract_guidance": c["broken_contract_guidance"],
                    **({"ignore_imports": "\n" + "\n".join(ignores[c["id"]])} if ignores.get(c["id"]) else {}),
                }
            with ini.open("w") as fh:
                obj.write(fh)
            return
        il = _table(obj, "tool", "importlinter")
        il["root_packages"] = rp
        arr = il.get("contracts") or tomlkit.aot()
        keep = [c for c in arr if c.get("id") not in {w["id"] for w in wanted}]
        new = tomlkit.aot()
        for c in keep:
            new.append(c)
        for c in wanted:
            t = tomlkit.table()
            t.update(c)
            if ignores.get(c["id"]):
                t["ignore_imports"] = ignores[c["id"]]
            new.append(t)
        il["contracts"] = new
        (root / "pyproject.toml").write_text(tomlkit.dumps(obj))

    target = ini if ini.is_file() else root / "pyproject.toml"
    original = target.read_text()
    obj, rp, old = load()
    rp = rp + [r for r in roots if r not in rp]
    save(obj, rp, {})
    ignores = {}
    try:
        for c in wanted:
            now = _lint_imports(root, preset, c["id"])
            ignores[c["id"]] = sorted(now & set(old[c["id"]]) if c["id"] in old else now)
    except PresetError:
        target.write_text(original)
        raise
    obj, _, _ = load()
    save(obj, rp, ignores)
    return {"contracts": [c["id"] for c in wanted], "baseline": {k: v for k, v in ignores.items() if v}}


def write_precommit(root: Path, preset: dict[str, Any]) -> list[str]:
    """Add the preset hooks as one local repo; a hook id the project already has stays its own."""
    path = root / ".pre-commit-config.yaml"
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    doc = yaml.load(path.read_text()) if path.is_file() else None
    doc = doc if doc is not None else {"repos": []}
    repos = doc.setdefault("repos", [])
    have = {h.get("id") for r in repos for h in (r.get("hooks") or [])}
    add = [h for h in preset["hooks"] if h["id"] not in have]
    if add:
        local = next((r for r in repos if r.get("repo") == "local"), None)
        if local is None:
            local = {"repo": "local", "hooks": []}
            repos.append(local)
        local["hooks"].extend(add)
        with path.open("w") as fh:
            yaml.dump(doc, fh)
    return [h["id"] for h in add]


def write_recipe(root: Path, preset: dict[str, Any]) -> str | None:
    """Make the project's one test entry (QBC-16; the ``test`` recipe ``bhinfer`` infers) run the
    preset's lint as its last line, so a human's ``just test`` and the measurer run the hooks a
    commit runs. With no ``test`` recipe the justfile gets one: the inferred test command, then the
    lint. Returns the line added, or None when the recipe already runs it."""
    import bhinfer

    lint, path = preset["lint"], root / "justfile"
    lines = path.read_text().splitlines() if path.is_file() else []
    if any(ln.strip() == lint for ln in lines):
        return None
    at = next((n for n, ln in enumerate(lines) if bhinfer.RECIPE.match(ln)), None)
    if at is None:
        test = bhinfer.infer(root).get("test", {}).get("value", "pytest")
        lines += ([""] if lines else []) + ["test:", f"    {preset['run']} {test}" if test == "pytest" else f"    {test}"]
        at = len(lines) - 2
    end = at + 1
    while end < len(lines) and lines[end][:1] in (" ", "\t"):
        end += 1
    indent = re.match(r"[ \t]+", lines[at + 1]).group(0) if end > at + 1 else "    "  # type: ignore[union-attr]
    lines.insert(end, indent + lint)
    path.write_text("\n".join(lines) + "\n")
    return lint


def apply(root: Path, owners_answered: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Write every detected stack's presets into the project's standard files."""
    report: dict[str, Any] = {}
    for stack in stacks(root):
        p = presets()[stack]
        rec = [record_owner(root, p, pat, who) for pat, who in owners_answered or []]
        r = _run(p["add_tools"].format(tools=" ".join(p["tools"])), root)
        if r.returncode != 0:
            report[stack] = {"error": f"`{p['add_tools']}` failed: {r.stderr.strip()[-300:]}"}
            continue
        owners = owner_map(root, p)
        hooks = write_precommit(root, p)
        recipe = write_recipe(root, p)
        try:
            ruff = write_ruff(root, p, "ruff" in hooks)
            imports = write_importlinter(root, p, owners)
        except PresetError as e:
            report[stack] = {"error": str(e)}
            continue
        report[stack] = {
            "ruff": ruff,
            "importlinter": imports,
            "pre-commit": hooks,
            **({"recipe": recipe} if recipe else {}),
            "owners": owners,
            "ask": sorted(o for o, v in owners.items() if v["source"] == "package folder"),
            **({"codeowners": sorted(set(rec))} if rec else {}),
        }
        _run(f"{p['run']} pre-commit install", root)  # the human's commit runs the same hooks
    return report

