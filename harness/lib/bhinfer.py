"""What the project's own standard files say (P9, QBC-60/61 B): the one owner of inference.

Convention over configuration, as buildpacks and GitHub starter workflows detect a project: the
test entry from the justfile, Makefile, package.json or the pytest configuration; the language,
the toolchain install and the add-a-dependency command from the lockfile; the build order and
features documents from their conventional names. Each value is a fact ``{"value", "source"}``
that names the file it came from, so a run can show why it ran what it ran. A value no standard
file gives is left out; ``questions`` turns the ones a run needs into one owner question each,
answered by writing that standard file (QBC-61 D, QBC-63: never a plugin file).

Every other module reads these values here; none keeps its own detector. A project config
(``.brick-harness/config.json``) is optional and only overrides (P8).
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

# lockfile or manifest -> language, first match wins (a lockfile names its tool exactly)
LANGUAGE = (
    ("uv.lock", "python"),
    ("poetry.lock", "python"),
    ("pyproject.toml", "python"),
    ("pytest.ini", "python"),
    ("package-lock.json", "node"),
    ("pnpm-lock.yaml", "node"),
    ("yarn.lock", "node"),
    ("package.json", "node"),
)
# Each toolchain's own standard install from its lockfile, run open (it needs the network)
# before the sealed run, in file order: tools first, then packages. The install goes into the
# checkout (copied, not hardlinked to the host cache, which a test could then rewrite) and
# runs no package scripts. Each install is the locked one: it fails when the lockfile no longer
# matches the manifest (uv --locked, npm ci, pnpm --frozen-lockfile), so an unlocked dependency
# is the same fact a human's install reports. mise checks only a mise.lock the project keeps.
PREPARE = (
    ("mise.toml", "mise install"),
    (".tool-versions", "mise install"),
    ("uv.lock", "uv sync --locked --link-mode=copy"),
    ("package-lock.json", "npm ci --ignore-scripts"),
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile --ignore-scripts"),
)
LOCK_ADD = (  # lockfile -> the package manager's own add command (the lockfile names the tool)
    ("uv.lock", "uv add <package>"),
    ("poetry.lock", "poetry add <package>"),
    ("pnpm-lock.yaml", "pnpm add <package>"),
    ("yarn.lock", "yarn add <package>"),
    ("package-lock.json", "npm install <package>"),
)
NODE_RUNNER = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"))
BUILD_ORDER_NAMES = ("docs/build-order.md", "build-order.md", "docs/BUILD_ORDER.md")
FEATURES_NAMES = ("docs/features.md", "features.md")
PYTEST_FILES = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
RECIPE = re.compile(r"^@?test\s*(?:\S.*)?:(?!=)")  # a justfile recipe or make target named test


def _fact(value: Any, source: str) -> dict[str, Any]:
    return {"value": value, "source": source}


def _has_recipe(path: Path) -> bool:
    return path.is_file() and any(
        RECIPE.match(ln) for ln in path.read_text(errors="ignore").splitlines()
    )


def _package_json(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / "package.json").read_text())
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _pytest_config(root: Path) -> str | None:
    """The file that configures pytest: pytest.ini, a ``[tool.pytest.ini_options]`` table, or a
    ``[pytest]``/``[tool:pytest]`` section (pytest's own lookup order)."""
    for name in PYTEST_FILES:
        p = root / name
        if not p.is_file():
            continue
        text = p.read_text(errors="ignore")
        if (
            name == "pytest.ini"
            or (name == "pyproject.toml" and "pytest" in tomllib.loads(text).get("tool", {}))
            or re.search(r"^\[(tool:)?pytest\]", text, re.M)
        ):
            return name
    return None


def _any_python(root: Path) -> str | None:
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        py = next((f for f in files if f.endswith(".py")), None)
        if py:
            return (Path(d) / py).relative_to(root).as_posix()
    return None


def test_roots(root: Path) -> dict[str, Any] | None:
    """The project's test roots as its test runner's own config names them: pytest's
    ``testpaths``, else node's default ``test`` directory."""
    py = root / "pyproject.toml"
    if py.is_file():
        opts = (
            tomllib.loads(py.read_text()).get("tool", {}).get("pytest", {}).get("ini_options", {})
        )
        if opts.get("testpaths"):
            return _fact(list(opts["testpaths"]), "pyproject.toml")
    if (root / "package.json").is_file() and (root / "test").is_dir():
        return _fact(["test"], "package.json")
    return None


def infer(root: Path) -> dict[str, dict[str, Any]]:
    """Every value the project's standard files give: key -> {"value", "source"}."""
    out: dict[str, dict[str, Any]] = {}
    lang = next(((f, lang) for f, lang in LANGUAGE if (root / f).is_file()), None)
    if lang is None and (py := _any_python(root)):
        lang = (py, "python")
    if lang:
        out["language"] = _fact(lang[1], lang[0])
    pkg = _package_json(root)
    if _has_recipe(root / "justfile"):
        out["test"] = _fact("just test", "justfile")
    elif _has_recipe(root / "Makefile"):
        out["test"] = _fact("make test", "Makefile")
    elif isinstance(pkg.get("scripts"), dict) and pkg["scripts"].get("test"):
        runner = next((r for f, r in NODE_RUNNER if (root / f).is_file()), "npm")
        out["test"] = _fact(f"{runner} test", "package.json")
    elif (cfg := _pytest_config(root)) or (lang and lang[1] == "python"):
        out["test"] = _fact("pytest", cfg or lang[0])  # type: ignore[index]
    install = [(f, c) for f, c in PREPARE if (root / f).is_file()]
    if install:
        out["install"] = _fact(
            list(dict.fromkeys(c for _, c in install)), ", ".join(f for f, _ in install)
        )
    dep = next(((f, c) for f, c in LOCK_ADD if (root / f).is_file()), None)
    if dep:
        out["dependency"] = _fact(dep[1], dep[0])
    for key, names in (("build_order", BUILD_ORDER_NAMES), ("features", FEATURES_NAMES)):
        hit = next((n for n in names if (root / n).is_file()), None)
        if hit:
            out[key] = _fact(hit, hit)
    roots = test_roots(root)
    if roots:
        out["test_paths"] = roots
    return out


def junit_env(language: str | None, junit: Path) -> dict[str, str]:
    """The environment that makes the language's own test runner write JUnit XML to ``junit``
    whatever recipe starts it: pytest reads ``PYTEST_ADDOPTS``, node's test runner reads its
    reporter flags from ``NODE_OPTIONS``."""
    if language == "node":
        return {"NODE_OPTIONS": f"--test-reporter=junit --test-reporter-destination={junit}"}
    return {}


def test_run(facts: dict[str, dict[str, Any]]) -> str | None:
    """The inferred test entry as a command writing JUnit XML to ``{out}/junit.xml`` (the
    config's ``commands.test.run`` form): pytest gets ``--junitxml``, node's test runner its
    reporter flags through ``NODE_OPTIONS``, any other recipe pytest's through
    ``PYTEST_ADDOPTS`` (pytest reads it whatever the recipe runs first)."""
    test = facts.get("test", {}).get("value")
    if test is None:
        return None
    if test == "pytest":
        run = (
            "uv run pytest"
            if facts.get("install", {}).get("source", "").find("uv.lock") >= 0
            else "python -m pytest"
        )
        return f"{run} -q --junitxml {{out}}/junit.xml"
    if facts.get("language", {}).get("value") == "node":
        return f"NODE_OPTIONS='--test-reporter=junit --test-reporter-destination={{out}}/junit.xml' {test}"
    return f"PYTEST_ADDOPTS=--junitxml={{out}}/junit.xml {test}"


def questions(facts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """One owner question per value a run needs that no standard file gives (asked once: the
    answer is the standard file, which the next run infers from)."""
    if "test" in facts:
        return []
    return [
        {
            "id": "Q-test",
            "kind": "test-command-unknown",
            "summary": "no test entry found: add a `test` recipe to the justfile (or a `test` "
            "target to the Makefile, or scripts.test to package.json); the next run infers it",
            "evidence": "justfile, Makefile, package.json, pyproject.toml",
        }
    ]


def acceptance_name(language: str | None, slug: str) -> str:
    """The acceptance test file name the language's own runner collects by default."""
    return f"{slug}.test.js" if language == "node" else f"test_{slug}.py"


def facts_lines(facts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """The inferred values as run facts, each naming its source file."""
    return [
        {"kind": "inferred", "detail": f"{k}: {v['value']} (from {v['source']})"}
        for k, v in facts.items()
    ]
