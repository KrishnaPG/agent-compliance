"""The plugin must stay project-neutral: no names, hosts or commands of a project using it.

Generic terms (model names, machine paths) are listed here. Project terms are not: naming
them here would leak them into the plugin. They are read, one regular expression per line,
from the file named by BH_DENY_TERMS, else ~/.config/brick-harness/deny-terms.txt; that
part of the check is skipped when neither exists.
"""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GENERIC = [
    r"workspace/",
    r"/home/\w+",
    r"\bhaiku\b",
    r"\bsonnet\b",
    r"\bopus\b",
    r"\bfable\b",
    r"claude-[a-z]+-\d",
]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "out"}


def project_terms() -> list[str] | None:
    p = Path(
        os.environ.get("BH_DENY_TERMS") or Path.home() / ".config/brick-harness/deny-terms.txt"
    )
    if not p.is_file():
        return None
    return [
        t for t in (x.strip() for x in p.read_text().splitlines()) if t and not t.startswith("#")
    ]


def hits(patterns: list[str]) -> list[str]:
    me = Path(__file__).resolve()
    out = []
    plugin = ROOT.parent  # the harness's own files: harness/, bin/ and its skill
    for p in [
        *ROOT.rglob("*"),
        *(plugin / "bin").rglob("*"),
        *(plugin / "skills" / "harness").rglob("*"),
        *(plugin / "agents").rglob("*"),
    ]:
        if p.is_dir() or p.resolve() == me or SKIP_DIRS & set(p.parts):
            continue
        text = p.read_text(errors="ignore")
        if (
            "agents" in p.relative_to(plugin).parts[:1]
        ):  # the model alias is the frontmatter's job (W4)
            text = re.sub(r"^model:.*$", "", text, flags=re.M)
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                out.append(f"{p.relative_to(plugin)}: {m.group(0)!r}")
    return out


def test_no_generic_machine_or_model_terms():
    assert hits(GENERIC) == []


def test_no_project_terms():
    terms = project_terms()
    if terms is None:
        pytest.skip(
            "no deny-list: set BH_DENY_TERMS or write ~/.config/brick-harness/deny-terms.txt"
        )
    assert hits(terms) == []
