"""Linter presets in the project's own files (QBC-62, QBC-63, R7, G2): ``bhpresets.apply`` writes
them into pyproject.toml and .pre-commit-config.yaml, derives the import contracts from the owner
map (QBC-19 rung 2), and baselines today's findings so the list only shrinks (P11, QBC-23). Each
planted defect class is then the same fact for a human (the refused commit) and for the measurer.

Offline whenever the run is (the run's UV_OFFLINE, set for every row): the pinned tools come from uv's
cache, filled once by provisioning (harness/README.md, Develop), and the project's own remote hook is a
git repository on disk."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import bhcore
import bhpresets
import pytest

PLUGIN = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("uv", "bwrap", "git", "just")), reason="needs uv, bwrap, git and just"
)

PYPROJECT = """[project]
name = "toy"
version = "0.1.0"
requires-python = "==3.14.*"
dependencies = []

[build-system]
requires = ["uv_build>=0.9,<1"]
build-backend = "uv_build"

[tool.ruff.lint.extend-per-file-ignores]
"tests/**" = ["S101"]
"""
OPENAPI = """openapi: 3.1.0
info: {title: toy, version: "1"}
paths:
  /orders:
    post:
      tags: [sales]
      operationId: toy.orders.api.create
      responses: {"201": {description: created}}
"""
PRECOMMIT = """# the project's own hooks
repos:
  - repo: {repo}
    rev: {rev}
    hooks:
      - id: check-toml
"""
HOOK_REPO = {
    ".pre-commit-hooks.yaml": "- id: check-toml\n  name: check toml\n  entry: check.sh\n  language: unsupported_script\n  files: \\.toml$\n",
    "check.sh": "#!/bin/sh\nexit 0\n",
}
LEGACY = "import datetime\n\nSTAMP = datetime.datetime.now()\n"  # today's finding: the baseline


def unlocked(d: Path) -> str:
    return (d / "pyproject.toml").read_text().replace("dependencies = []", 'dependencies = ["six"]', 1)


def gamed(d: Path) -> str:
    """A builder that silences its new finding by growing the baseline."""
    return (d / "pyproject.toml").read_text().replace(
        '[tool.ruff.lint.extend-per-file-ignores]\n', '[tool.ruff.lint.extend-per-file-ignores]\n"src/toy/orders/when.py" = ["DTZ005"]\n', 1
    )


WHEN = "import datetime\n\n\ndef now():\n    return datetime.datetime.now()\n"
PLANTS = {  # defect class -> ({file: text or fn(project)}, hook, what both runs must name)
    "naive datetime": ({"src/toy/orders/when.py": WHEN}, "ruff", "DTZ005"),
    "hard-coded secret": ({"src/toy/orders/auth.py": 'password = "hunter2-very-secret"\n'}, "ruff", "S105"),
    "magic value": ({"src/toy/orders/limit.py": "def full(n: int) -> bool:\n    return n > 42\n"}, "ruff", "PLR2004"),
    "sleep or polling": ({"src/toy/orders/wait.py": "import time\n\n\ndef wait():\n    time.sleep(1)\n"}, "ruff", "TID251"),
    "cross-owner import": ({"src/toy/orders/pay.py": "from toy.billing._ledger import post\n\nPOST = post\n"}, "import-linter", "toy.orders.pay -> toy.billing._ledger"),
    "unlocked dependency": ({"pyproject.toml": unlocked}, "uv-lock", "needs to be updated"),
}


def sh(d: Path, *cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=d, capture_output=True, text=True, check=check)


def git(d: Path, *a: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sh(d, "git", "-c", "user.email=t@t", "-c", "user.name=t", *a, check=check)


def presets(d: Path, *answers: tuple[str, str]) -> dict:
    report = bhpresets.apply(d, list(answers))["python"]
    assert "error" not in report, report
    return report


def human(d: Path) -> subprocess.CompletedProcess[str]:
    return sh(d, "uv", "run", "--frozen", "pre-commit", "run", "--all-files", check=False)


def measure(d: Path, ref: str = "HEAD") -> dict:
    return bhcore.measure_ref(bhcore.Config(d / ".brick-harness" / "config.json", partial=True), ref)


def no_clones(d: Path) -> bool:
    """Only each measured clone's .git is left: the checkout and its .venv are gone."""
    c = d / ".brick-harness" / "clones"
    return not c.is_dir() or all([p.name for p in x.iterdir()] == [".git"] for x in c.iterdir())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MISE_GLOBAL_CONFIG_FILE", str(PLUGIN / ".tool-versions"))  # the recipe's just


def hook_repo(d: Path) -> tuple[str, str]:
    """A remote hook repository (pre-commit clones it like any URL), on disk."""
    for f, text in HOOK_REPO.items():
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text(text)
    (d / "check.sh").chmod(0o755)
    git(d, "init", "-q", "-b", "main")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "hook")
    return str(d), git(d, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture(scope="module")
def toy(tmp_path_factory, suite_pin):
    d = tmp_path_factory.mktemp("toy")
    repo, rev = hook_repo(tmp_path_factory.mktemp("hooks"))
    for f, text in {
        "pyproject.toml": PYPROJECT,
        "openapi.yaml": OPENAPI,
        ".pre-commit-config.yaml": PRECOMMIT.format(repo=repo, rev=rev),
        "src/toy/__init__.py": "",
        "src/toy/billing/__init__.py": "from toy.billing._ledger import post\n\n__all__ = ['post']\n",
        "src/toy/billing/_ledger.py": "def post(x: int) -> int:\n    return x\n",
        "src/toy/orders/__init__.py": "",
        "src/toy/orders/api.py": "def create() -> None:\n    return None\n",
        "src/toy/legacy.py": LEGACY,
        "tests/test_toy.py": "from toy.billing import post\n\n\ndef test_post():\n    assert post(1) == 1\n",
        "justfile": "test:\n    uv run --frozen pytest -q\n",
        ".gitignore": ".brick-harness/\n.venv/\n",
    }.items():
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text(text)
    git(d, "init", "-q", "-b", "main")
    report = presets(d)
    sh(d, "uv", "add", "-q", "--dev", suite_pin("pytest"))
    git(d, "add", "-A")
    git(d, "commit", "-qm", "presets")
    return d, report


def test_presets_go_into_the_projects_standard_files_only(toy):
    d, report = toy
    py = tomllib.loads((d / "pyproject.toml").read_text())
    lint = py["tool"]["ruff"]["lint"]
    assert {"DTZ", "S105", "S106", "S107", "S108", "PLR2004", "TID251"} <= set(lint["extend-select"])
    msgs = [v["msg"] for v in lint["flake8-tidy-imports"]["banned-api"].values()]
    assert msgs and all(" -> " in m and len(m) <= 300 for m in msgs)  # P5: each rejection teaches
    contracts = py["tool"]["importlinter"]["contracts"]
    assert {c["id"] for c in contracts} == {"owner-billing", "owner-sales"}  # folder; OpenAPI tag
    assert all(len(c["broken_contract_guidance"]) <= 300 for c in contracts)
    hooks = (d / ".pre-commit-config.yaml").read_text()
    assert hooks.startswith("# the project's own hooks") and "id: check-toml" in hooks  # kept
    assert all(f"id: {h}" in hooks for h in ("ruff", "import-linter", "uv-lock"))
    assert not (d / ".brick-harness").exists()  # QBC-63: no plugin file
    assert report["owners"]["sales"] == {"units": ["toy.orders"], "source": "OpenAPI tag"}
    assert report["ask"] == ["billing"]  # an owner only guessed from its folder: ask once
    presets(d)
    assert git(d, "status", "--porcelain").stdout == ""  # a second run changes nothing


def test_the_ask_once_answer_lands_in_codeowners(toy, tmp_path):
    d, _ = toy
    c = tmp_path / "c"
    git(d, "clone", "-q", str(d), str(c))
    report = presets(c, ("src/toy/billing/", "@finance"))
    assert "src/toy/billing/ @finance" in (c / ".github" / "CODEOWNERS").read_text()
    assert report["owners"]["@finance"]["source"] == "CODEOWNERS"
    assert report["ask"] == []


def test_an_existing_importlinter_file_gets_the_contracts(tmp_path):
    d = tmp_path / "p"
    for f, text in {
        "pyproject.toml": PYPROJECT,
        ".importlinter": "[importlinter]\nroot_packages =\n    toy\n",
        "src/toy/__init__.py": "",
        "src/toy/billing/__init__.py": "",
        "src/toy/billing/_ledger.py": "X = 1\n",
        "src/toy/orders/__init__.py": "",
        "src/toy/orders/pay.py": "from toy.billing._ledger import X\n",
    }.items():
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text(text)
    git(d, "init", "-q", "-b", "main")
    report = presets(d)
    assert "importlinter" not in tomllib.loads((d / "pyproject.toml").read_text()).get("tool", {})
    assert "[importlinter:contract:owner-billing]" in (d / ".importlinter").read_text()
    assert report["importlinter"]["baseline"] == {"owner-billing": ["toy.orders.pay -> toy.billing._ledger"]}
    assert sh(d, "uv", "run", "--frozen", "lint-imports", check=False).returncode == 0


def test_the_baseline_only_shrinks(toy, tmp_path):
    d, report = toy
    assert report["ruff"]["baseline"] == {"src/toy/legacy.py": ["DTZ005"]}
    c = tmp_path / "c"
    git(d, "clone", "-q", str(d), str(c))
    (c / "src/toy/legacy.py").write_text("STAMP = None\n")
    assert presets(c)["ruff"]["baseline"] == {}  # fixed: the entry goes
    (c / "src/toy/legacy.py").write_text(LEGACY)
    assert presets(c)["ruff"]["baseline"] == {}  # never comes back: a rerun adds nothing
    pfi = tomllib.loads((c / "pyproject.toml").read_text())["tool"]["ruff"]["lint"]["extend-per-file-ignores"]
    assert pfi == {"tests/**": ["S101"]}  # the project's own entry stays


def test_a_clean_base_is_clean_for_both(toy):
    d, _ = toy
    assert human(d).returncode == 0  # today's findings break nobody's build
    res = measure(d, "main")
    assert res["items"][0]["status"] == "met", res
    assert no_clones(d)


def plant(d: Path, name: str, files: dict) -> subprocess.CompletedProcess[str]:
    """Commit ``files`` on a branch off main: first as a human would (the hook refuses it), then
    past the hook, so the measurer sees the same tree. Returns the refused commit."""
    git(d, "checkout", "-q", "-B", "plant-" + "-".join(name.split()), "main")
    for f, text in files.items():
        (d / f).write_text(text(d) if callable(text) else text)
    git(d, "add", "-A")
    refused = git(d, "commit", "-qm", name, check=False)
    if refused.returncode != 0:
        git(d, "commit", "-qm", f"plant {name}", "--no-verify")
    return refused


@pytest.mark.parametrize("cls", PLANTS)
def test_a_planted_defect_is_the_same_fact_for_a_human_and_the_measurer(toy, cls):
    d, _ = toy
    files, hook, names = PLANTS[cls]
    try:
        h = plant(d, cls, files)
        res = measure(d)
    finally:
        git(d, "checkout", "-q", "main")
    assert h.returncode != 0 and names in h.stdout + h.stderr  # the human's commit is refused
    item = res["items"][0]
    assert item["status"] == "unmet"
    assert no_clones(d)  # the result is the record
    sarif = d / item["out"] / "findings.sarif"
    said = " ".join(x["message"] for x in res["facts"]) + (sarif.read_text() if sarif.is_file() else "")
    assert names in said
    if hook == "uv-lock":  # the locked install says it, open, before the seal (no network inside)
        details = [x["detail"] for x in res["facts"]]
        assert details[0] == "env_setup" and not [x for x in details if x.startswith("lint:")]
    else:
        assert [x["detail"] for x in res["facts"]] == [f"lint:{hook}"]


def test_a_grown_baseline_or_dropped_hook_has_no_effect(toy):
    d, _ = toy
    hooks = (d / ".pre-commit-config.yaml").read_text().replace("id: ruff\n", "id: ruff-off\n")
    try:
        plant(d, "gamed", {"src/toy/orders/when.py": WHEN, "pyproject.toml": gamed, ".pre-commit-config.yaml": hooks})
        res = measure(d)
    finally:
        git(d, "checkout", "-q", "main")
    facts = res["facts"]
    assert any(x["detail"] == "lint:ruff" for x in facts)
    assert "DTZ005" in (d / res["items"][0]["out"] / "findings.sarif").read_text()
    assert any(x["kind"] == "diff" and "pyproject.toml" in x["detail"] for x in facts)
    assert any(x["kind"] == "diff" and ".pre-commit-config.yaml" in x["detail"] for x in facts)
    assert res["items"][0]["status"] == "unmet"


def test_a_project_that_is_not_installed_gets_its_import_roots_from_what_it_declares(tmp_path, monkeypatch):
    """uv `package = false` + pytest `pythonpath = ["src"]` (QBC-61, import-linter: root packages must
    be importable): the hook and the baseline run get PYTHONPATH from the project's declarations, and
    the plugin's own VIRTUAL_ENV is not passed on. A clean commit passes; a cross-owner import is refused."""
    monkeypatch.setenv("VIRTUAL_ENV", "/nonexistent/plugin-venv")
    files = {
        "pyproject.toml": '[project]\nname = "loose"\nversion = "0.1.0"\nrequires-python = "==3.14.*"\ndependencies = []\n'
        '\n[tool.uv]\npackage = false\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n',
        "src/catalog/__init__.py": "",
        "src/catalog/prices/__init__.py": "",
        "src/catalog/prices/_ledger.py": "PRICE = 1\n",
        "src/loans/__init__.py": "",
        "src/loans/rates/__init__.py": "",
        ".gitignore": ".venv/\n",
    }
    for f, text in files.items():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(text)
    git(tmp_path, "init", "-q", "-b", "main")
    report = presets(tmp_path)
    assert {"owner-prices", "owner-rates"} <= set(report["importlinter"]["contracts"])
    hook = next(h for h in (tmp_path / ".pre-commit-config.yaml").read_text().split("- id: ") if h.startswith("import-linter"))
    assert "env -u VIRTUAL_ENV PYTHONPATH=src uv run" in hook
    git(tmp_path, "add", "-A")
    assert git(tmp_path, "commit", "-qm", "clean", check=False).returncode == 0  # the installed hook, no hand setup
    (tmp_path / "src/loans/rates/pay.py").write_text("from catalog.prices._ledger import PRICE\n\nP = PRICE\n")
    git(tmp_path, "add", "-A")
    refused = git(tmp_path, "commit", "-qm", "cross", check=False)
    assert refused.returncode != 0 and "without a leading _" in refused.stdout + refused.stderr
