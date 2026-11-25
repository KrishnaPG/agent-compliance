"""Helpers shared by the keywords: subprocess runs, git, fixtures, field paths, digests."""

from __future__ import annotations

import fnmatch
import glob as _glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / "contract.json").read_text())


def catalog_entry(kind: str, key: str) -> dict:
    """One catalog entry; the named results of same_result and the metrics of threshold are defined there."""
    import yaml
    return yaml.safe_load((HERE.parents[2] / "docs/atdd/catalog.yaml").read_text())[kind][key]
sys.path.insert(0, str(HERE.parent.parent / "lib"))
from atdd_engine.runtime import FixtureError, Missing, say  # noqa: E402

REF = "harness/acceptance/fixtures/README.md"
FIXED_DATE = "2026-01-01T00:00:00+00:00"


def need(ok, wrong: str, right: str):
    """Assert (red): the system under test must hold `ok`."""
    if not ok:
        raise AssertionError(say("ATDD-RED", wrong, right, REF))


def missing(wrong: str, right: str):
    raise Missing(say("ATDD-MISSING", wrong, right, REF))


# ---------- fixtures ----------

def fixture_path(ctx, *parts: str) -> Path:
    p = ctx.fixtures.joinpath(*parts)
    if not p.exists():
        raise FixtureError(say("ATDD-FIXTURE", f"fixture {'/'.join(parts)} does not exist", "author it as described in the fixtures README", REF))
    return p


def fixture_data(ctx, *parts: str):
    p = fixture_path(ctx, *parts)
    try:
        return yaml.safe_load(p.read_text())  # JSON is YAML
    except Exception as e:  # malformed fixture
        raise FixtureError(say("ATDD-FIXTURE", f"fixture {'/'.join(parts)} is malformed: {e}", "fix the file as the fixtures README describes", REF)) from e


def api_log(ctx) -> list:
    """Every request the replay proxy saw, in order: {service, operation, method, path, body}; operation is `unmatched` when no recording answered."""
    p = ctx.work / "api.log.jsonl"
    out = {}
    for line in p.read_text().splitlines() if p.exists() else []:
        e = json.loads(line)
        out.setdefault(e["id"], {}).update(e)
    return list(out.values())


# ---------- processes ----------

def base_env(ctx) -> dict:
    return ctx.state["env"]


def init_env(ctx):
    work = ctx.work
    for d in ("bin", "home", "outside", "orchestrator"):
        (work / d).mkdir(exist_ok=True)
    stub = work / "bin" / "claude"
    stub.write_text("#!/usr/bin/env python3\nimport runpy,sys\nsys.argv[0]=sys.argv[0]\nrunpy.run_path(%r, run_name='__main__')\n" % str(HERE / "stub_claude.py"))
    stub.chmod(0o755)
    env = {
        "PATH": f"{work / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(work / "home"),
        "LC_ALL": "C.UTF-8",
        # the row's HOME is empty, so the host's pinned toolchain (uv's interpreters and cache, mise's tools) is named where it lives
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache"),
        "XDG_DATA_HOME": os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "",
        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_DATE": FIXED_DATE,
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
        "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "no_proxy": "127.0.0.1,localhost",
        CONTRACT["env"]["model_log"]: str(work / "model.log.jsonl"),
        CONTRACT["env"]["prompt_log"]: str(work / "prompts.log.jsonl"),
        CONTRACT["env"]["answers_file"]: str(work / "answers.json"),
        "ATDD_MODEL_STATE": str(work / "model.state"),
        "ATDD_TREE": str(ctx.tree),
        "MISE_GLOBAL_CONFIG_FILE": str(ctx.tree / ".tool-versions"),  # the plugin's one toolchain manifest pins the host tools (just) a run finds through mise shims
        "ATDD_OUTSIDE": str(work / "outside"),
        "BH_ORCHESTRATOR_DIR": str(work / "orchestrator"),  # where the program finds the authoritative packets
    }
    ctx.state["env"] = env
    ctx.state.setdefault("hidden_bins", [])


def git(ctx, *args, cwd=None, check=True, input=None) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=cwd or ctx.state["repo"], env={**base_env(ctx)}, capture_output=True, text=True, input=input)
    if check and p.returncode:
        raise FixtureError(say("ATDD-GIT", f"git {args[0]} failed: {p.stderr.strip()[:120]}", "fix the repo fixture", REF))
    return p


@dataclass
class Run:
    argv: list
    exit_code: int
    stdout: str
    stderr: str
    wall_s: float
    kind: str = ""
    extra: dict = field(default_factory=dict)
    first: "Run | None" = None
    runs: list = field(default_factory=list)  # parallel runs, this one included

    @property
    def json(self):
        t = self.stdout.strip()
        for cand in (t, t.splitlines()[-1] if t else ""):
            try:
                return json.loads(cand)
            except ValueError:
                continue
        return None

    @property
    def primary(self) -> str:
        return self.extra.get("primary", self.stdout)


def execute(ctx, argv, *, cwd=None, stdin="", timeout=120, env_extra=None) -> Run:
    env = {**base_env(ctx), **(env_extra or {})}
    t = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=cwd or ctx.state["repo"], env=env, input=stdin, capture_output=True, text=True, timeout=timeout)
        return Run(list(argv), p.returncode, p.stdout, p.stderr, time.monotonic() - t)
    except subprocess.TimeoutExpired as e:
        return Run(list(argv), 124, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), f"timed out after {timeout}s", time.monotonic() - t)
    except FileNotFoundError as e:
        return Run(list(argv), 127, "", f"not found: {e.filename}", time.monotonic() - t)


def parallel(fn, n: int) -> list:
    out = [None] * n
    barrier = threading.Barrier(n)

    def work(i):
        barrier.wait()
        out[i] = fn(i)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def sut_argv(ctx, parts) -> list:
    exe = ctx.tree / parts[0]
    if not exe.exists():
        missing(f"{parts[0]} is not in the tree under test", f"build {parts[0]} in the plugin tree")
    return [str(exe), *parts[1:]]


# ---------- repo ----------

def repo(ctx) -> Path:
    r = ctx.state.get("repo")
    if r is None:
        raise FixtureError(say("ATDD-ORDER", "a step needs the repo and no repo given came first", "put the repo given first in the row", REF))
    return r


def writable_repo(ctx) -> Path:
    """The plugin tree is read-only for the suite: a write to it goes to a copy."""
    if ctx.state.get("repo_is_tree"):
        import shutil

        dest = ctx.work / "plugin-copy"
        shutil.copytree(ctx.tree, dest, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        ctx.state["repo"], ctx.state["repo_is_tree"] = dest, False
        git(ctx, "init", "-q", "-b", CONTRACT["refs"]["main_branch"], cwd=dest)
        git(ctx, "add", "-A", cwd=dest)
        git(ctx, "commit", "-q", "-m", "plugin tree", cwd=dest)
        git(ctx, "tag", CONTRACT["refs"]["base_tag"], cwd=dest)
    return ctx.state["repo"]


def overlay(src: Path, dest: Path):
    """Copy the files of src over dest; `.atdd-delete` lists relative paths (one per line) to remove."""
    import shutil

    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if rel.name in (".atdd-delete", ".atdd-message") or p.is_dir():
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest / rel)  # not copy2: an old mtime and an equal size make git see no change
    d = src / ".atdd-delete"
    if d.exists():
        for line in d.read_text().split():
            t = dest / line
            if t.is_file():
                t.unlink()
            elif t.is_dir():
                shutil.rmtree(t)


# ---------- field paths ----------

_SEG = re.compile(r"([^.\[\]]+)|\[(\*|\d+|id=[^\]]+)\]")


def path_segments(path: str):
    out = []
    for m in _SEG.finditer(path):
        if m.group(1) is not None:
            out.append(m.group(1))
        elif m.group(2) == "*":
            out.append(None)
        elif m.group(2).startswith("id="):
            out.append(("id", m.group(2)[3:]))
        else:
            out.append(int(m.group(2)))
    return out


_NONE = object()


def get_path(obj, path: str) -> list:
    """The values at path; a [*] segment expands. Raises KeyError when a segment is absent."""
    cur = [obj]
    for seg in path_segments(path):
        nxt = []
        for c in cur:
            if seg is None:
                if not isinstance(c, list):
                    raise KeyError(path)
                nxt.extend(c)
            elif isinstance(seg, tuple):
                hit = [x for x in c if isinstance(x, dict) and x.get("id") == seg[1]] if isinstance(c, list) else []
                if not hit:
                    raise KeyError(path)
                nxt.append(hit[0])
            elif isinstance(seg, int):
                if not isinstance(c, list) or seg >= len(c):
                    raise KeyError(path)
                nxt.append(c[seg])
            else:
                if not isinstance(c, dict) or seg not in c:
                    raise KeyError(path)
                nxt.append(c[seg])
        cur = nxt
    return cur


def nonempty(v) -> bool:
    return v not in (None, "", [], {})


def apply_op(op: str, values: list, expected, wildcard: bool = False) -> str | None:
    """None when op holds for every value (distinct, and contains on a [*] path: for the one collected list), else a plain reason."""
    if op == "contains" and wildcard:
        values = [values]
    if op == "distinct":
        flat = [json.dumps(v, sort_keys=True) for v in values]
        return None if len(flat) == len(set(flat)) else "the values have a duplicate"
    for v in values:
        if op == "eq":
            ok = v == expected
        elif op == "ne":
            ok = v != expected
        elif op == "contains":
            ok = (expected in v) if isinstance(v, (list, str, dict)) else False
            if isinstance(v, str) and isinstance(expected, str):
                ok = expected in v
        elif op == "not_contains":
            ok = (expected not in v) if isinstance(v, (list, str, dict)) else True
        elif op == "present":
            ok = nonempty(v)
        elif op == "absent":
            ok = not nonempty(v)
        elif op in ("gt", "ge", "lt", "le"):
            try:
                ok = {"gt": v > expected, "ge": v >= expected, "lt": v < expected, "le": v <= expected}[op]
            except TypeError:
                ok = False
        elif op == "matches":
            ok = isinstance(v, str) and re.search(expected, v) is not None
        else:
            raise FixtureError(f"unknown op {op}")
        if not ok:
            return f"value {json.dumps(v)[:80]} is not {op} {json.dumps(expected)[:80]}"
    return None


# ---------- digests ----------

def digest_files(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(set(map(str, paths))):
        pp = Path(p)
        if pp.is_file():
            h.update(p.encode() + b"\0" + hashlib.sha256(pp.read_bytes()).digest())
    return h.hexdigest()


def tree_files(root: Path, skip=(".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")) -> list:
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in skip)
        out += [os.path.join(dp, f) for f in sorted(fn)]
    return out


def globs(root: Path, patterns) -> list:
    out = []
    for pat in patterns:
        out += [Path(p) for p in _glob.glob(str(root / pat), recursive=True)]
    return sorted(set(out))


def match_any(rel: str, patterns) -> bool:
    return any(fnmatch.fnmatch(rel, p) or rel.startswith(p.rstrip("*")) for p in patterns)
