"""Core of the brick harness: config loading, state derivation, gap checks and the deterministic measurer.

Python 3.12 standard library only, so the plugin's ``bin/`` tools run on any machine
without installing anything.

OSS checked before writing this module:
- jsonschema 4.26.0: full JSON Schema validator; not stdlib, so ``bin/`` cannot depend on
  it. The small subset validator below covers the keywords the harness schemas use; the
  tests cross-check the schemas with jsonschema itself.
- pytest 9.0.2 ``--junitxml`` / JUnit XML: adopted as the test-result format (parsed here
  with ``xml.etree``), not reimplemented.
- pytest-benchmark 5.3.1, hyperfine 2.0.0, asv 0.6.6 (latest releases, looked up 2026-11-19): produce bench numbers but do not
  compare them with project targets or keep a scoreboard; the measurer reads their JSON or
  CSV output through a configured extractor instead of replacing them.
- Markdown link and anchor checks (looked up 2026-11-19): lychee 0.24.2 (Rust binary),
  markdown-link-check 3.15.0 and remark-validate-links 13.1.0 (Node): all check links, none
  is stdlib Python or emits gaps with file:line evidence and a tag; the few lines below do.
- Gap merging: no tool found that recomputes mechanical checks and rejects reviewer findings
  whose file:line does not resolve; rule compliance itself is left to the configured
  catalog's own review skill, not re-implemented here.
- Catalogue merges: git's built-in ``union`` merge driver is line-based and can emit
  invalid JSON; the union here works on parsed documents and is schema-checked.
- Lockfiles (looked up 2026-11-19): @yarnpkg/lockfile 1.1.0 and @pnpm/lockfile-file 9.1.3 (Node), PyYAML 6.0.3 (not
  stdlib), bundler's own parser (Ruby): none runs from stdlib Python, so the few
  line-level readers below take only name and version and report a malformed file.
- Findings, ranking, history, sizing (looked up 2026-11-19): ranking is a tuple sort key
  (stdlib); no issue tracker, SARIF 2.1.0 tool or review bot found that orders findings by
  impact on measured targets and stays a plain file the harness commits (SARIF levels are
  error/warning/note, with no target impact), so the key below is its own, documented.
  Target history is one JSON file appended per measurement; metrics stores (Prometheus
  3.x, MLflow 3.x) hold series but need a server, and the rules over them (met to unmet
  after another item's change) would still be ours. ``git diff`` gives the review input.
- Value order, decision records, work packet (SG-16 to SG-18; named from knowledge, not
  re-looked-up at pinned versions, none adopted): WSJF / cost-of-delay scoring (SAFe) and
  tracker rank fields (Beads, GitHub Projects) hold an order but not one derived from an
  owner-cited slice and value over a dependency closure; ADR tools (adr-tools, log4brains)
  write prose records, not records a gap check can match by kind and area; repo packers
  (repomix, gitingest) pack code, not cited line ranges with a digest. Used: stdlib
  ``fractions`` (exact value / cost ratios), ``hashlib`` (passage digests), ``git show``.
- State checksums: sha256 would be the pick, but workflow scripts have no crypto API, so
  both sides use 32-bit FNV-1a over a canonical form defined below (detects a part
  shortened in transit; not a security check).
"""

from __future__ import annotations

import ast
import contextlib
import csv
import fcntl
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import signal
import statistics
import subprocess
import tempfile
import time
import tomllib
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parent.parent  # harness/ inside the plugin
PLUGIN_ROOT = HARNESS_DIR.parent  # the plugin: bin/, skills/, catalog/, checks/
SCHEMA_DIR = HARNESS_DIR / "schema"

# Helper jobs every catalogue names a library for, per ecosystem, unless the config's
# `catalogue_jobs` replaces the list. Kept tiny: which jobs matter is the project's call.
DEFAULT_JOBS = ["testing"]

OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}

TEMPLATE_VARS = ("item", "brick_path", "out", "slot", "port_base", "workdir", "root", "ref")

HDIR = ".brick-harness"
# Harness-owned files: default under .brick-harness/, created by the harness, committed.
DEFAULT_PATHS = {
    "targets": f"{HDIR}/targets.json",
    "bricks": f"{HDIR}/bricks.json",
    "contracts_dir": f"{HDIR}/contracts",
    "catalogue": f"{HDIR}/catalogue.json",
    "scoreboard": f"{HDIR}/scoreboard.json",
    "scoreboard_md": f"{HDIR}/scoreboard.md",
    "gaps": f"{HDIR}/gaps.json",
    "gaps_md": f"{HDIR}/gaps.md",
    "feature_slices": f"{HDIR}/features.json",
    "answers": f"{HDIR}/decisions",
    "measure_out": f"{HDIR}/out",
}
HARNESS_KEYS = tuple(k for k in DEFAULT_PATHS if k != "measure_out")
# The project's own documents: read only; the harness reports gaps in them, never writes them.
PROJECT_KEYS = (
    "features",
    "acceptance",
    "standards",
    "decisions_dir",
    "stack_manifest",
    "build_order",
    "status",
    "lockfiles",
)


class HarnessError(Exception):
    pass


# Output limits (config ``limits``): they bound what is printed or filed per call, never
# what is measured.
LIMIT_DEFAULTS = {"decision_items": 25, "packet_rules": 8, "file_per_run": 10, "tracker_read": 200}


# ---------------------------------------------------------------- schema validation


def validate(
    instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, at: str = "$"
) -> list[str]:
    """Validate with the JSON Schema subset the harness schemas use; return error strings."""
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise HarnessError(f"unsupported $ref {ref}")
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate(instance, target, root, at)
    errs: list[str] = []
    types = schema.get("type")
    if types is not None:
        tlist = types if isinstance(types, list) else [types]
        if not any(_is_type(instance, t) for t in tlist):
            return [f"{at}: expected {types}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{at}: {instance!r} not in {schema['enum']}")
    if (
        isinstance(instance, str)
        and "pattern" in schema
        and not re.search(schema["pattern"], instance)
    ):
        errs.append(f"{at}: {instance!r} does not match {schema['pattern']}")
    if _is_type(instance, "number"):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{at}: {instance} < {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{at}: {instance} > {schema['maximum']}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errs.append(f"{at}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, v in enumerate(instance):
                errs += validate(v, schema["items"], root, f"{at}[{i}]")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errs.append(f"{at}: missing {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        names = schema.get("propertyNames")
        for key, val in instance.items():
            if names is not None:
                errs += validate(key, names, root, f"{at}.{key}(name)")
            if key in props:
                errs += validate(val, props[key], root, f"{at}.{key}")
            elif extra is False:
                errs.append(f"{at}: unexpected key {key!r}")
            elif isinstance(extra, dict):
                errs += validate(val, extra, root, f"{at}.{key}")
    return errs


def _is_type(v: Any, t: str) -> bool:
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if t == "null":
        return v is None
    raise HarnessError(f"unsupported type {t}")


def load_schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return schema


def _no_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not allowed")


def loads(text: str) -> Any:
    """json.loads that rejects NaN and Infinity (they would compare false with every target)."""
    return json.loads(text, parse_constant=_no_constant)


def load_json(path: Path, schema: str | None = None) -> Any:
    try:
        data = loads(path.read_text())
    except (OSError, ValueError) as e:
        raise HarnessError(f"{path}: {e}") from e
    if schema:
        errs = validate(data, load_schema(schema))
        if errs:
            raise HarnessError(f"{path} fails {schema} schema: " + "; ".join(errs[:10]))
    return data


# ---------------------------------------------------------------- config


class Config:
    """A validated project config.

    Paths and commands resolve from the project root: ``root`` in the config (relative to
    the config file), else the parent of a ``.brick-harness/`` directory holding the config,
    else the config file's directory.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.config_dir = self.path.parent
        self.data: dict[str, Any] = load_json(self.path, "harness.config")
        if "root" in self.data:
            self.dir = (self.config_dir / self.data["root"]).resolve()
        elif self.config_dir.name == HDIR:
            self.dir = self.config_dir.parent
        else:
            self.dir = self.config_dir
        self.root = self.dir
        self.paths: dict[str, Any] = {**DEFAULT_PATHS, **self.data.get("paths", {})}
        self.commands: dict[str, Any] = self.data["commands"]
        self.sections: dict[str, str] = self.data.get("sections", {})
        self.protected: list[str] = self.data.get("protected", [])
        self.na: dict[str, str] = self.data.get("na", {})
        if self.data.get("tracker"):
            ts = load_schema("tracker")
            errs = validate(self.data["tracker"], ts["$defs"]["config"], ts, "$.tracker")
            if errs:
                raise HarnessError(f"{self.path} fails tracker schema: " + "; ".join(errs[:10]))

    def limit(self, key: str) -> int:
        """A config limit (``limits``) or its default."""
        return int(self.data.get("limits", {}).get(key, LIMIT_DEFAULTS[key]))

    def commands_for(self, brick: dict[str, Any]) -> dict[str, Any]:
        """The commands that score ``brick``: the config's, with the item's own overrides."""
        own = brick.get("commands", {})
        return {
            k: v
            for k, v in {**self.commands, **own}.items()
            if k in ("test", "bench", "env_setup", "timeout_s")
        }

    def file(self, key: str, base: Path | None = None) -> Path | None:
        rel = self.paths.get(key)
        if rel is None or isinstance(rel, list):
            return None
        return ((base or self.dir) / str(rel)).resolve()

    def files(self, key: str) -> list[Path]:
        rel = self.paths.get(key)
        if rel is None:
            return []
        return [(self.dir / r).resolve() for r in (rel if isinstance(rel, list) else [rel])]

    def slot(self, n: int) -> dict[str, Any]:
        s = self.data.get("slots", {})
        return {"slot": n, "port_base": s.get("port_base", 20000) + n * s.get("port_stride", 100)}


# ---------------------------------------------------------------- results parsing


def _count(s: ET.Element, attr: str, path: Path) -> int:
    raw = s.get(attr, "0") or "0"
    try:
        v = float(raw)
    except ValueError as e:
        raise HarnessError(f"junit {path}: {attr}={raw!r} is not a number") from e
    if not math.isfinite(v) or v < 0 or v != int(v):
        raise HarnessError(f"junit {path}: {attr}={raw!r} is not a count")
    return int(v)


def parse_junit(path: Path) -> dict[str, int]:
    """Sum JUnit XML counts over the innermost <testsuite> elements; HarnessError when unreadable.

    Only leaf suites are summed: a <testsuite> nested in another repeats its children's counts.
    """
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        raise HarnessError(f"junit {path}: {e}") from e
    suites = [s for s in root.iter("testsuite") if s.find(".//testsuite") is None]
    if root.tag not in ("testsuite", "testsuites"):
        raise HarnessError(f"junit {path}: root element <{root.tag}> is not a test report")
    c = {"total": 0, "failed": 0, "errors": 0, "skipped": 0}
    for s in suites:
        c["total"] += _count(s, "tests", path)
        c["failed"] += _count(s, "failures", path)
        c["errors"] += _count(s, "errors", path)
        c["skipped"] += _count(s, "skipped", path)
    c["passed"] = c["total"] - c["failed"] - c["errors"] - c["skipped"]
    if c["passed"] < 0:
        raise HarnessError(f"junit {path}: more failed/errors/skipped than tests")
    return c


def extract(results: Path, fmt: str, spec: str) -> float:
    """Pull one number from a bench result file.

    json: dotted path (``a.b.0.c``). csv: ``column`` or ``column:agg`` with agg in
    first, last, min, max, mean, median (default first).
    """
    try:
        if fmt == "json":
            cur: Any = loads(results.read_text())
            for part in spec.split("."):
                cur = cur[int(part)] if isinstance(cur, list) else cur[part]
            value = cur
        else:
            col, _, agg = spec.partition(":")
            with results.open(newline="") as f:
                vals = [float(r[col]) for r in csv.DictReader(f)]
            if not vals:
                raise HarnessError(f"{results}: no rows")
            agg = agg or "first"
            aggs: dict[str, Callable[[list[float]], float]] = {
                "first": lambda v: v[0],
                "last": lambda v: v[-1],
                "min": lambda v: min(v),
                "max": lambda v: max(v),
                "mean": statistics.fmean,
                "median": statistics.median,
            }
            value = aggs[agg](vals)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        raise HarnessError(f"bench metric {spec!r} from {results}: {e!r}") from e
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HarnessError(f"bench metric {spec!r} is not a number: {value!r}")
    if not math.isfinite(value):
        raise HarnessError(f"bench metric {spec!r} is not finite: {value!r}")
    return float(value)


# ---------------------------------------------------------------- measuring


def _render(template: str, ctx: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        return str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0)

    return re.sub(r"\{(" + "|".join(TEMPLATE_VARS) + r")\}", sub, template)


def _run(cmd: str, cwd: Path, env: dict[str, str], timeout: float) -> dict[str, Any]:
    """Run in its own process group so a timeout kills the command's children too."""
    t0 = time.monotonic()
    p = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    exit_code: int | None
    try:
        output, _ = p.communicate(timeout=timeout)
        exit_code, tail = p.returncode, output[-2000:]
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        exit_code, tail = None, f"timeout after {timeout}s"
    return {"cmd": cmd, "exit": exit_code, "seconds": round(time.monotonic() - t0, 3), "tail": tail}


def targets_for(targets: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    return [t for t in targets if t["item"] == item]


def digest(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def target_digest(cfg: Config, brick: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    """What a result was scored against: the item's targets and the commands that measure it."""
    import bhrules

    return digest(
        {
            "targets": bhrules.item_targets(cfg, targets, brick["id"]),
            "commands": cfg.commands_for(brick),
        }
    )


def measure_item(
    cfg: Config,
    brick: dict[str, Any],
    targets: list[dict[str, Any]],
    workdir: Path,
    root: Path,
    out: Path,
    slot: int,
    ref: str,
    facts: dict[str, Any] | None = None,
    changed: list[str] | None = None,
) -> dict[str, Any]:
    """Run one item's commands in ``workdir`` and compare raw numbers with its targets.

    Fails closed: no targets, a command marked ``pending``, a non-zero exit, a timeout, zero
    tests, an unreadable result or a missing metric each make the item ``unmet`` with the
    reason in ``errors``. A command may run anywhere (e.g. a script that runs the tests on
    another host); it only has to leave its results at the configured path under ``{out}``.
    ``facts`` (ignored edits, scope, dependencies, ...) are copied into the result and never
    change its status. A bench target's ``runs`` repeats the bench; the median is the value
    and the spread is recorded (``noise``). When the rule catalog ships checks they run over the
    item's owned paths and the files in ``changed`` and ``rules.violations == 0`` is one more
    target (SG-19; ``bhrules``). A test command naming an ``environment`` runs
    through that environment's ``run`` template (``{cmd}`` is the quoted command).
    """
    import bhrules

    item = brick["id"]
    mine = targets_for(targets, item)
    out.mkdir(parents=True, exist_ok=True)
    ctx = {
        "item": item,
        "brick_path": brick.get("path", ""),
        "out": out,
        "workdir": workdir,
        "root": root,
        "ref": ref,
        **cfg.slot(slot),
    }
    env = dict(
        os.environ,
        BH_ITEM=item,
        BH_OUT=str(out),
        BH_SLOT=str(slot),
        BH_PORT_BASE=str(ctx["port_base"]),
    )
    cmds = cfg.commands_for(brick)
    timeout = float(cmds.get("timeout_s", 600))
    metrics: dict[str, float] = {}
    errors: list[str] = []
    noise: dict[str, Any] = {}
    environment: str | None = None
    runs: list[dict[str, Any]] = []
    if not mine:
        errors.append("no targets for this item")
    rules = None
    if bhrules.active(cfg):
        rules = bhrules.run_checks(cfg, root, brick, changed or [])
        mine = mine + [{"item": item, "metric": "rules.violations", "op": "==", "value": 0}]

    def step(name: str, cmd: str) -> bool:
        r = _run(_render(cmd, ctx), root, env, timeout)
        r["name"] = name
        runs.append(r)
        if r["exit"] != 0:
            errors.append(
                f"{name}: exit {r['exit']}" if r["exit"] is not None else f"{name}: timeout"
            )
            return False
        return True

    if cmds.get("env_setup"):
        step("env_setup", cmds["env_setup"])
    test = cmds.get("test")
    if test and test.get("pending"):
        errors.append(f"test: command not yet present ({test['pending']})")
    elif test:
        junit = _result_path(test.get("junit", "{out}/junit.xml"), ctx, root)
        environment = test.get("environment")
        run_cmd, why = _in_environment(cfg, test["run"], environment, ctx)
        if why:
            errors.append(why)
        else:
            step("test", run_cmd)
        try:
            for k, v in parse_junit(junit).items():
                metrics[f"tests.{k}"] = float(v)
            if metrics["tests.total"] == 0:
                errors.append("test: zero tests collected")
        except HarnessError as e:
            errors.append(str(e))
    bench = cmds.get("bench")
    if any(t["metric"].startswith("bench.") for t in mine):
        if not bench:
            errors.append("bench targets but no bench command")
        elif bench.get("pending"):
            errors.append(f"bench: command not yet present ({bench['pending']})")
            bench = None
        if bench:
            runs_n = max([int(t.get("runs", 1)) for t in mine if t["metric"].startswith("bench.")])
            samples: dict[str, list[float]] = {}
            done = True
            for _ in range(runs_n):
                res = _result_path(bench["results"], ctx, root)
                if not step("bench", bench["run"]):
                    done = False
                    break
                for name, spec in bench["metrics"].items():
                    try:
                        v = extract(res, bench.get("format", "json"), spec)
                        samples.setdefault(f"bench.{name}", []).append(v)
                    except HarnessError as e:
                        if str(e) not in errors:
                            errors.append(str(e))
            for m, vs in samples.items():
                if done and len(vs) == runs_n:
                    metrics[m] = statistics.median(vs)
                    if runs_n > 1:
                        noise[m] = _noise(vs, [t for t in mine if t["metric"] == m])
    if rules:
        if rules["violations"] is None:
            errors.append(rules["error"])
        else:
            metrics["rules.violations"] = float(rules["violations"])
            if rules["error"]:
                errors.append(rules["error"])
    checks = []
    for t in mine:
        actual = metrics.get(t["metric"])
        met = actual is not None and OPS[t["op"]](actual, t["value"])
        if actual is None:
            errors.append(f"metric {t['metric']} not measured")
        checks.append(
            {
                "metric": t["metric"],
                "op": t["op"],
                "value": t["value"],
                "actual": actual,
                "met": met,
            }
        )
    status = "met" if not errors and all(c["met"] for c in checks) else "unmet"
    return {
        "status": status,
        "ref": ref,
        "measured_at": datetime.now(UTC).isoformat(timespec="microseconds"),
        "metrics": metrics,
        "targets": checks,
        "targets_digest": target_digest(cfg, brick, targets),
        "errors": errors,
        "runs": [
            {k: r[k] for k in ("name", "exit", "seconds")}
            | ({"tail": r["tail"]} if r["exit"] != 0 else {})
            for r in runs
        ],
        **({"noise": noise} if noise else {}),
        **({"rules": rules} if rules else {}),
        **({"environment": environment or "local"} if brick.get("kind") == "system" else {}),
        **(facts or {}),
    }


def _noise(samples: list[float], ts: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread of repeated bench runs; ``within_noise`` lists the targets whose value lies
    between the slowest and fastest run (so another run could have gone either way)."""
    lo, hi = min(samples), max(samples)
    return {
        "runs": len(samples),
        "median": statistics.median(samples),
        "min": lo,
        "max": hi,
        "within_noise": [f"{t['op']} {t['value']}" for t in ts if lo <= t["value"] <= hi],
    }


def _in_environment(
    cfg: Config, run: str, name: str | None, ctx: dict[str, Any]
) -> tuple[str, str | None]:
    """The command to run and, when its environment is not defined, why it cannot run."""
    if not name:
        return run, None
    env = cfg.data.get("environments", {}).get(name)
    if env is None:
        return run, f"test: environment {name!r} is not defined in config.environments"
    return env["run"].replace("{cmd}", shlex.quote(_render(run, ctx))), None


def _result_path(template: str, ctx: dict[str, Any], root: Path) -> Path:
    """Resolve a result file and unlink any copy left by an earlier run, so it cannot be reused."""
    p = Path(_render(template, ctx))
    p = p if p.is_absolute() else root / p
    p.unlink(missing_ok=True)
    return p


def target_keys(targets: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    return {(t["item"], t["metric"], t["op"], t["value"]) for t in targets}


def _git(top: Path, *a: str) -> str:
    p = subprocess.run(["git", "-C", str(top), *a], capture_output=True, text=True)
    if p.returncode != 0:
        raise HarnessError(f"git {' '.join(a)}: {p.stderr.strip()}")
    return p.stdout.strip()


def _git_ok(top: Path, *a: str) -> bool:
    return subprocess.run(["git", "-C", str(top), *a], capture_output=True).returncode == 0


def _under(p: Path, top: Path) -> str:
    """``p`` relative to the repository top, as git names it; HarnessError when outside."""
    if not p.is_relative_to(top):
        raise HarnessError(f"{p} is outside the repository {top}")
    return p.relative_to(top).as_posix() or "."


def _matches(path: str, patterns: list[str]) -> bool:
    """A path equals, lies under, or fnmatches one of the patterns (all repository-relative)."""
    for pat in patterns:
        pat = pat.rstrip("/")
        if pat in (".", "") or path == pat or path.startswith(pat + "/"):
            return True
        if fnmatch.fnmatchcase(path, pat):
            return True
    return False


@contextlib.contextmanager
def clean_checkout(top: Path, ref: str) -> Iterator[Path]:
    """Detached worktree of ``ref`` in a temp dir, removed afterwards by git."""
    tmp = Path(tempfile.mkdtemp(prefix="bh-measure-"))
    co = tmp / "co"
    _git(top, "worktree", "add", "--detach", str(co), ref)
    try:
        yield co
    finally:
        _git(top, "worktree", "remove", "--force", str(co))
        with contextlib.suppress(OSError):
            tmp.rmdir()


_HELD: dict[str, int] = {}


@contextlib.contextmanager
def harness_lock(cfg: Config) -> Iterator[None]:
    """One writer at a time for the scoreboard, plan commits and merges (re-entrant in-process).

    A blocking flock: the caller waits on the kernel's lock release, never in a loop.
    """
    d = cfg.file("measure_out")
    assert d is not None
    d.mkdir(parents=True, exist_ok=True)
    key = str(d)
    if _HELD.get(key):
        _HELD[key] += 1
        try:
            yield
        finally:
            _HELD[key] -= 1
        return
    with open(d / "harness.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        _HELD[key] = 1
        try:
            yield
        finally:
            _HELD[key] = 0


def git_top(d: Path) -> Path | None:
    try:
        return Path(_git(d, "rev-parse", "--show-toplevel")).resolve()
    except HarnessError:
        return None


def _keyed(cfg: Config, keys: tuple[str, ...], top: Path) -> list[str]:
    """Configured harness paths for ``keys`` (existing or not) relative to the repository top."""
    out = []
    for k in keys:
        for p in cfg.files(k):
            if p.is_relative_to(top):
                out.append(_under(p, top))
    return out


PLAN_KEYS = (
    "targets",
    "bricks",
    "contracts_dir",
    "feature_slices",
    "answers",
)  # the plan a builder must not touch
RESULT_KEYS = ("scoreboard", "scoreboard_md", "gaps", "gaps_md")


def _plan_guard(cfg: Config, top: Path) -> list[str]:
    """Paths no built ref may change: the plan, results, config and harness ignore file."""
    extra = [p for p in (cfg.path, cfg.dir / HDIR / ".gitignore") if p.is_relative_to(top)]
    return _keyed(cfg, PLAN_KEYS + RESULT_KEYS, top) + [_under(p, top) for p in extra]


def _protected(cfg: Config, top: Path) -> list[str]:
    root = _under(cfg.dir, top)
    return [p if root == "." else f"{root}/{p}" for p in cfg.protected]


def plan_head(cfg: Config, top: Path) -> str | None:
    """The last commit in HEAD that changed the plan (items, targets, contracts, config)."""
    paths = _keyed(cfg, PLAN_KEYS, top) + (
        [_under(cfg.path, top)] if cfg.path.is_relative_to(top) else []
    )
    try:
        sha = _git(top, "log", "-1", "--format=%H", "HEAD", "--", *paths)
    except HarnessError:
        return None
    return sha or None


def changed_paths(top: Path, sha: str) -> list[str]:
    """Paths ``sha`` changes relative to its merge base with HEAD (repository-relative)."""
    base = _git(top, "merge-base", "HEAD", sha)
    return _git(top, "diff", "--name-only", "--no-renames", base, sha).splitlines()


HOLDOUT_REF = "refs/brick-harness/holdout"


def guarded_paths(cfg: Config, top: Path) -> list[str]:
    """Paths the measurer takes from the plan commit, whatever a ref holds there: the plan,
    results, config and ignore file, and the protected tests, benches and runner scripts."""
    return _plan_guard(cfg, top) + _protected(cfg, top)


def _tree_files(top: Path, rev: str) -> dict[str, str]:
    """Repository-relative file name -> blob sha of ``rev``'s tree."""
    out = _git(top, "ls-tree", "-r", "-z", rev).split("\0")
    return {e.split("\t", 1)[1]: e.split()[2] for e in out if e}


def holdout_files(top: Path) -> dict[str, str]:
    """The held-out cases (ref ``refs/brick-harness/holdout``); empty when the ref is absent."""
    if not _git_ok(top, "rev-parse", "--verify", "-q", HOLDOUT_REF + "^{commit}"):
        return {}
    return _tree_files(top, HOLDOUT_REF)


def _checkout_paths(co: Path, rev: str, names: list[str]) -> None:
    if not names:
        return
    p = subprocess.run(
        ["git", "-C", str(co), "checkout", rev, "--pathspec-from-file=-", "--pathspec-file-nul"],
        input="\0".join(names) + "\0",
        capture_output=True,
        text=True,
        env=dict(os.environ, GIT_LITERAL_PATHSPECS="1"),
    )
    if p.returncode != 0:
        raise HarnessError(f"overlay of {rev[:12]} failed: {p.stderr.strip()}")


def overlay_plan(cfg: Config, top: Path, co: Path, head: str) -> None:
    """Make a ref's checkout use the plan commit's guarded paths and the held-out cases.

    Whatever the ref holds under a guarded path is replaced by HEAD's version, a guarded file
    the ref added is deleted, and the held-out ref's tree is laid over the checkout. Nothing is
    refused: the ref's edits there simply have no effect (they are listed as ignored edits).
    """
    guard = guarded_paths(cfg, top)
    want = [n for n in _tree_files(top, head) if _matches(n, guard)]
    _checkout_paths(co, head, want)
    for n in _git(co, "ls-files", "-z").split("\0"):
        if n and _matches(n, guard) and n not in want:
            (co / n).unlink(missing_ok=True)
    held = list(holdout_files(top))
    _checkout_paths(co, HOLDOUT_REF, held)


def ref_facts(cfg: Config, top: Path, sha: str) -> dict[str, Any]:
    """Facts about a ref that never change its score: the edits the overlay ignores and a
    plan commit the ref does not contain."""
    facts: dict[str, Any] = {}
    notes: list[str] = []
    try:
        changed = changed_paths(top, sha)
    except HarnessError as e:
        changed = []
        notes.append(f"ref has no merge base with HEAD, its edits are not listed: {e}")
    guard, held = guarded_paths(cfg, top), holdout_files(top)
    ignored = sorted(c for c in changed if _matches(c, guard) or c in held)
    if ignored:
        facts["ignored_edits"] = ignored[:200]
    ph = plan_head(cfg, top)
    if ph and not _git_ok(top, "merge-base", "--is-ancestor", ph, sha):
        notes.append(
            f"ref does not contain the plan commit {ph[:12]}; the plan paths come from HEAD"
        )
    if notes:
        facts["notes"] = notes
    return facts


def set_branch(cfg: Config, item: str, sha: str) -> dict[str, Any]:
    """Point ``refs/heads/bh/<item>`` at a builder's commit, from the main checkout.

    A builder in an isolated worktree cannot move the branch itself and returns its commit;
    this does it deterministically. The commit must exist, be new (not already in HEAD),
    The branch is created or fast-forwarded; anything else is refused. Never moves the branch
    backwards or sideways. What the commit holds under plan or protected paths is not
    judged here: the measurer ignores those edits and lists them.
    """
    top = git_top(cfg.dir)
    if top is None:
        raise HarnessError("not a git repository")
    bricks = load_json(cfg.file("bricks"), "bricks")["bricks"]  # type: ignore[index]
    if item not in {b["id"] for b in bricks}:  # type: ignore[union-attr]
        raise HarnessError(f"unknown item {item}")
    try:
        full = _git(top, "rev-parse", "--verify", sha + "^{commit}")
    except HarnessError:
        raise HarnessError(f"{sha} is not a commit in this repository") from None
    if _git_ok(top, "merge-base", "--is-ancestor", full, "HEAD"):
        raise HarnessError(f"{full} is already in HEAD: the builder made no new commit")
    name = f"refs/heads/bh/{item}"
    old = (
        _git(top, "rev-parse", "--verify", "-q", name)
        if _git_ok(top, "rev-parse", "--verify", "-q", name)
        else ""
    )
    if old and old != full and not _git_ok(top, "merge-base", "--is-ancestor", old, full):
        raise HarnessError(
            f"{name} is at {old}, which {full} does not contain: refusing a non-fast-forward "
            "move (a retry must start from the previous commit)"
        )
    _git(top, "update-ref", name, full, old or "0" * 40)
    return {"ok": True, "item": item, "branch": f"bh/{item}", "ref": full, "previous": old or None}


def measure(
    cfg: Config, items: list[tuple[str, str]], in_place: bool = False, slot: int = 0
) -> dict[str, Any]:
    """Measure ``(item, ref)`` pairs; record each result in the scoreboard as it lands.

    Config, items and targets are read from the invoking checkout, never from the measured
    ref. A ref is measured on its checkout with the plan commit's plan and protected paths and
    the held-out cases laid over it (``overlay_plan``); its edits there have no effect and
    are listed as ``ignored_edits``. A result at HEAD is current; any other ref is a candidate,
    which never replaces a met current result. ``in_place`` results are ``met-uncommitted``
    at best and never satisfy a target.
    """
    import bhrules

    bricks = {b["id"]: b for b in load_json(cfg.file("bricks"), "bricks")["bricks"]}  # type: ignore[arg-type]
    targets = load_json(cfg.file("targets"), "targets")["targets"]  # type: ignore[arg-type]
    if not items:
        items = [(i, "HEAD") for i in bricks]
    unknown = [i for i, _ in items if i not in bricks]
    if unknown:
        raise HarnessError(f"unknown items: {unknown}")
    _, bad = read_board(cfg.file("scoreboard"))  # type: ignore[arg-type]
    if bad:
        raise HarnessError(bad + "; restore the scoreboard from git before measuring")
    out_root = cfg.file("measure_out")
    assert out_root is not None
    results: dict[str, Any] = {}
    errors: list[str] = []

    def record(item: str, r: dict[str, Any], current: bool, tree: str | None = None) -> None:
        results[item] = r
        (out_root / item).mkdir(parents=True, exist_ok=True)
        (out_root / item / "result.json").write_text(json.dumps(r, indent=2) + "\n")
        try:
            write_scoreboard(cfg, {item: r}, current=current, trees={item: tree} if tree else None)
        except HarnessError as e:
            errors.append(f"{item}: not recorded: {e}")

    if in_place:
        for item, _ in items:
            r = measure_item(
                cfg, bricks[item], targets, cfg.dir, cfg.dir, out_root / item, slot, "working-tree"
            )
            if r["status"] == "met":
                r["status"] = "met-uncommitted"
            record(item, r, current=False)
    else:
        top = git_top(cfg.dir)
        if top is None:
            raise HarnessError("not a git repository; use --in-place")
        _git(top, "worktree", "prune")
        head = _git(top, "rev-parse", "HEAD")
        root_rel = _under(cfg.dir, top)
        by_ref: dict[str, list[str]] = {}
        for item, ref in items:
            by_ref.setdefault(_git(top, "rev-parse", "--verify", ref + "^{commit}"), []).append(
                item
            )
        for sha, its in by_ref.items():
            facts = ref_facts(cfg, top, sha) | _dependency_facts(cfg, top, sha)
            try:
                chg = [
                    c.removeprefix(root_rel + "/")
                    for c in changed_paths(top, sha)
                    if root_rel == "." or c.startswith(root_rel + "/")
                ]
            except HarnessError:
                chg = []
            sup = bhrules.suppressions(cfg, top, sha)
            if sup:
                facts["suppressions"] = sup
            with clean_checkout(top, sha) as co:
                overlay_plan(cfg, top, co, head)
                for item in its:
                    b = bricks[item]
                    r = measure_item(
                        cfg,
                        b,
                        targets,
                        co,
                        co / root_rel,
                        out_root / item,
                        slot,
                        sha,
                        facts | _scope_facts(cfg, top, co, b, sha),
                        chg,
                    )
                    key = tree_key(cfg, top, bricks, item, sha, head, r["targets_digest"])
                    record(item, r, current=sha == head, tree=key)
    run: dict[str, Any] = {
        "ok": not errors and all(r["status"] == "met" for r in results.values()),
        "scoreboard": str(cfg.file("scoreboard")),
        "items": results,
    }
    if errors:
        run["error"] = "; ".join(errors)
    return run


def _scope_facts(
    cfg: Config, top: Path, co: Path, brick: dict[str, Any], sha: str
) -> dict[str, Any]:
    """What the ref changed beyond the item's contract: paths outside the item's own paths
    (path and paths) and, in Python files under them, public top-level names the contract's
    ``exports`` list does not name. Reported, never scored."""
    try:
        changed = changed_paths(top, sha)
    except HarnessError:
        changed = []
    root = _under(cfg.dir, top)
    own = _own_paths(brick)
    pats = [p if root == "." else f"{root}/{p}" for p in own]
    skip = guarded_paths(cfg, top) + list(holdout_files(top))
    cat = cfg.file("catalogue")
    if cat is not None and cat.is_relative_to(top):
        skip.append(_under(cat, top))
    outside = sorted(c for c in changed if own and not _matches(c, pats) and not _matches(c, skip))
    out: dict[str, Any] = {"outside_paths": outside[:200]} if outside else {}
    names = _exports_missing(cfg, co, brick, pats)
    if names:
        out["unlisted_names"] = names
    return {"scope": out} if out else {}


def _public_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return {n for n in names if not n.startswith("_")}


def _exports_missing(cfg: Config, co: Path, brick: dict[str, Any], pats: list[str]) -> list[str]:
    """Public names in the item's Python files that its contract (``exports``) does not list;
    nothing when the item has no contract or the contract lists no exports."""
    contract = brick.get("contract")
    if not contract or not (cfg.dir / contract).exists():
        return []
    try:
        exports = loads((cfg.dir / contract).read_text()).get("exports")
    except (OSError, ValueError, AttributeError):
        return []
    if not isinstance(exports, list):
        return []
    found: set[str] = set()
    for pat in pats:
        base = co / pat.rstrip("/")
        files = [base] if base.is_file() else sorted(base.rglob("*.py")) if base.is_dir() else []
        for f in files:
            if f.suffix == ".py":
                found |= _public_names(f)
    return sorted(found - set(map(str, exports)))


def _lock_at(top: Path, rev: str, rel: str) -> dict[str, str]:
    try:
        text = _git(top, "show", f"{rev}:{rel}")
    except HarnessError:
        return {}
    with tempfile.TemporaryDirectory(prefix="bh-lock-") as d:
        f = Path(d) / Path(rel).name
        f.write_text(text)
        return lock_versions([f])


def _major(v: str) -> str | None:
    m = re.match(r"v?(\d+)", v)
    return m.group(1) if m else None


def _dependency_facts(cfg: Config, top: Path, sha: str) -> dict[str, Any]:
    """Packages the ref added or changed in the lockfiles since its fork from HEAD, whether the
    stack record (``standards.stack``) names each, and those whose major version differs from
    the pinned one (the base lockfile, or the stack record's own pin). Reported, never scored."""
    rels = [_under(p, top) for p in cfg.files("lockfiles") if p.is_relative_to(top)]
    if not rels:
        return {}
    try:
        base = _git(top, "merge-base", "HEAD", sha)
    except HarnessError:
        return {}
    old: dict[str, str] = {}
    new: dict[str, str] = {}
    for rel in rels:
        old |= _lock_at(top, base, rel)
        new |= _lock_at(top, sha, rel)
    added = {k: v for k, v in new.items() if k not in old}
    changed = {k: [old[k], v] for k, v in new.items() if k in old and old[k] != v}
    if not added and not changed:
        return {}
    stack_list = cfg.data.get("standards", {}).get("stack")
    pins: dict[str, str] = {}
    for e in stack_list or []:
        m = re.match(r"^([^=@\s]+)\s*(?:==|@)?\s*(.*)$", e)
        pins[norm(m.group(1))] = m.group(2).strip() if m else ""
    touched = {**added, **{k: v[1] for k, v in changed.items()}}
    out: dict[str, Any] = {"added": added, "changed": changed}
    if stack_list is not None:
        out["not_in_stack"] = sorted(k for k in touched if k not in pins)
    second = []
    for k, v in touched.items():
        pinned = pins.get(k) or old.get(k)
        if pinned and _major(pinned) and _major(v) and _major(pinned) != _major(v):
            second.append(k)
    if second:
        out["second_major"] = sorted(second)
    return {"dependencies": out}


def tree_key(
    cfg: Config,
    top: Path,
    bricks: dict[str, Any],
    item: str,
    sha: str,
    head: str,
    targets_digest: str,
) -> str | None:
    """What a result depends on, as git blob shas: the item's and its dependencies' files at
    the ref, the guarded files and held-out cases the measurer overlays, and the targets.
    Two runs with the same key ran the same thing."""
    try:
        pats = [p for p in _item_pathspec(cfg, top, bricks, item) if not p.startswith(":(")]
        excl = [
            p[len(":(exclude)") :]
            for p in _item_pathspec(cfg, top, bricks, item)
            if p.startswith(":(exclude)")
        ]
        guard = guarded_paths(cfg, top)
        theirs = _tree_files(top, sha)
        ours = _tree_files(top, head)
        mine = {
            n: b
            for n, b in theirs.items()
            if _matches(n, pats) and not _matches(n, excl) and not _matches(n, guard)
        }
        plan = {n: b for n, b in ours.items() if _matches(n, guard)}
        return digest(
            [
                sorted(mine.items()),
                sorted(plan.items()),
                sorted(holdout_files(top).items()),
                targets_digest,
            ]
        )
    except HarnessError:
        return None


def affected(cfg: Config, ref: str) -> list[str]:
    """Items a ref touches (their paths changed; items without paths count as touched), plus
    every item that depends on them, in build order."""
    top = git_top(cfg.dir)
    if top is None:
        raise HarnessError("not a git repository")
    sha = _git(top, "rev-parse", "--verify", ref + "^{commit}")
    changed = changed_paths(top, sha)
    bricks = load_json(cfg.file("bricks"), "bricks")["bricks"]  # type: ignore[arg-type]
    root = _under(cfg.dir, top)
    hit = set()
    for b in bricks:
        own = _own_paths(b)
        pats = [p if root == "." else f"{root}/{p}" for p in own]
        if not own or any(_matches(c, pats) for c in changed):
            hit.add(b["id"])
    return _with_dependents(bricks, hit)


def _own_paths(b: dict[str, Any]) -> list[str]:
    return ([b["path"]] if b.get("path") else []) + list(b.get("paths", []))


def _with_dependents(bricks: list[dict[str, Any]], seed: set[str]) -> list[str]:
    out = set(seed)
    grew = True
    while grew:  # fixed point over a finite graph, not a wait
        grew = False
        for b in bricks:
            if b["id"] not in out and out & set(b.get("depends_on", [])):
                out.add(b["id"])
                grew = True
    return [b["id"] for b in bricks if b["id"] in out]


def out_ignored(cfg: Config, top: Path) -> bool:
    out = cfg.file("measure_out")
    if out is None or not out.is_relative_to(top):
        return True
    probe = str((out / "x").relative_to(top))  # a dir-only pattern (out/) matches its contents
    cmd = ["git", "-C", str(top), "check-ignore", "-q", probe]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def ensure_out_ignored(cfg: Config, top: Path) -> None:
    """Write .brick-harness/.gitignore with out/ when the default measure_out is not ignored."""
    out = cfg.file("measure_out")
    if out_ignored(cfg, top) or out != cfg.dir / HDIR / "out":
        return
    gi = cfg.dir / HDIR / ".gitignore"
    gi.parent.mkdir(parents=True, exist_ok=True)
    old = gi.read_text() if gi.exists() else ""
    gi.write_text(old + ("" if not old or old.endswith("\n") else "\n") + "out/\n")


def _plan_paths(cfg: Config, top: Path, scoreboard: bool = True) -> list[str]:
    """Harness-owned files that exist under the repo: config, plan, scoreboard, gaps report."""
    keys = [k for k in HARNESS_KEYS if scoreboard or not k.startswith("scoreboard")]
    ps = [p for k in keys for p in cfg.files(k)] + [
        cfg.path,
        cfg.dir / HDIR / ".gitignore",
        cfg.dir / HDIR / "work",  # the files tracker adapter: one committed file per entry
    ]
    return [_under(p, top) for p in ps if p.exists() and p.is_relative_to(top)]


def _merging(top: Path) -> bool:
    return _git_ok(top, "rev-parse", "-q", "--verify", "MERGE_HEAD")


def commit_harness(cfg: Config, message: str, dry_run: bool = False) -> dict[str, Any]:
    """Commit the harness files (and only them) so worktrees forked from HEAD see the plan.

    Never stages the project's own documents. Refuses while a merge is in progress and when
    the targets file drops or changes a target HEAD has (the owner commits such a change).
    """
    top = git_top(cfg.dir)
    if top is None:
        raise HarnessError("not a git repository")
    if dry_run:
        changed = _uncommitted(cfg, top, scoreboard=True)
        return {"committed": False, "dry_run": True, "files": changed}
    with harness_lock(cfg):
        if _merging(top):
            raise HarnessError("a merge is in progress; finish or abort it first")
        moved = _moved_vs_head(cfg, top)
        if moved:
            raise HarnessError(
                f"targets dropped or changed vs HEAD (the owner commits that): {moved}"
            )
        ensure_out_ignored(cfg, top)
        paths = _not_ignored(top, _plan_paths(cfg, top))
        if paths:
            _git(top, "add", "-A", "--", *paths)
        staged = (
            _git(top, "diff", "--cached", "--name-only", "--", *paths).splitlines() if paths else []
        )
        if staged:
            _git(top, "commit", "-q", "-m", message, "--", *paths)
        files = [_rel(cfg, top / f) for f in staged]
        return {"committed": bool(staged), "files": files, "head": _git(top, "rev-parse", "HEAD")}


def _moved_vs_head(cfg: Config, top: Path) -> list[str]:
    tf = cfg.file("targets")
    if tf is None or not tf.exists() or not tf.is_relative_to(top):
        return []
    try:
        old = loads(_git(top, "show", f"HEAD:{_under(tf, top)}"))["targets"]
    except (HarnessError, ValueError, KeyError, TypeError):
        return []  # not in HEAD yet: nothing to move
    new = load_json(tf, "targets")["targets"]
    return sorted(map(str, target_keys(old) - target_keys(new)))


def _not_ignored(top: Path, paths: list[str]) -> list[str]:
    """Drop paths git ignores (git add refuses an explicitly named ignored path)."""
    cmd = ["git", "-C", str(top), "check-ignore", "--stdin"]
    p = subprocess.run(cmd, input="\n".join(paths), capture_output=True, text=True)
    ignored = set(p.stdout.splitlines())
    return [x for x in paths if x not in ignored]


# ---------------------------------------------------------------- scoreboard


def _board_digest(board: dict[str, Any]) -> str:
    d = {"items": board["items"], "candidates": board["candidates"]}
    if board.get("trees"):
        d["trees"] = board["trees"]
    return digest(d)


TREE_RUNS, TREE_KEYS = 6, 300  # limits: runs kept per tree key, tree keys kept on the board


def _note_trees(board: dict[str, Any], results: dict[str, Any], trees: dict[str, str]) -> None:
    """Record each result under its tree key; the same tree both passing and failing is flaky:
    the result then carries ``flaky`` with the runs' statuses and errors. Never changes a status."""
    hist = board.setdefault("trees", {})
    for item, key in trees.items():
        r = results.get(item)
        if r is None or r.get("status") not in ("met", "unmet"):
            continue
        runs = hist.setdefault(key, {"item": item, "runs": []})["runs"]
        runs.append(
            {
                "ref": r["ref"],
                "status": r["status"],
                "errors": [e[:300] for e in r.get("errors", [])[:3]],
                "measured_at": r["measured_at"],
            }
        )
        del runs[:-TREE_RUNS]
        if len({x["status"] for x in runs}) > 1:
            r["flaky"] = {"tree": key, "runs": list(runs)}
    for k in sorted(hist, key=lambda k: hist[k]["runs"][-1]["measured_at"])[:-TREE_KEYS]:
        del hist[k]


def write_scoreboard(
    cfg: Config,
    results: dict[str, Any],
    current: bool = True,
    trees: dict[str, str] | None = None,
) -> None:
    """Merge results into the scoreboard: ``current`` (measured at HEAD) or candidates.
    ``trees`` (item -> tree key) feeds the flaky-result fact.

    Refuses (HarnessError) when the scoreboard on disk fails its digest: an edited board is
    never overwritten, so the edit stays visible.
    """
    path = cfg.file("scoreboard")
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    with harness_lock(cfg):
        board, bad = read_board(path)
        if bad:
            raise HarnessError(bad)
        if trees:
            _note_trees(board, results, trees)
        board["items" if current else "candidates"].update(results)
        doc = {"writer": "brick-harness measure", **board, "digest": _board_digest(board)}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
        md = cfg.file("scoreboard_md")
        if md:
            md.write_text(render_md(board))
        record_history(cfg, results, current)


def read_board(path: Path) -> tuple[dict[str, Any], str | None]:
    """Return ({items, candidates}, problem). A board whose digest fails was edited by hand."""
    empty: dict[str, Any] = {"items": {}, "candidates": {}, "trees": {}}
    if not path.exists():
        return empty, None
    try:
        doc = loads(path.read_text())
    except (OSError, ValueError) as e:
        return empty, f"scoreboard unreadable: {e}"
    if not isinstance(doc, dict) or not all(
        isinstance(doc.get(k, {}), dict) for k in ("items", "candidates")
    ):
        return empty, "scoreboard is not a measurer document"
    board = {
        "items": doc.get("items", {}),
        "candidates": doc.get("candidates", {}),
        "trees": doc.get("trees", {}),
    }
    legacy = "candidates" not in doc and doc.get("digest") == digest(board["items"])
    if doc.get("digest") != _board_digest(board) and not legacy:
        return (
            empty,
            "scoreboard digest mismatch: edited outside the measurer; all items treated as unmeasured",
        )
    return board, None


def read_scoreboard(path: Path) -> tuple[dict[str, Any], str | None]:
    """Current (HEAD) results only, with the board's problem."""
    board, bad = read_board(path)
    return board["items"], bad


def _fact_lines(r: dict[str, Any]) -> list[str]:
    """One short line per fact a result carries (never part of its status)."""
    out = []
    if r.get("ignored_edits"):
        out.append(f"ignored-edits {len(r['ignored_edits'])}: {', '.join(r['ignored_edits'][:5])}")
    if r.get("flaky"):
        out.append(f"FLAKY: same tree {len(r['flaky']['runs'])} runs, passed and failed")
    for m, n in sorted(r.get("noise", {}).items()):
        if n["within_noise"]:
            out.append(f"within-noise {m} [{n['min']:.4g}..{n['max']:.4g}]")
    sc = r.get("scope", {})
    if sc.get("outside_paths"):
        out.append(f"outside-paths {len(sc['outside_paths'])}")
    if sc.get("unlisted_names"):
        out.append(f"unlisted-names {', '.join(sc['unlisted_names'][:5])}")
    d = r.get("dependencies", {})
    if d:
        out.append(
            f"deps +{len(d['added'])} ~{len(d['changed'])}"
            + (f" not-in-stack {', '.join(d['not_in_stack'])}" if d.get("not_in_stack") else "")
            + (f" second-major {', '.join(d['second_major'])}" if d.get("second_major") else "")
        )
    if r.get("suppressions"):
        out.append(
            f"suppressions {len(r['suppressions'])}: "
            + ", ".join(f"{x['file']}:{x['line']}" for x in r["suppressions"][:5])
        )
    if r.get("rules", {}).get("skipped"):
        out.append("rules-skipped " + ", ".join(x["rule"] for x in r["rules"]["skipped"][:5]))
    if r.get("environment"):
        out.append(f"env {r['environment']}")
    out += r.get("notes", [])
    return [x.replace("|", "/") for x in out]


def render_md(board: dict[str, Any]) -> str:
    rows = ["| item | result | status | ref | unmet | facts |", "|---|---|---|---|---|---|"]
    for kind in ("items", "candidates"):
        for item, r in sorted(board[kind].items()):
            bad = [
                f"{c['metric']} {c['actual']} (want {c['op']} {c['value']})"
                for c in r.get("targets", [])
                if not c["met"]
            ]
            bad += r.get("errors", [])
            label = "current" if kind == "items" else "candidate"
            rows.append(
                f"| {item} | {label} | {r['status']} | {str(r['ref'])[:10]} | {'; '.join(bad)} "
                f"| {'; '.join(_fact_lines(r))} |"
            )
    return "# Scoreboard\n\nWritten by the measurer only.\n\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------- merging (bh-merge)


def union_catalogue(ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    """JSON-level union of two catalogues by (job, ecosystem, library); used_by is unioned.

    git's built-in ``union`` merge driver is line-based and can emit invalid JSON, so the
    union is done on parsed documents and validated against the catalogue schema.
    """
    for side in (ours, theirs):
        errs = validate(side, load_schema("catalogue"))
        if errs:
            raise HarnessError("a catalogue side fails its schema: " + "; ".join(errs[:5]))
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for e in ours["entries"] + theirs["entries"]:
        k = (e["job"], e["ecosystem"], e["library"])
        if k in out:
            out[k]["used_by"] = sorted(set(out[k]["used_by"]) | set(e["used_by"]))
            if not out[k].get("why") and e.get("why"):
                out[k]["why"] = e["why"]
        else:
            out[k] = {**e, "used_by": list(e["used_by"])}
    doc = {"entries": list(out.values())}
    errs = validate(doc, load_schema("catalogue"))
    if errs:
        raise HarnessError("merged catalogue fails its schema: " + "; ".join(errs[:5]))
    return doc


def merge_unmerged(cfg: Config) -> dict[str, Any]:
    """Merge every met-unmerged candidate (from the scoreboard, never from a caller) into HEAD.

    In build order, with ``git merge --no-ff``. A conflict only in the catalogue is resolved
    by a schema-checked JSON union; any other conflict aborts that merge and records the item
    as ``conflict`` with the paths, so it is rebuilt against HEAD. Returns the items to
    re-measure at HEAD: those merged and everything that depends on them.
    """
    top = git_top(cfg.dir)
    if top is None:
        raise HarnessError("not a git repository")
    with harness_lock(cfg):
        if _merging(top):
            raise HarnessError("a merge is in progress; finish or abort it first")
        dirty = _uncommitted(cfg, top)
        if dirty:
            raise HarnessError(f"commit the plan files first (bh-commit): {dirty}")
        st = state(cfg)
        bricks = _load_plan(cfg, [])[0]
        cat = cfg.file("catalogue")
        cat_rel = _under(cat, top) if cat and cat.is_relative_to(top) else None
        merged, conflicts = [], []
        for u in st["unmerged"]:
            item, sha = u["item"], u["ref"]
            if _git_ok(top, "merge-base", "--is-ancestor", sha, "HEAD"):
                merged.append(u)  # another item's merge brought it in
                continue
            msg = f"brick-harness: merge {item} {sha[:12]}"
            before = _git(top, "rev-parse", "HEAD")
            if _git_ok(top, "merge", "--no-ff", "--no-edit", "-m", msg, sha):
                merged.append(u)
                _restore_guarded(cfg, top, before, item)
                continue
            unresolved = _git(top, "diff", "--name-only", "--diff-filter=U").splitlines()
            if cat_rel and unresolved == [cat_rel] and _union_resolve(cfg, top, cat_rel):
                _git(top, "commit", "-q", "--no-edit")
                merged.append(u)
                _restore_guarded(cfg, top, before, item)
                continue
            _git_ok(top, "merge", "--abort")
            paths = unresolved or ["(merge refused: local changes or unrelated history)"]
            conflicts.append({"item": item, "ref": sha, "paths": paths})
            _record_conflict(cfg, item, sha, paths)
        remeasure = _with_dependents(bricks, {m["item"] for m in merged})
        return {
            "merged": merged,
            "conflicts": conflicts,
            "remeasure": remeasure,
            "head": _git(top, "rev-parse", "HEAD"),
        }


def _restore_guarded(cfg: Config, top: Path, before: str, item: str) -> None:
    """After a merge, put the plan and protected paths back as they were before it, so edits a
    ref made there (which the measurer ignored) never reach HEAD. Nothing is refused."""
    guard = guarded_paths(cfg, top)
    now, was = _tree_files(top, "HEAD"), _tree_files(top, before)
    diff = [
        n
        for n in sorted(now.keys() | was.keys())
        if _matches(n, guard) and now.get(n) != was.get(n)
    ]
    if not diff:
        return
    _checkout_paths(top, before, [n for n in diff if n in was])
    for n in diff:
        if n not in was:
            _git(top, "rm", "-q", "-f", "--", n)
    _git(
        top,
        "commit",
        "-q",
        "-m",
        f"brick-harness: restore plan and protected paths after merging {item}",
    )


def _union_resolve(cfg: Config, top: Path, rel: str) -> bool:
    try:
        ours = loads(_git(top, "show", f":2:{rel}"))
        theirs = loads(_git(top, "show", f":3:{rel}"))
        doc = union_catalogue(ours, theirs)
    except (HarnessError, ValueError, KeyError, TypeError):
        return False
    (top / rel).write_text(json.dumps(doc, indent=2) + "\n")
    _git(top, "add", "--", rel)
    return True


def _record_conflict(cfg: Config, item: str, sha: str, paths: list[str]) -> None:
    board, bad = read_board(cfg.file("scoreboard"))  # type: ignore[arg-type]
    if bad:
        raise HarnessError(bad)
    prev = board["candidates"].get(item, {})
    write_scoreboard(
        cfg,
        {
            item: {
                **prev,
                "status": "conflict",
                "ref": sha,
                "measured_at": datetime.now(UTC).isoformat(timespec="microseconds"),
                "errors": [f"conflicts with HEAD at {', '.join(paths)}"],
            }
        },
        current=False,
    )


# ---------------------------------------------------------------- state


def lock_versions(paths: list[Path], problems: list[str] | None = None) -> dict[str, str]:
    """Package versions from lockfiles: uv/poetry/Cargo (TOML), package-lock.json, yarn.lock,
    pnpm-lock.yaml, go.sum, Gemfile.lock and pinned requirements. A malformed lockfile is a
    problem, never a crash."""
    out: dict[str, str] = {}
    for p in paths:
        if not p.exists():
            continue
        try:
            out.update(_lock_versions(p))
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            tomllib.TOMLDecodeError,
        ) as e:
            if problems is not None:
                problems.append(f"lockfile {p.name} unreadable: {e}")
    return out


def _lock_versions(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    text = p.read_text(errors="replace")
    if p.name == "yarn.lock":
        name = None
        for line in text.splitlines():
            if line and not line[0].isspace() and line.rstrip().endswith(":"):
                first = line.rstrip(":").split(",")[0].strip().strip('"')
                name = first.rsplit("@", 1)[0] if first.rfind("@") > 0 else first
            m = re.match(r'\s+version:?\s+"?([^"\s]+)"?', line)
            if m and name:
                out[norm(name)] = m.group(1)
                name = None
    elif p.name == "pnpm-lock.yaml":
        for line in text.splitlines():
            m = re.match(r"\s{2}'?/?(@?[^@\s'(]+)@([^(:'\s]+)", line)
            if m:
                out[norm(m.group(1))] = m.group(2)
    elif p.name == "go.sum":
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and not parts[1].endswith("/go.mod"):
                out[norm(parts[0])] = parts[1]
    elif p.name == "Gemfile.lock":
        for line in text.splitlines():
            m = re.match(r"^ {4}([A-Za-z0-9_.\-]+) \(([^)]+)\)$", line)
            if m:
                out[norm(m.group(1))] = m.group(2)
    elif p.suffix == ".lock":
        for pkg in tomllib.loads(text).get("package", []):
            out[norm(pkg["name"])] = str(pkg.get("version", ""))
    elif p.name == "package-lock.json":
        for key, pkg in loads(text).get("packages", {}).items():
            if key:
                out[norm(key.rsplit("node_modules/", 1)[-1])] = str(pkg.get("version", ""))
    elif p.suffix == ".txt":
        for line in text.splitlines():
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s;#]+)", line)
            if m:
                out[norm(m.group(1))] = m.group(2)
    return out


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_plan(
    cfg: Config, problems: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    bricks: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    catalogue: list[dict[str, Any]] = []
    for key, schema, sink, field in (
        ("bricks", "bricks", bricks, "bricks"),
        ("targets", "targets", targets, "targets"),
        ("catalogue", "catalogue", catalogue, "entries"),
    ):
        p = cfg.file(key)
        if p and p.exists():
            try:
                sink.extend(load_json(p, schema)[field])
            except HarnessError as e:
                problems.append(str(e))
    _split_parents_wait_for_children(bricks)
    return bricks, targets, catalogue


def _split_parents_wait_for_children(bricks: list[dict[str, Any]]) -> None:
    """A split parent depends on each of its children (structure, not a gate): it keeps its
    targets and is measured after them, so a child that misses part of the parent shows up as
    an unmet parent. A child the parent does not list in ``depends_on`` is added here and kept
    in ``_undeclared_children`` so the report can say so."""
    by_id = {b["id"]: b for b in bricks}
    for c in bricks:
        p = by_id.get(c.get("split_from", ""))
        if p is not None and p is not c and c["id"] not in p.get("depends_on", []):
            p["depends_on"] = [*p.get("depends_on", []), c["id"]]
            p.setdefault("_undeclared_children", []).append(c["id"])


def _rel(cfg: Config, p: Path) -> str:
    """A path as every harness output names it: relative to the project root (config root)."""
    p = p.resolve() if not p.is_absolute() else p
    return p.relative_to(cfg.dir).as_posix() if p.is_relative_to(cfg.dir) else str(p)


def record_status(
    r: dict[str, Any] | None,
    digest_ok: bool,
    resolvable: bool = True,
    in_head: bool = True,
    same_tree: bool = True,
) -> str | None:
    """Status one scoreboard record gives its item, from facts about it (pure; table-tested)."""
    if r is None:
        return None
    if not digest_ok:
        return "stale"
    if r.get("ref") == "working-tree":
        return "met-uncommitted" if r["status"] in ("met", "met-uncommitted") else "unmet"
    if not resolvable:
        return "stale"
    if r["status"] == "conflict":
        return "conflict"
    if r["status"] != "met":
        return "unmet"
    if not in_head:
        return "met-unmerged"
    if not same_tree:
        return "stale"
    return "met"


def pick_status(
    cur: tuple[dict[str, Any] | None, str | None], cand: tuple[dict[str, Any] | None, str | None]
) -> tuple[str, dict[str, Any] | None]:
    """An item's status from its current (HEAD) and candidate records.

    A met current result stands whatever the candidate says; otherwise the newer record
    decides. Returns (status, the record it came from).
    """
    (rc, sc), (rd, sd) = cur, cand
    if sc is None and sd is None:
        return "unmeasured", None
    if sc == "met" or sd is None:
        return sc, rc  # type: ignore[return-value]
    if sc is None:
        return sd, rd
    assert rc is not None and rd is not None
    if rd.get("measured_at", "") > rc.get("measured_at", ""):
        return sd, rd
    return sc, rc


READY_FROM = ("unmeasured", "unmet", "stale", "conflict", "met-uncommitted")


def _item_pathspec(cfg: Config, top: Path, by_id: dict[str, Any], item: str) -> list[str]:
    """What must be unchanged since a result for it to hold at HEAD: the item's own paths,
    its dependencies' paths and the protected paths; the whole project root (less the
    measurer's own outputs) when any of them names no path."""
    seen, todo = set(), [item]
    while todo:  # walk the finite dependency graph
        i = todo.pop()
        if i in seen or i not in by_id:
            continue
        seen.add(i)
        todo += by_id[i].get("depends_on", [])
    root = _under(cfg.dir, top)
    own = [p for i in sorted(seen) for p in _own_paths(by_id[i])]
    if any(not _own_paths(by_id[i]) for i in seen):
        excl = [f":(exclude){p}" for p in _keyed(cfg, RESULT_KEYS, top)]
        return [root] + excl
    return [p if root == "." else f"{root}/{p}" for p in own] + _protected(cfg, top)


def state(cfg: Config) -> dict[str, Any]:
    """Derive the whole work list from project files; nothing comes from caches."""
    problems: list[str] = []
    top = git_top(cfg.dir)
    files = {}
    for key in cfg.paths:
        ps = cfg.files(key)  # a list-valued key is one entry with its paths joined by ", "
        entry: dict[str, Any] = {
            "path": ", ".join(map(str, ps)),
            "rel": ", ".join(_rel(cfg, p) for p in ps),
            "exists": all(p.exists() for p in ps),
            "create": key in DEFAULT_PATHS,  # harness-owned; the project's documents never
        }
        if key in cfg.sections:
            entry["section"] = cfg.sections[key]
        files[key] = entry
        if key not in DEFAULT_PATHS:
            problems += [f"{key}: {p} missing (a project document)" for p in ps if not p.exists()]
    if top is not None and not out_ignored(cfg, top):
        problems.append(
            f"measure_out {cfg.paths['measure_out']} is not git-ignored: add it to .gitignore "
            f"(bh-commit writes {HDIR}/.gitignore with out/ for the default location)"
        )
    bricks, targets, catalogue = _load_plan(cfg, problems)
    board, bad = read_board(cfg.file("scoreboard"))  # type: ignore[arg-type]
    if bad:
        problems.append(bad)
    by_id = {b["id"]: b for b in bricks}
    ids = set(by_id)
    head = (
        _git(top, "rev-parse", "HEAD")
        if top is not None and _git_ok(top, "rev-parse", "HEAD")
        else None
    )
    decs = load_decisions(cfg, problems)
    rules = overlay_rules(cfg)
    gaps, _ = apply_learning(check_gaps(cfg, bricks, targets, catalogue, board), decs, rules)
    status: dict[str, str] = {}
    last: dict[str, Any] = {}
    blocked_by: dict[str, list[str]] = {}
    unmerged = []
    for b in bricks:
        i = b["id"]
        dg = target_digest(cfg, b, targets)
        rc, rd = board["items"].get(i), board["candidates"].get(i)
        sc, sd = _facts(cfg, top, by_id, i, dg, rc), _facts(cfg, top, by_id, i, dg, rd)
        s, src = pick_status((rc, sc), (rd, sd))
        blockers = [g["id"] for g in gaps if i in g.get("blocks", [])]
        if blockers and s != "met":
            blocked_by[i] = blockers
            s = "blocked"
        status[i] = s
        newer = rd is not None and (
            rc is None or rd.get("measured_at", "") > rc.get("measured_at", "")
        )
        if sd == "met-unmerged" and newer and s in ("met", "met-unmerged"):
            # a met candidate newer than the current result waits for its merge, even while the
            # current result keeps the item met (a harvest of an item that already passed)
            unmerged.append({"item": i, "ref": rd["ref"]})
        if src is not None and s not in ("met", "met-unmerged"):  # feedback for a rebuild
            last[i] = {
                "ref": src["ref"],
                "status": src["status"],
                "unmet": [
                    {k: c[k] for k in ("metric", "op", "value", "actual")}
                    for c in src.get("targets", [])
                    if not c["met"]
                ],
                "errors": [e[:300] for e in src.get("errors", [])[:10]],
            }
        for d in b.get("depends_on", []):
            if d not in ids:
                problems.append(f"brick {i} depends on unknown {d}")
    waves = _waves(bricks, problems)
    order = [i for w in waves for i in w]
    unmerged.sort(key=lambda u: order.index(u["item"]) if u["item"] in order else len(order))
    split_parents = {b["split_from"] for b in bricks if b.get("split_from") in ids}
    out_bricks = []
    for b in bricks:
        deps = b.get("depends_on", [])
        out_bricks.append(
            {
                "id": b["id"],
                "kind": b.get("kind", "brick"),
                "depends_on": deps,
                "status": status[b["id"]],
                "ready": status[b["id"]] in READY_FROM
                and all(status.get(d) == "met" for d in deps),
                "blocked_by": blocked_by.get(b["id"], []),
                "split_parent": b["id"] in split_parents,
                "last": last.get(b["id"]),
                **({"est_loc": b["est_loc"]} if "est_loc" in b else {}),
            }
        )
    branches = _branches(top, ids)
    plan = _value_plan(cfg, out_bricks, order, set(branches), problems)
    for ob in out_bricks:  # finish before start: a later feature's items wait
        if ob["id"] in plan["held"]:
            ob["ready"], ob["held_by"] = False, plan["held"][ob["id"]]
    ecos = cfg.data.get("ecosystems", [])
    have: dict[tuple[str, str], set[str]] = {}  # (job, ecosystem) -> libraries
    for e in catalogue:
        have.setdefault((e["job"], e["ecosystem"]), set()).add(e["library"])
    versions = lock_versions(cfg.files("lockfiles"), problems)
    s_out: dict[str, Any] = {
        "config_path": str(cfg.path),
        "root": str(cfg.dir),
        "config": cfg.data,
        "files": files,
        "problems": problems,
        "bricks": out_bricks,
        "waves": waves,
        # only leaves run: a split parent is measured (its ``ready`` flag) but never built
        "ready": [
            b["id"]
            for b in out_bricks
            if b["ready"] and b["kind"] != "system" and not b["split_parent"]
        ],
        "ready_system": [
            b["id"]
            for b in out_bricks
            if b["ready"] and b["kind"] == "system" and not b["split_parent"]
        ],
        "unmerged": unmerged,
        "uncommitted": _uncommitted(cfg, top),
        "head": head,
        "plan_head": plan_head(cfg, top) if top is not None else None,
        "branches": branches,
        "commands": {b["id"]: rendered_commands(cfg, b) for b in bricks},
        "all_met": bool(bricks) and all(s == "met" for s in status.values()),
        "catalogue": {
            "entries": catalogue,
            "missing_jobs": _missing_jobs(cfg, catalogue, ecos),
            "duplicates": [
                {"job": j, "ecosystem": e, "libraries": sorted(libs)}
                for (j, e), libs in sorted(have.items())
                if len(libs) > 1
            ],
            "versions": {e["library"]: versions.get(norm(e["library"])) for e in catalogue},
        },
        "checklist": checklist_mentions(cfg),
        "overlay": overlay_path(cfg),
        "gaps": gaps,
    }
    s_out["pending"] = pending_page(out_bricks, plan["queue"], cfg.limit("decision_items"))
    s_out["value"] = plan["value"]
    s_out["learning"] = learning_part(cfg, decs, rules)
    s_out["features"] = _features_part(cfg, bricks, status)
    s_out["merged"] = _merged_part(cfg, top, bricks, board, status)
    s_out["counts"] = {
        k: len(v) for k, v in s_out.items() if isinstance(v, list | dict) and k != "config"
    }
    s_out["decision"] = _decision(cfg, s_out, out_bricks)
    s_out["decision"]["oscillating"] = oscillating(read_history(cfg))[: cfg.limit("decision_items")]
    return s_out


def pending_page(
    bricks: list[dict[str, Any]], order: list[str], limit: int, after: str | None = None
) -> dict[str, Any]:
    """Items not met in ``order`` (the value queue; the build order, dependency waves then id,
    without features.json), at most ``limit`` after the item ``after``: ``{items, more, next}``, ``more`` the count left, ``next`` the id to
    page on with (``bh-state --part pending --after ID``). Met items appear as counts only."""
    rank = {i: n for n, i in enumerate(order)}

    def key(b: dict[str, Any]) -> tuple[int, str]:
        return (rank.get(b["id"], len(rank)), b["id"])

    rows = sorted((b for b in bricks if b["status"] != "met"), key=key)
    if after is not None:
        ref = next((b for b in bricks if b["id"] == after), None)
        if ref is None:
            raise HarnessError(f"unknown item {after} to page after")
        rows = [b for b in rows if key(b) > key(ref)]
    page = rows[:limit]
    more = len(rows) - len(page)
    return {
        "items": [
            {
                k: b[k]
                for k in (
                    "id",
                    "kind",
                    "status",
                    "ready",
                    "depends_on",
                    "blocked_by",
                )
            }
            | ({"split_parent": True} if b.get("split_parent") else {})
            for b in page
        ],
        "more": more,
        "next": page[-1]["id"] if more and page else None,
    }


def _features_part(
    cfg: Config, bricks: list[dict[str, Any]], status: dict[str, str]
) -> dict[str, Any]:
    """Per feature named by an item not met (the horizon's features): items met and total
    (derived here, never stored) and the ids of the items naming it, capped."""
    cap = cfg.limit("decision_items")
    named: dict[str, list[str]] = {}
    for b in bricks:
        for f in b.get("features", []):
            named.setdefault(f, []).append(b["id"])
    horizon = sorted(f for f, ids in named.items() if any(status[i] != "met" for i in ids))
    rows = [
        {
            "feature": f,
            "met": sum(status[i] == "met" for i in named[f]),
            "total": len(named[f]),
            "ids": named[f][:cap],
            "more_ids": max(0, len(named[f]) - cap),
        }
        for f in horizon[:cap]
    ]
    return {"items": rows, "more": max(0, len(horizon) - cap)}


def _last_harvest(top: Path | None) -> datetime | None:
    if top is None or not _git_ok(top, "rev-parse", "--verify", "-q", "HEAD"):
        return None
    when = _git(top, "log", "-1", "--format=%cI", "--grep=^brick-harness: harvest")
    return datetime.fromisoformat(when) if when else None


def _merged_part(
    cfg: Config,
    top: Path | None,
    bricks: list[dict[str, Any]],
    board: dict[str, Any],
    status: dict[str, str],
) -> dict[str, Any]:
    """Items met since the last harvest commit (all of them before the first), newest first,
    capped, with their rendered commands: all a harvest reads of the items."""
    since = _last_harvest(top)
    rows = []
    for b in bricks:
        r = board["items"].get(b["id"])
        if status[b["id"]] != "met" or not r:
            continue
        at = r.get("measured_at", "")
        # a commit date has whole seconds: a result of the same second is not newer
        if since is None or (at and datetime.fromisoformat(at).replace(microsecond=0) > since):
            rows.append((at, b))
    rows.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
    cap = cfg.limit("decision_items")
    keep = [b for _, b in rows[:cap]]
    return {
        "since": since.isoformat() if since else None,
        "items": [{"id": b["id"], "status": "met"} for b in keep],
        "commands": {b["id"]: rendered_commands(cfg, b) for b in keep},
        "more": max(0, len(rows) - cap),
    }


def _decision(cfg: Config, s: dict[str, Any], bricks: list[dict[str, Any]]) -> dict[str, Any]:
    """The compact part a round loop reloads: what to do next, small enough that an agent
    can copy it back exactly, and bounded by ``limits.decision_items`` however many items
    there are: the first page of items not met in build order (``pending``), counts per
    status, ``more`` (the count left) and the paging command. Branches, commands and last
    results are for the listed items only; met items are counts."""
    cap = cfg.limit("decision_items")
    page = s["pending"]["items"]
    listed = {p["id"] for p in page}
    ready = [
        p["id"] for p in page if p["ready"] and p["kind"] != "system" and not p.get("split_parent")
    ]
    ready_sys = [
        p["id"] for p in page if p["ready"] and p["kind"] == "system" and not p.get("split_parent")
    ]
    ready_all = set(ready) | set(ready_sys)
    by_id = {b["id"]: b for b in bricks}
    counts: dict[str, int] = {}
    for b in bricks:
        counts[b["status"]] = counts.get(b["status"], 0) + 1
    return {
        "head": s["head"],
        "plan_head": s["plan_head"],
        "all_met": s["all_met"],
        "ready": ready,
        "ready_system": ready_sys,
        "pending": page,
        "more": s["pending"]["more"],
        "after": s["pending"]["next"],
        "paging": "bh-state --part pending --after ID",
        "blocked": {p["id"]: p["blocked_by"] for p in page if p["blocked_by"]},
        "held": {p["id"]: by_id[p["id"]]["held_by"] for p in page if by_id[p["id"]].get("held_by")},
        "value": {
            "sellable_at_head": s["value"]["sellable_at_head"][:cap],
            "if_stopped_today": s["value"]["if_stopped_today"][:cap],
            "next": s["value"]["next"],
            "unvalued": s["value"]["unvalued"][:cap],
            "unvalued_more": max(0, len(s["value"]["unvalued"]) - cap),
        },
        "unmerged": s["unmerged"][:cap],
        "conflicts": [p["id"] for p in page if p["status"] == "conflict"],
        "stale": [p["id"] for p in page if p["status"] == "stale"],
        "uncommitted": s["uncommitted"],
        "branches": {i: c for i, c in s["branches"].items() if i in listed},
        "commands": {i: c for i, c in s["commands"].items() if i in ready_all},
        "last": {
            i: {**by_id[i]["last"], "errors": [e[:200] for e in by_id[i]["last"]["errors"][:3]]}
            for i in sorted(ready_all)
            if by_id[i]["last"]
        },
        "counts": {
            "bricks": len(bricks),
            "ready": sum(1 for b in bricks if b["ready"]),
            "unmerged": len(s["unmerged"]),
            "problems": len(s["problems"]),
            "gaps": len(s["gaps"]),
            "status": counts,
        },
    }


def _facts(
    cfg: Config,
    top: Path | None,
    by_id: dict[str, Any],
    item: str,
    dg: str,
    r: dict[str, Any] | None,
) -> str | None:
    """Gather the git facts about one record and judge it with record_status."""
    if r is None:
        return None
    ok = r.get("targets_digest") == dg
    if not ok or r.get("ref") == "working-tree" or top is None:
        return record_status(r, ok, resolvable=top is not None)
    sha = str(r.get("ref", ""))
    res = bool(re.fullmatch(r"[0-9a-f]{40}", sha)) and _git_ok(
        top, "rev-parse", "--verify", "-q", sha + "^{commit}"
    )
    if not res or r["status"] != "met":
        return record_status(r, ok, resolvable=res)
    inh = _git_ok(top, "merge-base", "--is-ancestor", sha, "HEAD")
    same = inh and _git_ok(
        top, "diff", "--quiet", sha, "HEAD", "--", *_item_pathspec(cfg, top, by_id, item)
    )
    return record_status(r, ok, True, inh, same)


def _waves(bricks: list[dict[str, Any]], problems: list[str]) -> list[list[str]]:
    ids = {b["id"] for b in bricks}
    waves: list[list[str]] = []
    placed: set[str] = set()
    remaining = {b["id"]: set(b.get("depends_on", [])) & ids for b in bricks}
    while remaining:  # topological layering of a finite graph
        wave = sorted(i for i, deps in remaining.items() if deps <= placed)
        if not wave:
            problems.append(f"dependency cycle among {sorted(remaining)}")
            break
        waves.append(wave)
        placed |= set(wave)
        for i in wave:
            del remaining[i]
    return waves


def _branches(top: Path | None, ids: set[str]) -> dict[str, str]:
    """Builder branches by convention ``bh/<item>``: item -> commit."""
    if top is None:
        return {}
    try:
        raw = _git(top, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/bh/")
    except HarnessError:
        return {}
    out = {}
    for line in raw.splitlines():
        name, _, sha = line.partition(" ")
        item = name.removeprefix("refs/heads/bh/")
        if item in ids:
            out[item] = sha
    return out


def rendered_commands(cfg: Config, b: dict[str, Any]) -> dict[str, Any]:
    """The item's effective commands as a builder runs them from the project root: overrides
    applied, {item} {brick_path} {out} {ref} {root} {workdir} filled; {slot} and {port_base}
    left for the caller; a pending command shows only why it is pending."""
    out_dir = cfg.file("measure_out")
    assert out_dir is not None
    ctx = {
        "item": b["id"],
        "brick_path": b.get("path", ""),
        "out": _rel(cfg, out_dir / b["id"]),
        "workdir": ".",
        "root": ".",
        "ref": "HEAD",
    }
    c = cfg.commands_for(b)
    res: dict[str, Any] = {}
    if c.get("env_setup"):
        res["env_setup"] = _render(c["env_setup"], ctx)
    for k in ("test", "bench"):
        v = c.get(k)
        if v:
            res[k] = (
                {"pending": v["pending"]} if v.get("pending") else {"run": _render(v["run"], ctx)}
            )
    return res


def _missing_jobs(
    cfg: Config, catalogue: list[dict[str, Any]], ecos: list[str]
) -> dict[str, list[str]]:
    jobs = [j for j in cfg.data.get("catalogue_jobs", DEFAULT_JOBS) if j not in cfg.na]
    covered = {(e["job"].split(":", 1)[0], e["ecosystem"]) for e in catalogue}  # formats:csv
    return {eco: [j for j in jobs if (j, eco) not in covered] for eco in ecos}


def _in_head(top: Path, ref: str) -> bool:
    return _git_ok(top, "merge-base", "--is-ancestor", ref, "HEAD")


def _uncommitted(cfg: Config, top: Path | None, scoreboard: bool = False) -> list[str]:
    """Harness files (not the scoreboard) with changes not in HEAD; builders fork from HEAD."""
    if top is None:
        return []
    paths = _plan_paths(cfg, top, scoreboard=scoreboard)
    if not paths:
        return []
    cmd = ["git", "-C", str(top), "status", "--porcelain", "--untracked-files=all", "--", *paths]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout  # unstripped: XY<space>path
    return [_rel(cfg, top / line[3:]) for line in out.splitlines()]


# ---------------------------------------------------------------- checksums (bh-state parts)


def canon(v: Any) -> str:
    """Canonical text of a JSON value that lib/prelude.js reproduces exactly: strings with
    their UTF-16 length, numbers floored (exponent forms differ between languages), keys
    in UTF-16 order, null-valued keys left out."""
    if v is None:
        return "n"
    if v is True:
        return "t"
    if v is False:
        return "f"
    if isinstance(v, int | float):
        return "d" + (str(math.floor(v)) if abs(v) < 1e15 else "big")
    if isinstance(v, str):
        return f"s{len(v.encode('utf-16-le')) // 2}:{v}"
    if isinstance(v, list):
        return "[" + "".join(canon(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted((k for k in v if v[k] is not None), key=lambda k: k.encode("utf-16-be"))
        return "{" + "".join(canon(k) + canon(v[k]) for k in keys) + "}"
    raise HarnessError(f"not a JSON value: {type(v).__name__}")


def checksum(v: Any) -> str:
    """32-bit FNV-1a over the UTF-16 code units of canon(v), as lib/prelude.js computes it."""
    h = 0x811C9DC5
    data = canon(v).encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


# ---------------------------------------------------------------- gaps (report, never decide)

GAP_KINDS = (
    "missing-document",
    "dangling-reference",
    "no-acceptance",
    "no-numeric-target",
    "target-without-source",
    "target-without-command",
    "target-on-unknown-item",
    "duplicate-item",
    "no-contract",
    "missing-dependency",
    "item-without-source",
    "contradiction",
    "untracked-open-item",
    "helper-without-library",
    "unsettled-area",
    "unmet-after-rounds",
    "not-derivable",
    "missing-context",
    "other",
)
DOC_KEYS = (
    "features",
    "acceptance",
    "standards",
    "decisions_dir",
    "stack_manifest",
    "build_order",
    "status",
    "overlay",
)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+[\"'(].*)?$")
# Targets every item may carry without a cited source: that the item has passing tests is
# not a design number.
DEFAULT_TEST_TARGETS = {
    ("tests.failed", "==", 0),
    ("tests.errors", "==", 0),
    ("tests.passed", ">=", 1),
}


def _standard_layers(cfg: Config) -> dict[str, Path]:
    """The project overlay of the owner's rule catalog, when set (placeholders start with <)."""
    st = cfg.data.get("standards", {})
    v = st.get("overlay")
    return {"overlay": (cfg.dir / v).resolve()} if v and not v.startswith("<") else {}


def overlay_path(cfg: Config) -> str | None:
    """The overlay as a path relative to the project root, for the reviewer's prompt."""
    p = _standard_layers(cfg).get("overlay")
    return _rel(cfg, p) if p else None


def catalog_skill(name: str) -> str:
    """A skill of this plugin, referenced by its plugin-qualified name (never copied)."""
    return f"agent-compliance:{name}"


def _docs(cfg: Config) -> list[Path]:
    """The project's own text documents (directories expand to their markdown files)."""
    out: list[Path] = []
    for key in DOC_KEYS:
        for p in cfg.files(key) + (
            [_standard_layers(cfg)[key]] if key in _standard_layers(cfg) else []
        ):
            if p.is_dir():
                out += sorted(p.rglob("*.md"))
            elif p.is_file():
                out.append(p)
    return list(dict.fromkeys(out))


def _lines(p: Path) -> list[str]:
    try:
        return p.read_text(errors="ignore").splitlines()
    except OSError:
        return []


def _bounded(needle: str) -> re.Pattern[str]:
    """Match ``needle`` as a whole token: no word character (or -) glued on either side."""
    left = r"(?<![\w-])" if re.match(r"[\w-]", needle) else ""
    right = r"(?![\w-])" if re.search(r"[\w-]$", needle) else ""
    return re.compile(left + re.escape(needle) + right)


def _line_of(p: Path | None, needle: str) -> int | None:
    """First line holding ``needle`` as a whole token; None when absent (never a made-up line)."""
    if p is None or not needle:
        return None
    pat = _bounded(needle)
    for n, line in enumerate(_lines(p), 1):
        if pat.search(line):
            return n
    return None


def _ev(cfg: Config, p: Path | None, needle: str) -> list[tuple[str, int]]:
    n = _line_of(p, needle)
    return [(_rel(cfg, p), n)] if p is not None and n is not None else []


def slug(heading: str) -> str:
    """GitHub-style heading anchor."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def headings(p: Path) -> list[str]:
    out, fence = [], False
    for line in _lines(p):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and re.match(r"#{1,6} ", line):
            out.append(line.lstrip("#").strip())
    return out


def _has_section(p: Path, section: str) -> bool:
    hs = headings(p)
    s = section.lstrip("#").strip()
    return any(h == s or h.startswith(s) or slug(h) == slug(s) for h in hs)


def _gap(
    kind: str, summary: str, tag: str, ev: list[tuple[str, int]], **extra: Any
) -> dict[str, Any]:
    g = {
        "id": f"check:{kind}:{digest([kind, summary])[:8]}",
        "kind": kind,
        "summary": summary,
        "tag": tag,
        "evidence": [{"file": f, "line": n} for f, n in ev],
        "source": "check",
        **extra,
    }
    if not ev and not extra.get("looked_in"):
        g["unlocated"] = (
            True  # the check found no line to cite; it says so instead of inventing one
        )
    return g


def load_checklist(cfg: Config | None = None) -> list[dict[str, Any]]:
    """Design areas: the config's ``checklist`` (inline list or a JSON file under the root),
    else the plugin's tiny generic default."""
    spec = cfg.data.get("checklist") if cfg else None
    if isinstance(spec, list):
        return spec
    path = (
        (cfg.dir / spec)
        if (cfg and isinstance(spec, str))
        else SCHEMA_DIR / "design-checklist.json"
    )
    doc = load_json(path)
    areas = doc["areas"] if isinstance(doc, dict) else doc
    return areas  # type: ignore[no-any-return]


def _config_value(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _settled_value(v: Any) -> bool:
    """A configured value that settles an area: present, not pending, not a <placeholder>."""
    if isinstance(v, dict):
        return not v.get("pending") and _settled_value(v.get("run", "x"))
    if isinstance(v, str):
        return bool(v.strip()) and not v.startswith("<")
    return v is not None


def checklist_mentions(cfg: Config) -> list[dict[str, Any]]:
    """Where each design area is mentioned (a place to look, never proof it is settled).

    The config itself settles an area through the dotted keys in the area's ``config`` (e.g.
    the test and bench commands); an area the config marks ``na`` carries its reason.
    """
    try:
        areas = load_checklist(cfg)
    except HarnessError:
        areas = []
    docs = [(d, _lines(d)) for d in _docs(cfg)]
    out = []
    for a in areas:
        entry: dict[str, Any] = {"id": a["id"], "area": a["area"], "mentioned_at": []}
        if a["id"] in cfg.na:
            entry["na"] = cfg.na[a["id"]]
            out.append(entry)
            continue
        hits = []
        for key in a.get("config", []):
            if _settled_value(_config_value(cfg.data, key)):
                n = _line_of(cfg.path, f'"{key.rsplit(".", 1)[-1]}"')
                hits.append(f"{_rel(cfg, cfg.path)}:{n or 1}" if n else _rel(cfg, cfg.path))
        kws = a.get("keywords", [])
        if kws:
            pat = re.compile("|".join(_bounded(k).pattern for k in kws), re.I)
            hits += [
                f"{_rel(cfg, d)}:{n}"
                for d, ls in docs
                for n, line in enumerate(ls, 1)
                if pat.search(line)
            ]
        entry["mentioned_at"] = hits[:3]
        out.append(entry)
    return out


def _numbers(line: str) -> list[float]:
    line = re.sub(r"(?<=\d)[,_   ](?=\d{3}(?!\d))", "", line)
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", line)]


REF_SOURCE = re.compile(r'(\S+): "(.+)"', re.S)


def _ref_source_problem(
    t: dict[str, Any], ref: str, quote: str, show: Callable[[str], Any] | None
) -> str | None:
    """Why a tracker source ``<ref>: "<quote>"`` does not back the target's value, or None:
    the question asked of file:line, put to the entry tracker.show returns. ``show`` None
    means the caller must not reach the tracker (bh-state): the source is not judged. An
    entry that cannot be read (offline included) is unresolved like a missing source."""
    if show is None:
        return None
    try:
        entry = show(ref)
    except HarnessError as e:
        return f"source {ref} cannot be read from the tracker: {e}"
    if _squash(quote) not in _squash(f"{entry['title']}\n{entry.get('body') or ''}"):
        return f"source {ref} does not contain the quoted text"
    if not any(math.isclose(x, float(t["value"]), rel_tol=1e-9) for x in _numbers(quote)):
        return f"source {ref} does not state {t['value']}"
    return None


def _source_problem(
    cfg: Config, t: dict[str, Any], show: Callable[[str], Any] | None = None
) -> str | None:
    """Why a target's ``source`` (file:line, or a tracker ref with a quote) does not back
    its value, or None."""
    src = t.get("source")
    if (t["metric"], t["op"], t["value"]) in DEFAULT_TEST_TARGETS:
        return None
    if not src:
        return "states no source (file:line of the number)"
    rm = REF_SOURCE.fullmatch(src.strip())
    if rm and not re.fullmatch(r"(.+):(\d+)", src.strip()):
        return _ref_source_problem(t, rm.group(1), rm.group(2), show)
    m = re.fullmatch(r"(.+):(\d+)", src.strip())
    if not m:
        return f"source {src!r} is not file:line"
    p = (cfg.dir / m.group(1)).resolve()
    ls = _lines(p) if p.is_file() else []
    n = int(m.group(2))
    if not 1 <= n <= len(ls):
        return f"source {src} does not exist"
    if not any(math.isclose(x, float(t["value"]), rel_tol=1e-9) for x in _numbers(ls[n - 1])):
        return f"source {src} does not state {t['value']}"
    return None


def _exe(run: str) -> str:
    """The program a command runs, after leading VAR=value assignments."""
    for tok in run.split():
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue
        return tok
    return ""


def _cmd_problem(c: dict[str, Any], root: Path) -> str | None:
    exe = _exe(c["run"])
    if c.get("pending"):
        return f"not yet present: {c['pending']}"
    if c["run"].startswith("<"):
        return f"is a placeholder: {c['run']}"
    if "/" in exe and not re.search(r"[{$~*]", exe) and not (root / exe).exists():
        return f"runs {exe}, which does not exist"
    return None


def _link_target(cfg: Config, d: Path, t: str) -> str | None:
    """None when a markdown link target resolves; else the target as written."""
    if re.match(r"[a-z][a-z0-9+.-]*:", t, re.I):
        return None  # http:, mailto:, ...
    path, _, anchor = t.partition("#")
    path = urllib.parse.unquote(path)
    if path.startswith("/"):
        tp = (cfg.dir / path.lstrip("/")).resolve()
    else:
        tp = (d.parent / path).resolve() if path else d
    ok = tp.exists() and (
        not anchor
        or tp.suffix != ".md"
        or urllib.parse.unquote(anchor) in {slug(h) for h in headings(tp)}
    )
    return None if ok else t


def check_gaps(
    cfg: Config,
    bricks: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    catalogue: list[dict[str, Any]],
    board: dict[str, Any] | None = None,
    show: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Mechanical gap checks; judgement kinds (contradictions, ...) come from the reviewer.

    A gap that stops an item from ever being met lists the item in ``blocks``.
    """
    gaps: list[dict[str, Any]] = []
    conf = cfg.path
    for key in DOC_KEYS + ("lockfiles",):
        for p in cfg.files(key):
            if not p.exists():
                rel = _rel(cfg, p)
                gaps.append(
                    _gap(
                        "missing-document",
                        f"{key}: {rel} does not exist",
                        "fixable",
                        _ev(cfg, conf, rel),
                    )
                )
    import bhrules

    gaps += bhrules.unbound_gaps(cfg)
    st = cfg.data.get("standards", {})
    for key in ("base_version", "overlay"):  # an unset or placeholder catalog is this plugin's
        v = st.get(key)
        if isinstance(v, str) and v.startswith("<"):
            gaps.append(
                _gap(
                    "missing-document",
                    f"standards.{key} is a placeholder: {v}",
                    "owner-decides",
                    _ev(cfg, conf, v),
                )
            )
    for key, p in _standard_layers(cfg).items():
        if not p.exists():
            gaps.append(
                _gap(
                    "missing-document",
                    f"standards.{key}: {st[key]} does not exist",
                    "fixable",
                    _ev(cfg, conf, st[key]),
                )
            )
    for key, section in cfg.sections.items():
        sp = cfg.file(key)
        if sp and sp.is_file() and not _has_section(sp, section):
            gaps.append(
                _gap(
                    "dangling-reference",
                    f"{key}: no section {section!r} in {_rel(cfg, sp)}",
                    "fixable",
                    _ev(cfg, conf, section),
                )
            )
    for d in _docs(cfg):
        if d.suffix != ".md":
            continue
        fence = False
        for n, line in enumerate(_lines(d), 1):
            if line.lstrip().startswith("```"):
                fence = not fence
            if fence:
                continue
            found = [m.group(1) for m in LINK.finditer(line)]
            rm = REF_LINK.match(line)
            if rm:
                found.append(rm.group(1))
            for t in found:
                bad = _link_target(cfg, d, t)
                if bad:
                    gaps.append(
                        _gap(
                            "dangling-reference",
                            f"link to {bad} does not resolve",
                            "fixable",
                            [(_rel(cfg, d), n)],
                        )
                    )
    bfile, tfile = cfg.file("bricks"), cfg.file("targets")
    ids = [b["id"] for b in bricks]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        lines = (
            [
                (_rel(cfg, bfile), n)
                for n, line in enumerate(_lines(bfile), 1)
                if bfile and _bounded(f'"{dup}"').search(line) and '"id"' in line
            ]
            if bfile
            else []
        )
        gaps.append(
            _gap(
                "duplicate-item",
                f"item id {dup} is listed {ids.count(dup)} times",
                "fixable",
                lines,
                blocks=[dup],
            )
        )
    for b in bricks:
        ev = _ev(cfg, bfile, f'"{b["id"]}"')
        if not targets_for(targets, b["id"]):
            gaps.append(
                _gap(
                    "no-numeric-target",
                    f"item {b['id']} has no targets",
                    "owner-decides",
                    ev,
                    blocks=[b["id"]],
                )
            )
        if b.get("kind", "brick") == "brick" and not (
            b.get("contract") and (cfg.dir / b["contract"]).exists()
        ):
            gaps.append(
                _gap(
                    "no-contract",
                    f"item {b['id']} has no input/output contract file",
                    "fixable",
                    ev,
                )
            )
        for dep in b.get("depends_on", []):
            if dep not in ids:
                gaps.append(
                    _gap(
                        "missing-dependency",
                        f"item {b['id']} depends on unknown {dep}",
                        "fixable",
                        ev,
                        blocks=[b["id"]],
                    )
                )
        if b.get("split_from") and b["split_from"] not in ids:
            gaps.append(
                _gap(
                    "missing-dependency",
                    f"item {b['id']} is split from unknown {b['split_from']}",
                    "fixable",
                    ev,
                    blocks=[b["id"]],
                )
            )
        if cfg.paths.get("build_order") and not b.get("source") and not b.get("refs"):
            gaps.append(
                _gap(
                    "item-without-source",
                    f"item {b['id']} names no source in the build order",
                    "fixable",
                    ev,
                )
            )
        for kind, c in b.get("commands", {}).items():
            if isinstance(c, dict) and kind in ("test", "bench"):
                why = _cmd_problem(c, cfg.dir)
                if why:
                    gaps.append(
                        _gap(
                            "target-without-command",
                            f"item {b['id']} commands.{kind} {why}",
                            "fixable",
                            ev,
                            blocks=[b["id"]],
                        )
                    )
    by_id = {b["id"]: b for b in bricks}
    for t in targets:
        tev = _ev(cfg, tfile, f'"{t["item"]}"') if tfile else []
        if t["item"] not in by_id:
            gaps.append(
                _gap(
                    "target-on-unknown-item",
                    f"target {t['metric']} names unknown item {t['item']}",
                    "fixable",
                    tev,
                )
            )
            continue
        cmds = cfg.commands_for(by_id[t["item"]])
        kind = "test" if t["metric"].startswith("tests.") else "bench"
        if kind not in cmds:
            msg = f"target {t['item']} {t['metric']} has no {kind} command"
            gaps.append(_gap("target-without-command", msg, "fixable", tev, blocks=[t["item"]]))
        why = _source_problem(cfg, t, show)
        if why:
            msg = f"target {t['item']} {t['metric']} {t['op']} {t['value']} {why}"
            tag = "owner-decides" if "no source" in why else "fixable"
            gaps.append(_gap("target-without-source", msg, tag, tev))
    for kind in ("test", "bench"):
        c = cfg.commands.get(kind)
        if not c:
            continue
        why = _cmd_problem(c, cfg.dir)
        if not why:
            continue
        users = [
            b["id"]
            for b in bricks
            if kind not in b.get("commands", {})
            and (
                kind == "test"
                or any(t["metric"].startswith("bench.") for t in targets_for(targets, b["id"]))
            )
        ]
        gaps.append(
            _gap(
                "target-without-command",
                f"commands.{kind} {why}",
                "fixable",
                _ev(cfg, conf, c["run"]) or _ev(cfg, conf, f'"{kind}"'),
                blocks=users,
            )
        )
    for b in bricks:  # an environment the item cannot change: the owner's env_setup fails
        recs = [
            r for r in ((board or {}).get(k, {}).get(b["id"]) for k in ("items", "candidates")) if r
        ]
        if not recs:
            continue
        r = max(recs, key=lambda x: x.get("measured_at", ""))
        fails = [e for e in r.get("errors", []) if e.startswith("env_setup:")]
        if fails and r.get("targets_digest") == target_digest(cfg, b, targets):
            setup = cfg.commands_for(b).get("env_setup", "")
            src = bfile if "env_setup" in b.get("commands", {}) else conf
            gaps.append(
                _gap(
                    "target-without-command",
                    f"env_setup fails for item {b['id']} ({fails[0]})",
                    "fixable",
                    _ev(cfg, src, setup) or _ev(cfg, src, '"env_setup"'),
                    blocks=[b["id"]],
                )
            )
    for eco, jobs in _missing_jobs(cfg, catalogue, cfg.data.get("ecosystems", [])).items():
        if jobs:
            msg = f"{eco}: no library named for helper jobs {', '.join(jobs)}"
            gaps.append(
                _gap(
                    "helper-without-library",
                    msg,
                    "fixable",
                    _ev(cfg, conf, '"ecosystems"'),
                    resolve_with=catalog_skill("vet-oss"),
                )
            )
    looked = [_rel(cfg, p) for k in DOC_KEYS for p in cfg.files(k) if p.exists()]
    looked += [_rel(cfg, p) for p in _standard_layers(cfg).values() if p.exists()]
    looked.append(_rel(cfg, cfg.path))
    for a in checklist_mentions(cfg):
        if not a["mentioned_at"] and "na" not in a:
            msg = f"design area not settled in any project document: {a['area']}"
            gaps.append(
                _gap("unsettled-area", msg, "owner-decides", [], looked_in=looked, area=a["id"])
            )
    return _with_resolver(cfg, gaps)


def _with_resolver(cfg: Config, gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Owner-level gaps name the catalog's decision skill (reported, never run automatically)."""
    for g in gaps:
        if g["tag"] == "owner-decides":
            g.setdefault("resolve_with", catalog_skill("vetted-decision"))
    return gaps


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _bad_evidence(cfg: Config, g: dict[str, Any]) -> str | None:
    item_schema = load_schema("gaps")["$defs"]["gap"]
    errs = validate(g, item_schema, load_schema("gaps"))
    if errs:
        return "; ".join(errs[:3])
    if not g["evidence"] and not (g["kind"] == "unsettled-area" and g.get("looked_in")):
        return "no file:line evidence"
    for e in g["evidence"]:
        p = (cfg.dir / e["file"]).resolve()
        if not p.is_file():
            return f"evidence file {e['file']} does not exist"
        ls = _lines(p)
        if not 1 <= e["line"] <= len(ls):
            return f"evidence line {e['file']}:{e['line']} out of range"
        q = e.get("quote")
        if q and _squash(q) not in _squash(ls[e["line"] - 1]):
            return f"evidence {e['file']}:{e['line']} does not contain the quoted text"
    return None


STUCK_REASONS = {
    "build-failed": "the builder returned no usable commit",
    "no-change": "the builder made no change and the item at HEAD does not meet its targets",
    "unmet": "the item still misses its targets",
    "not-attempted": "the item was never built or measured (dependencies not met or rounds ran out)",
    "budget": "the run ended on its token budget (config budgets) before the item was rebuilt",
    "oscillating": "a target of the item went met to unmet after another item's change, twice",
}


def stuck_rows(
    cfg: Config, items: list[str], every: bool = False, st: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Items not met when a cycle's rounds end, each with how it got there, in build order.

    ``items`` are ``ITEM`` or ``ITEM:REASON`` (REASON one of STUCK_REASONS) for what the run
    attempted or left over; with ``every`` each other item not met is derived from the files
    as ``not-attempted``. An item whose target went met to unmet after another item's change,
    twice (the target history), is ``oscillating`` with the items named, unless the run ended
    on its budget before the item was rebuilt. Facts only: no status is changed."""
    given: dict[str, str] = {}
    for raw in items:
        i, _, why = raw.rpartition(":")
        if not i or why not in STUCK_REASONS:
            i, why = raw, "unmet"
        given[i] = why
    st = st or state(cfg)
    osc: dict[str, set[str]] = {}
    for o in oscillating(read_history(cfg)):
        osc.setdefault(o["item"], set()).update(o["changed_by"])
    by_id = {b["id"]: b for b in st["bricks"]}
    placed = [i for w in st["waves"] for i in w]
    seen = set(placed)
    order = placed + [i for i in by_id if i not in seen]
    rows = []
    for i in order:
        b = by_id[i]
        not_met = b["status"] not in ("met", "met-unmerged")
        if not (not_met if every else i in given):
            continue
        why = given.get(i, "not-attempted")
        if why != "budget" and i in osc:
            why = "oscillating"
        last = b.get("last") or {}
        rows.append(
            {
                "item": i,
                "status": b["status"],
                "reason": why,
                "errors": [e[:300] for e in last.get("errors", [])[:3]],
                **(
                    {"oscillating_with": sorted(osc[i])}
                    if why == "oscillating" and i in osc
                    else {}
                ),
            }
        )
    return rows


def unmet_gaps(
    cfg: Config, items: list[str], every: bool = False, st: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Gaps for items not met when the cycle's rounds end: a defect to analyse, cited at the
    item's scoreboard entry (or its line in the items file when it was never measured), with
    the reason and the last measurer errors (named with the catalog's defect skill; reported,
    never run). See ``stuck_rows`` for ``items`` and ``every``."""
    if not items and not every:
        return []
    sb, bf = cfg.file("scoreboard"), cfg.file("bricks")
    out = []
    for r in stuck_rows(cfg, items, every, st):
        i, why = r["item"], r["reason"]
        n, src = _line_of(sb, f'"{i}": {{'), sb
        if sb is None or n is None:
            n, src = _line_of(bf, f'"{i}"'), bf
        if src is None or n is None:
            continue
        errs = "; ".join(r["errors"])
        by = (
            f" after a change by {', '.join(r['oscillating_with'])}"
            if "oscillating_with" in r
            else ""
        )
        g: dict[str, Any] = {
            "kind": "unmet-after-rounds",
            "summary": f"item {i} is not met after the cycle's rounds ({why}: {STUCK_REASONS[why]}{by})"
            + (f"; last errors: {errs}"[:600] if errs else ""),
            "tag": "fixable",
            "evidence": [{"file": _rel(cfg, src), "line": n}],
        }
        g["resolve_with"] = catalog_skill("bug-analysis")
        out.append(g)
    return out


def structure_facts(
    cfg: Config,
    bricks: list[dict[str, Any]],
    st: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(rollup, facts) for the gaps report (M4, M12), derived at read time and never stored:
    per feature named by an item not met, items met and total; split parents that do not list
    a child in depends_on; paths owned by two items; items never scored. Changes no status."""
    status = {b["id"]: b["status"] for b in st["bricks"]}
    named: dict[str, list[str]] = {}
    for b in bricks:
        for f in b.get("features", []):
            named.setdefault(f, []).append(b["id"])
    rollup = {
        f: {"met": sum(status[i] == "met" for i in ids), "total": len(ids)}
        for f, ids in sorted(named.items())
        if any(status[i] != "met" for i in ids)
    }
    facts: list[dict[str, Any]] = []
    for b in bricks:
        if b.get("_undeclared_children"):
            facts.append(
                {
                    "kind": "split-parent-without-child-dependency",
                    "item": b["id"],
                    "children": b["_undeclared_children"],
                    "note": "depends_on does not list them; the harness measures the parent after them anyway",
                }
            )
    owners: dict[str, set[str]] = {}
    for b in bricks:
        for p in _own_paths(b):
            owners.setdefault(p.rstrip("/"), set()).add(b["id"])
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for p, ids in sorted(owners.items()):
        sharing = set(ids)
        for anc in PurePosixPath(p).parents:
            sharing |= owners.get(str(anc), set())
        if len(sharing) > 1 and (p, tuple(sorted(sharing))) not in seen:
            seen.add((p, tuple(sorted(sharing))))
            facts.append({"kind": "shared-path", "path": p, "items": sorted(sharing)})
    for b in bricks:
        if status[b["id"]] == "unmeasured":
            facts.append({"kind": "never-scored", "item": b["id"]})
    facts += split_facts(bricks, status)
    return rollup, facts


def split_facts(bricks: list[dict[str, Any]], status: dict[str, str]) -> list[dict[str, Any]]:
    """M12 facts: a split child with no ``split_kind`` (split-without-kind), and a split
    parent not met although all its children are (parent-unmet-after-children)."""
    facts: list[dict[str, Any]] = []
    children: dict[str, list[str]] = {}
    for b in bricks:
        if b.get("split_from"):
            children.setdefault(b["split_from"], []).append(b["id"])
            if not b.get("split_kind"):
                facts.append(
                    {"kind": "split-without-kind", "item": b["id"], "parent": b["split_from"]}
                )
    for p, kids in sorted(children.items()):
        if (
            p in status
            and all(status.get(k) == "met" for k in kids)
            and status[p] in ("unmet", "stale", "conflict")
        ):
            facts.append(
                {"kind": "parent-unmet-after-children", "item": p, "children": sorted(kids)}
            )
    return facts


def _dependency_cycle_members(bricks: list[dict[str, Any]]) -> set[str]:
    """Items that can reach themselves through depends_on (an item merely behind a cycle is not)."""
    deps = {b["id"]: [d for d in b.get("depends_on", [])] for b in bricks}
    out = set()
    for start in deps:
        seen: set[str] = set()
        todo = list(deps[start])
        while todo:  # walk the finite graph
            i = todo.pop()
            if i == start:
                out.add(start)
                break
            if i not in seen:
                seen.add(i)
                todo += deps.get(i, [])
    return out


def _first_seen(top: Path | None, rel: str, item: str) -> str | None:
    """Commit time of the first commit whose items file names ``item``."""
    if top is None or not _git_ok(top, "rev-parse", "--verify", "-q", "HEAD"):
        return None
    try:
        out = _git(top, "log", "--reverse", "--format=%cI", f'-S"id": "{item}"', "--", rel)
    except HarnessError:
        return None
    return out.splitlines()[0] if out else None


def invest_flow(
    cfg: Config,
    bricks: list[dict[str, Any]],
    st: dict[str, Any],
    board: dict[str, Any] | None,
    tracker_parent_feature: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    """M11 facts, never scored. Per item not met (capped at limits.decision_items): the INVEST
    questions as booleans (independent: not in a dependency cycle; valuable: names a feature or
    its tracker parent is a feature; estimable: est_loc present; small: no sizing note;
    testable: not blocked by a gap). Flow (Kanban): WIP against horizon.items, and the cycle
    time of items met since the last harvest, from the commit that introduced the item to its
    scoreboard ``measured_at``; throughput is their count."""
    cap = cfg.limit("decision_items")
    status = {b["id"]: b["status"] for b in st["bricks"]}
    blocked = {b["id"]: b["blocked_by"] for b in st["bricks"]}
    cyc = _dependency_cycle_members(bricks)
    notes: dict[str, int] = {}
    for n in sizing_notes(cfg, bricks, board):
        notes[n["item"]] = notes.get(n["item"], 0) + 1
    facts: list[dict[str, Any]] = []
    for b in [x for x in bricks if status[x["id"]] != "met"][:cap]:
        i = b["id"]
        facts.append(
            {
                "kind": "invest",
                "item": i,
                "independent": i not in cyc,
                "valuable": bool(b.get("features"))
                or bool(tracker_parent_feature and tracker_parent_feature(b)),
                "estimable": "est_loc" in b,
                "small": i not in notes,
                "testable": not blocked.get(i),
            }
        )
    top = git_top(cfg.dir)
    bf = cfg.file("bricks")
    since = _last_harvest(top)
    rows = []
    for b in bricks:
        r = ((board or {}).get("items") or {}).get(b["id"])
        if status[b["id"]] != "met" or not r or not r.get("measured_at"):
            continue
        at = datetime.fromisoformat(r["measured_at"])
        if since is not None and at.replace(microsecond=0) <= since:
            continue
        born = (
            _first_seen(top, _under(bf, top), b["id"])
            if top and bf and bf.is_relative_to(top)
            else None
        )
        if born:
            rows.append((b["id"], round((at - datetime.fromisoformat(born)).total_seconds())))
    horizon = int(cfg.data.get("horizon", {}).get("items", 20))
    facts.append(
        {
            "kind": "flow",
            "wip": sum(1 for v in status.values() if v != "met"),
            "horizon": horizon,
            "throughput": len(rows),
            "cycle_time_s": dict(sorted(rows)[:cap]),
        }
    )
    return facts


def merge_gaps(
    cfg: Config,
    added: list[dict[str, Any]],
    source: str,
    write: bool = False,
    unmet: list[str] | None = None,
    show: Callable[[str], Any] | None = None,
    tracker_facts: Callable[[dict[str, Any], list[dict[str, Any]]], list[dict[str, Any]]]
    | None = None,
    parent_feature: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Recompute the mechanical gaps, replace ``source``'s earlier findings with ``added``.

    Findings whose evidence does not resolve to an existing file:line (or whose quote is not
    on that line) are rejected, so a reviewer cannot report what it did not read. Writes
    nothing unless ``write``. An empty ``added`` clears ``source``'s earlier findings. For
    source ``cycle`` every item not met gets a gap (the ``unmet`` ones with their reason, the
    rest ``not-attempted``) and ``stuck`` lists them capped at ``limits.decision_items`` with
    ``stuck_more``; the full list is in the report.
    """
    if source == "check":
        raise HarnessError("source 'check' is reserved for the mechanical checks")
    if not isinstance(added, list):
        raise HarnessError("findings must be a JSON list")
    st = state(cfg) if (unmet or source == "cycle") else None
    rows = stuck_rows(cfg, unmet or [], source == "cycle", st) if st else []
    added = added + unmet_gaps(cfg, unmet or [], source == "cycle", st)
    problems: list[str] = []
    bricks, targets, catalogue = _load_plan(cfg, problems)
    board, _ = read_board(cfg.file("scoreboard"))  # type: ignore[arg-type]
    old: list[dict[str, Any]] = []
    prev_head = None
    gp = cfg.file("gaps")
    if gp and gp.exists():
        old_doc = load_json(gp, "gaps")
        old, prev_head = old_doc["gaps"], old_doc.get("reviewed_head")
        old += [x["gap"] for x in old_doc.get("answered", []) + old_doc.get("re_asked", [])]
    kept = [g for g in old if g.get("source") not in ("check", source)]
    accepted, rejected = [], []
    for g in added:
        if not isinstance(g, dict):
            rejected.append({"gap": g, "reason": "not an object"})
            continue
        stable = digest([g.get("kind"), g.get("summary"), g.get("evidence")])[:8]
        g = {**g, "source": source, "id": f"{source}:{g.get('kind', 'other')}:{stable}"}
        why = _bad_evidence(cfg, g)
        if why:
            rejected.append({"gap": g, "reason": why})
        else:
            accepted.append(g)
    decs, rules = load_decisions(cfg, problems), overlay_rules(cfg)
    gaps, learn = apply_learning(
        check_gaps(cfg, bricks, targets, catalogue, board, show)
        + kept
        + _with_resolver(cfg, accepted),
        decs,
        rules,
    )
    st = st or state(cfg)
    rollup, facts = structure_facts(cfg, bricks, st)
    unmet_items = [b["id"] for b in st["bricks"] if b["status"] != "met"]
    pk = packet_report(cfg, unmet_items)
    import bhrules

    facts = facts + learn["bad_cites"] + pk["facts"] + bhrules.rule_facts(cfg, bricks)
    facts += invest_flow(cfg, bricks, st, board, parent_feature)
    if tracker_facts is not None:
        facts += tracker_facts(st, bricks)
    finds = [g for g in gaps if g.get("source") == "finding"]
    report = {
        "writer": "brick-harness gaps",
        "counts": {
            t: sum(g["tag"] == t and g.get("source") != "finding" for g in gaps)
            for t in ("owner-decides", "fixable")
        },
        "gaps": gaps,
        "rollup": rollup,
        "facts": facts,
        "reviewed_head": _head(cfg) if write and source == "review" else prev_head,
        "sizing_notes": sizing_notes(cfg, bricks, board) + pk["notes"],
        "answered": learn["answered"],
        "re_asked": learn["re_asked"],
        "learning": learning_counts(cfg, gaps, learn, decs, rules, finds),
        "value": st["value"],
        "packets": pk["packets"],
    }
    written = []
    if write:
        assert gp is not None
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(json.dumps(report, indent=2) + "\n")
        written.append(_rel(cfg, gp))
        md = cfg.file("gaps_md")
        if md:
            md.write_text(render_gaps_md(report))
            written.append(_rel(cfg, md))
    cap = cfg.limit("decision_items")
    return {
        **report,
        "received": len(added),
        "accepted": len(accepted),
        "rejected": rejected,
        "problems": problems,
        "written": written,
        "dry_run": not write,
        **(
            {"stuck": rows[:cap], "stuck_more": max(0, len(rows) - cap)}
            if source == "cycle"
            else {}
        ),
    }


def _gap_row(g: dict[str, Any]) -> str:
    ev = ", ".join(f"{e['file']}:{e['line']}" for e in g["evidence"])
    ev = ev or ("looked in " + ", ".join(g["looked_in"]) if g.get("looked_in") else "no line found")
    ev += f" (resolve with {g['resolve_with']})" if g.get("resolve_with") else ""
    return f"| {g['tag']} | {g['kind']} | {g['summary']} | {ev} |".replace("\n", " ")


def _learning_md(report: dict[str, Any]) -> str:
    """The sections for SG-16 and SG-17 facts: answered, re-asked, overlay candidates, value."""
    out = ""
    for key, title, col in (
        ("answered", "Answered by a decision", "answered_by"),
        ("re_asked", "Re-asked after a decision covered it", "covered_by"),
    ):
        rows = report.get(key) or []
        if rows:
            out += f"\n## {title}\n\nOwner questions a recorded decision or overlay rule covers; they block nothing.\n\n"
            out += "\n".join(
                ["| gap | question | by |", "|---|---|---|"]
                + [
                    f"| {r['gap'].get('id', '')} | {r['gap']['summary']} | {r[col] if col == 'answered_by' else ', '.join(r[col])} |".replace(
                        "\n", " "
                    )
                    for r in rows
                ]
            )
            out += "\n"
    lc = report.get("learning") or {}
    if lc:
        out += (
            "\n## Learning from answers\n\nPer cycle, never scored: "
            + ", ".join(
                f"{k.replace('_', ' ')} {lc[k]}"
                for k in (
                    "opened",
                    "answered",
                    "re_asked",
                    "bad_cites",
                    "missing_context",
                    "decisions",
                )
                if k in lc
            )
            + ".\n"
        )
        cands = lc.get("overlay_candidates") or []
        if cands:
            out += "\nOverlay candidates (areas answered often enough to become a rule):\n\n"
            out += "\n".join(
                ["| area | decisions |", "|---|---|"]
                + [f"| {c['area']} | {', '.join(c['decisions'])} |" for c in cands]
            )
            out += "\n"
    v = report.get("value") or {}
    if v.get("sellable_at_head") or v.get("next") or v.get("unvalued"):
        out += "\n## Value order\n\nFacts from the owner's slices and values; never scored.\n\n"
        out += "- Sellable at HEAD: " + (", ".join(v["sellable_at_head"]) or "none") + "\n"
        out += (
            "- If stopped today: "
            + (
                ", ".join(f"{r['feature']} (slice {r['slice']})" for r in v["if_stopped_today"])
                or "nothing"
            )
            + "\n"
        )
        n = v.get("next")
        out += (
            "- Cost to the next sellable feature: "
            + (f"{n['feature']}, remaining cost {n['remaining_cost']}" if n else "none")
            + "\n"
        )
        out += (
            "- Unvalued: "
            + (
                ", ".join(f"{u['feature']} ({'; '.join(u['missing'])})" for u in v["unvalued"])
                or "none"
            )
            + "\n"
        )
    return out


def render_gaps_md(report: dict[str, Any]) -> str:
    """Gaps in rank order (rank_key; unranked gaps keep tag, kind order); gaps that name a
    recorded decision (``reopens``) are listed in their own section, never dropped."""
    head_row = ["| tag | kind | gap | evidence |", "|---|---|---|---|"]
    ordered = sorted(report["gaps"], key=lambda g: (rank_key(g), g["tag"], g["kind"]))
    finds = [g for g in ordered if g.get("source") == "finding"]
    reopen = [g for g in ordered if g.get("reopens") and g not in finds]
    rest = [g for g in ordered if not g.get("reopens") and g not in finds]
    c = report["counts"]
    out = f"# Spec gaps\n\n{c['owner-decides']} for the owner to decide, {c['fixable']} fixable. Reported, not decided. Listed in rank order (impact on targets, severity, evidence); nothing is dropped.\n\n"
    out += "\n".join(head_row + [_gap_row(g) for g in rest]) + "\n"
    if reopen:
        out += "\n## Reopens\n\nGaps that name a recorded decision. They are the owner's to keep or reopen; no tool accepts or rejects them.\n\n"
        out += "\n".join(
            ["| tag | kind | gap | evidence | decision |", "|---|---|---|---|---|"]
            + [_gap_row(g)[:-1] + f" {g['reopens']} |" for g in reopen]
        )
        out += "\n"
    if finds:
        out += "\n## Findings\n\nReview findings, apart from spec gaps, in rank order. A finding becomes work only as a failing test or target.\n\n"
        out += "\n".join(
            ["| severity | proof | finding | where | state |", "|---|---|---|---|---|"]
            + [
                f"| {g.get('severity', '')} | {g.get('proof', '')} | {g['summary']} | {_where(g)} | {g.get('state', 'open')} |".replace(
                    "\n", " "
                )
                for g in finds
            ]
        )
        out += "\n"
    if report.get("rollup"):
        out += "\n## Features in the horizon\n\nItems met of total, derived when read; never stored.\n\n"
        out += "\n".join(
            ["| feature | met | total |", "|---|---|---|"]
            + [f"| {f} | {r['met']} | {r['total']} |" for f, r in report["rollup"].items()]
        )
        out += "\n"
    if report.get("facts"):
        out += "\n## Facts\n\nFor the owner to decide; they change no status.\n\n"
        out += "\n".join(
            ["| fact | detail |", "|---|---|"]
            + [
                f"| {f['kind']} | "
                + ", ".join(f"{k} {v}" for k, v in f.items() if k != "kind").replace("\n", " ")
                + " |"
                for f in report["facts"]
            ]
        )
        out += "\n"
    out += _learning_md(report)
    notes = report.get("sizing_notes") or []
    if notes:
        out += "\n## Sizing notes\n\nFacts for the owner to decide; they change no status.\n\n"
        out += (
            "\n".join(
                ["| item | note |", "|---|---|"] + [f"| {n['item']} | {n['note']} |" for n in notes]
            )
            + "\n"
        )
    return out


# ---------------------------------------------------------------- findings, ranking, review input

SEVERITIES = ("S1", "S2", "S3", "S4")
EVIDENCE_LEVELS = ("reproduced", "trigger", "theoretical")
RANK_KEY = "(impact ids desc, severity S1..S4, evidence reproduced..theoretical, id)"
REVIEW_DIFF_CAP = 20000  # characters of document diff handed to a re-review


def rank_key(f: dict[str, Any]) -> tuple[Any, ...]:
    """The fixed order of findings and gaps: impact on targets first (more distinct impact
    ids first), then severity (S1 first), then evidence (reproduced first), then id. A missing
    or unknown severity or evidence ranks after the known ones. Order only: nothing is dropped.
    A gap carries its evidence level as ``proof`` (its ``evidence`` is file:line)."""
    imp = f.get("impact")
    n = len({str(i) for i in imp}) if isinstance(imp, list) else 0
    sev = f.get("severity")
    ev = f.get("evidence") if isinstance(f.get("evidence"), str) else f.get("proof")
    return (
        -n,
        SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES),
        EVIDENCE_LEVELS.index(ev) if ev in EVIDENCE_LEVELS else len(EVIDENCE_LEVELS),
        str(f.get("id", "")),
    )


def rank_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of ``items`` in rank order, each with its 1-based ``rank``; all of them."""
    return [{**f, "rank": n} for n, f in enumerate(sorted(items, key=rank_key), 1)]


def _head(cfg: Config) -> str | None:
    top = git_top(cfg.dir)
    return _git(top, "rev-parse", "HEAD") if top and _git_ok(top, "rev-parse", "HEAD") else None


def _gaps_doc(cfg: Config) -> dict[str, Any]:
    p = cfg.file("gaps")
    if p is None or not p.exists():
        return {"writer": "brick-harness gaps", "gaps": []}
    doc: dict[str, Any] = load_json(p, "gaps")
    return doc


def _committed_finding_ids(cfg: Config) -> set[str] | None:
    """Ids of findings in HEAD's gaps.json (the outbox); None outside a git repository."""
    top, gp = git_top(cfg.dir), cfg.file("gaps")
    if top is None or gp is None or not _git_ok(top, "rev-parse", "--verify", "-q", "HEAD"):
        return None
    try:
        doc = loads(_git(top, "show", f"HEAD:{_under(gp, top)}"))
    except (HarnessError, ValueError):
        return set()
    return {g["id"] for g in doc.get("gaps", []) if g.get("source") == "finding" and "id" in g}


def _write_gaps_doc(cfg: Config, doc: dict[str, Any]) -> list[str]:
    path, written = cfg.file("gaps"), []
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(path)
    written.append(_rel(cfg, path))
    md = cfg.file("gaps_md")
    if md:
        md.write_text(render_gaps_md(doc))
        written.append(_rel(cfg, md))
    return written


def _as_finding(g: dict[str, Any]) -> dict[str, Any]:
    """A finding as bh-rank prints it, from its gaps.json form (evidence level is ``proof``)."""
    f = {k: g[k] for k in ("id", "summary", "severity", "impact", "rule", "source") if k in g}
    return {**f, "evidence": g.get("proof"), "where": _where(g), "state": g.get("state", "open")}


def all_findings(cfg: Config) -> list[dict[str, Any]]:
    """Every finding recorded in gaps.json (``source`` is ``finding``), ranked, closed too."""
    return rank_findings(
        [_as_finding(g) for g in _gaps_doc(cfg)["gaps"] if g.get("source") == "finding"]
    )


def _finding_gap(raw: dict[str, Any]) -> dict[str, Any]:
    """The gaps.json form of a finding: a gap-shaped record kept apart by source ``finding``."""
    where = raw.get("where", "")
    m = re.fullmatch(r"(.+):(\d+)", where)
    g: dict[str, Any] = {
        "id": raw.get("id") or f"finding:{digest([raw.get('rule'), raw['summary']])[:8]}",
        "kind": raw.get("kind", "other"),
        "summary": raw["summary"],
        "tag": "fixable",
        "evidence": [{"file": m.group(1), "line": int(m.group(2))}] if m else [],
        "source": "finding",
        "state": raw.get("state", "open"),
    }
    for k in ("severity", "impact", "rule"):
        if k in raw:
            g[k] = raw[k]
    if "evidence" in raw:
        g["proof"] = raw["evidence"]
    return g


def add_findings(
    cfg: Config, added: list[dict[str, Any]], source: str = "finding", write: bool = False
) -> dict[str, Any]:
    """Record ``added`` findings in gaps.json (the one place findings live) by id: a repeat
    replaces, so a re-review can close one; every other entry stays. Input that fails the
    finding schema is an error and nothing is written. Writes only when ``write``."""
    if not isinstance(added, list):
        raise HarnessError("findings must be a JSON list")
    schema = load_schema("finding")
    errs: list[str] = []
    for i, f in enumerate(added):
        errs += validate(f, schema["$defs"]["finding"], schema, f"$[{i}]")
    if errs:
        raise HarnessError("findings fail the finding schema: " + "; ".join(errs[:10]))
    new = [_finding_gap(f) for f in added]
    written = []
    with harness_lock(cfg):
        doc = _gaps_doc(cfg)
        ids = {g["id"] for g in new}
        doc["gaps"] = [g for g in doc["gaps"] if g.get("id") not in ids] + new
        doc["counts"] = {
            t: sum(g["tag"] == t and g.get("source") != "finding" for g in doc["gaps"])
            for t in ("owner-decides", "fixable")
        }
        path = cfg.file("gaps")
        if write and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2) + "\n")
            written.append(_rel(cfg, path))
            md = cfg.file("gaps_md")
            if md:
                md.write_text(render_gaps_md(doc))
                written.append(_rel(cfg, md))
    found = [_as_finding(g) for g in doc["gaps"] if g.get("source") == "finding"]
    return {
        "findings": rank_findings(found),
        "key": RANK_KEY,
        "written": written,
        "dry_run": not write,
    }


def open_findings(cfg: Config) -> list[dict[str, Any]]:
    """Open findings, ranked: the ``finding`` entries of gaps.json plus the review gaps there
    (a review's gaps are its findings; a gap leaves the list when a re-review no longer
    reports it)."""
    out = [
        _as_finding(g)
        for g in _gaps_doc(cfg)["gaps"]
        if g.get("source") in ("finding", "review") and g.get("state", "open") == "open"
    ]
    return rank_findings(out)


def _where(g: dict[str, Any]) -> str:
    ev = g.get("evidence") or []
    return f"{ev[0]['file']}:{ev[0]['line']}" if ev else ""


def review_input(cfg: Config) -> dict[str, Any]:
    """What a re-review is given, and nothing else: the project documents' diff since the last
    review (``since`` null on a first review: then it reads them whole) and the open findings.
    The diff is capped at REVIEW_DIFF_CAP characters (``diff_truncated``)."""
    top = git_top(cfg.dir)
    since = _gaps_doc(cfg).get("reviewed_head")
    docs = sorted({p for k in PROJECT_KEYS for p in cfg.files(k) if p.exists()})
    changed: list[str] = []
    diff = ""
    if (
        top
        and since
        and _git_ok(top, "rev-parse", "--verify", "-q", f"{since}^{{commit}}")
        and docs
    ):
        spec = [_under(p, top) for p in docs if p.is_relative_to(top)]
        if spec:
            changed = _git(top, "diff", "--name-only", since, "--", *spec).splitlines()
            diff = _git(top, "diff", "--unified=2", since, "--", *spec) if changed else ""
    else:
        since = None
    return {
        "since": since,
        "head": _git(top, "rev-parse", "HEAD")
        if top and _git_ok(top, "rev-parse", "HEAD")
        else None,
        "changed": changed,
        "diff": diff[:REVIEW_DIFF_CAP],
        "diff_truncated": len(diff) > REVIEW_DIFF_CAP,
        "open": open_findings(cfg),
    }


# ---------------------------------------------------------------- target history (SG-04)

HISTORY_CAP = 50  # entries kept per item


def history_path(cfg: Config) -> Path | None:
    out = cfg.file("measure_out")
    return out / "history.json" if out is not None else None


def read_history(cfg: Config) -> list[dict[str, Any]]:
    """Per measurement at the item's current or candidate ref: ``seq`` (global order),
    ``item``, ``ref``, ``current``, ``status`` and ``targets`` ({"metric op value": met}).
    Lives in the ignored out/ directory; an unreadable file is an empty history."""
    p = history_path(cfg)
    try:
        doc = loads(p.read_text()) if p and p.exists() else {}
    except (OSError, ValueError):
        return []
    rows = doc.get("entries") if isinstance(doc, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def record_history(cfg: Config, results: dict[str, Any], current: bool = True) -> None:
    """Append one entry per result; a fact only, so a failure to record never fails the
    measurement."""
    p = history_path(cfg)
    if p is None:
        return
    try:
        rows = read_history(cfg)
        seq = max((r.get("seq", 0) for r in rows), default=0)
        for item, r in results.items():
            seq += 1
            rows.append(
                {
                    "seq": seq,
                    "item": item,
                    "ref": str(r.get("ref", "")),
                    "current": current,
                    "status": r.get("status"),
                    "targets": {
                        f"{c['metric']} {c['op']} {c['value']}": bool(c["met"])
                        for c in r.get("targets", [])
                    },
                }
            )
            mine = [x for x in rows if x["item"] == item]
            for old in mine[:-HISTORY_CAP]:
                rows.remove(old)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": rows}, indent=1) + "\n")
        tmp.replace(p)
    except (OSError, KeyError, TypeError, ValueError):
        return


def oscillating(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Targets that went met to unmet after another item's change, twice or more.

    Over the current (HEAD) measurements in order: a target of item A regressed when it was
    met in A's previous measurement and unmet in the next; the other items that went from
    not met to met between the two are the change that preceded it. A target with two such
    regressions is reported with A and those items named. A fact, never a status."""
    cur = sorted((r for r in rows if r.get("current")), key=lambda r: r.get("seq", 0))
    went_met: dict[str, list[int]] = {}  # item -> seqs at which it went from not met to met
    prev_ok: dict[str, bool] = {}
    for r in cur:
        ok = r.get("status") == "met"
        if ok and not prev_ok.get(r["item"], False):
            went_met.setdefault(r["item"], []).append(r["seq"])
        prev_ok[r["item"]] = ok
    last: dict[tuple[str, str], tuple[int, bool]] = {}
    hits: dict[tuple[str, str], list[set[str]]] = {}
    for r in cur:
        for k, met in (r.get("targets") or {}).items():
            key = (r["item"], k)
            if key in last and last[key][1] and not met:
                lo = last[key][0]
                by = {
                    b
                    for b, seqs in went_met.items()
                    if b != r["item"] and any(lo < s < r["seq"] for s in seqs)
                }
                if by:
                    hits.setdefault(key, []).append(by)
            last[key] = (r["seq"], bool(met))
    return [
        {
            "item": item,
            "target": k,
            "regressions": len(h),
            "changed_by": sorted(set().union(*h)),
        }
        for (item, k), h in sorted(hits.items())
        if len(h) >= 2
    ]


# ---------------------------------------------------------------- value order (SG-17)


def _cite_problem(cfg: Config, src: str | None) -> str | None:
    """Why a cited source does not resolve, or None. ``file:line`` must name an existing line;
    anything else is a tracker ref, resolved by its adapter and not here."""
    src = (src or "").strip()
    if not src:
        return "no source"
    m = re.fullmatch(r"(.+):(\d+)", src)
    if not m:
        return None
    p = (cfg.dir / m.group(1)).resolve()
    if not p.is_file() or not 1 <= int(m.group(2)) <= len(_lines(p)):
        return f"source {src} does not exist"
    return None


def load_features(cfg: Config, problems: list[str] | None = None) -> list[dict[str, Any]]:
    """The owner's features (``paths.feature_slices``, features.schema.json); none when the
    file is absent. A file that fails its schema is a problem and reads as empty."""
    p = cfg.file("feature_slices")
    if p is None or not p.exists():
        return []
    try:
        feats: list[dict[str, Any]] = load_json(p, "features")["features"]
        return feats
    except HarnessError as e:
        if problems is not None:
            problems.append(str(e))
        return []


def _closure(by_id: dict[str, Any], root: str) -> set[str]:
    seen: set[str] = set()
    todo = [root]
    while todo:  # walk the finite dependency graph
        i = todo.pop()
        if i in seen or i not in by_id:
            continue
        seen.add(i)
        todo += by_id[i].get("depends_on", [])
    return seen


def _value_plan(
    cfg: Config,
    bricks: list[dict[str, Any]],
    order: list[str],
    branches: set[str] | frozenset[str] = frozenset(),
    problems: list[str] | None = None,
) -> dict[str, Any]:
    """The work order and its facts from ``bricks`` (state rows: id, status, depends_on, ready,
    est_loc when present) in build ``order``: ``queue`` (items not met), ``held`` (item ->
    the earlier feature it waits for) and ``value`` (facts). See ``value_queue``."""
    by_id = {b["id"]: b for b in bricks}
    rank = {i: n for n, i in enumerate(order)}

    def at(i: str) -> tuple[int, str]:
        return (rank.get(i, len(rank)), i)

    def met(i: str) -> bool:
        return bool(by_id[i]["status"] == "met")

    rows: list[dict[str, Any]] = []
    unvalued: list[dict[str, Any]] = []
    sellable: list[dict[str, Any]] = []
    for f in load_features(cfg, problems):
        acc = f["acceptance"]
        if acc not in by_id:
            unvalued.append({"feature": f["id"], "missing": [f"acceptance item {acc} unknown"]})
            continue
        miss = [k for k in ("slice", "value") if f.get(k) is None]
        why = _cite_problem(cfg, f.get("source"))
        if why:
            miss.append(why)
        if miss:
            unvalued.append({"feature": f["id"], "missing": miss})
        if met(acc):
            sellable.append(f)
            continue
        closure = _closure(by_id, acc)
        unmet = sorted((i for i in closure if not met(i)), key=at)
        rows.append(
            {
                "id": f["id"],
                "acc": acc,
                "slice": f.get("slice"),
                "value": f.get("value"),
                "miss": miss,
                "unmet": unmet,
                "cost": sum(by_id[i].get("est_loc") or 1 for i in unmet),
                "started": any(by_id[i]["status"] not in ("unmeasured", "blocked") for i in closure)
                or bool(closure & set(branches)),
            }
        )
    valued = sorted(
        (r for r in rows if not r["miss"]),
        key=lambda r: (r["slice"], -Fraction(r["value"]) / r["cost"], at(r["acc"]), r["id"]),
    )
    ordered = valued + sorted(
        (r for r in rows if r["miss"]), key=lambda r: at(r["acc"]) + (r["id"],)
    )
    queue: list[str] = []
    owner: dict[str, str] = {}
    for r in ordered:
        for i in r["unmet"]:
            if i not in owner:
                owner[i] = r["id"]
                queue.append(i)
    placed = [i for i in order if i in by_id]
    rest = placed + sorted(i for i in by_id if i not in rank)
    queue += [i for i in rest if i not in owner and not met(i)]
    held: dict[str, str] = {}  # finish before start
    holder: str | None = None
    for r in ordered:
        own = [i for i in r["unmet"] if owner[i] == r["id"]]
        if holder:
            held.update({i: holder for i in own})
        elif r["started"] and any(by_id[i].get("ready") for i in own):
            holder = r["id"]
    sellable.sort(key=lambda f: (f.get("slice") or 10**9, f["id"]))
    value = {
        "sellable_at_head": [f["id"] for f in sellable],
        "if_stopped_today": [{"feature": f["id"], "slice": f.get("slice")} for f in sellable],
        "next": {"feature": ordered[0]["id"], "remaining_cost": ordered[0]["cost"]}
        if ordered
        else None,
        "unvalued": unvalued,
    }
    return {"queue": queue, "held": held, "value": value}


def value_queue(cfg: Config, state: dict[str, Any]) -> list[str]:
    """The order work is done in: ids of the items not met, most valuable first (pure; reads
    only ``features.json`` beside the ``state()`` dict it is given).

    Among features whose acceptance item is not met, the earliest slice, then the highest
    value divided by remaining cost (sum of ``est_loc``, 1 when absent, over the unmet items
    of the feature's dependency closure), ties by build order; each feature's unmet closure
    in dependency order, then the next feature; features without slice, value or a resolving
    source follow; items no feature names follow in build order. Without ``features.json`` it
    is the build order. Uses ``state["bricks"]`` (id, status, depends_on, est_loc) and
    ``state["waves"]``; page it with ``pending_page``."""
    order = [i for w in state["waves"] for i in w]
    return list(_value_plan(cfg, state["bricks"], order)["queue"])


# ---------------------------------------------------------------- learning from answers (SG-16)

RULE_ID = re.compile(r"\b[A-Z][A-Z0-9]*-[A-Za-z0-9][A-Za-z0-9.]*\b")


def load_decisions(cfg: Config, problems: list[str] | None = None) -> list[dict[str, Any]]:
    """Decision records D-n (``paths.answers``, decision.schema.json) in id order; a record
    that fails its schema is a problem and is left out."""
    d = cfg.file("answers")
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("D-*.json")) if d is not None and d.is_dir() else []:
        try:
            out.append(load_json(p, "decision"))
        except HarnessError as e:
            if problems is not None:
                problems.append(str(e))
    return sorted(out, key=lambda x: int(x["id"][2:]))


def overlay_rules(cfg: Config) -> list[dict[str, Any]]:
    """Rules the project overlay holds that name the areas they cover: a line with a rule id
    before ``covers:`` and the areas, comma separated, after it."""
    p = _standard_layers(cfg).get("overlay")
    out: list[dict[str, Any]] = []
    for line in _lines(p) if p is not None and p.is_file() else []:
        head, sep, tail = line.partition("covers:")
        m = RULE_ID.search(head)
        if sep and m:
            areas = [a.strip(" |*`").rstrip(".") for a in re.split(r"[,;]", tail)]
            out.append({"id": m.group(0), "areas": [a for a in areas if a]})
    return out


def _area_hit(area: str, g: dict[str, Any]) -> bool:
    area = area.rstrip("/")
    files = [e["file"] for e in g.get("evidence", [])]
    return area == g.get("area") or any(f == area or f.startswith(area + "/") for f in files)


def _covering(
    decs: list[dict[str, Any]], rules: list[dict[str, Any]], g: dict[str, Any]
) -> list[str]:
    """Ids of the decisions (kind and area) and overlay rules (area) that cover gap ``g``."""
    return [
        d["id"]
        for d in decs
        if g.get("kind") in d["kinds"] and any(_area_hit(a, g) for a in d["areas"])
    ] + [r["id"] for r in rules if any(_area_hit(a, g) for a in r["areas"])]


def _is_question(g: dict[str, Any]) -> bool:
    return g.get("tag") == "owner-decides" and g.get("source") != "finding"


def apply_learning(
    gaps: list[dict[str, Any]], decs: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split owner questions by what the owner already answered: ``(kept, learn)``.

    A gap citing ``answered_by`` a decision or overlay rule that exists and covers its kind
    and area is listed in ``learn["answered"]``; a cite that is missing or does not cover is
    the fact bad-cite and the gap stays in ``kept`` as it was; a covered gap that cites
    nothing is listed in ``learn["re_asked"]`` with the covering ids. Answered and re-asked
    gaps are not in ``kept``, so they block nothing."""
    dates = {d["id"]: d["date"] for d in decs}
    known = set(dates) | {r["id"] for r in rules}
    kept: list[dict[str, Any]] = []
    learn: dict[str, list[dict[str, Any]]] = {"answered": [], "re_asked": [], "bad_cites": []}
    for g in gaps:
        if not _is_question(g):
            kept.append(g)
            continue
        cover = _covering(decs, rules, g)
        cite = g.get("answered_by")
        if cite and cite in cover:
            learn["answered"].append({"gap": g, "answered_by": cite, "date": dates.get(cite)})
            continue
        if cite:
            why = "does not cover the gap's kind and area" if cite in known else "no such record"
            learn["bad_cites"].append(
                {"kind": "bad-cite", "gap": g.get("id"), "answered_by": cite, "why": why}
            )
        elif cover:
            learn["re_asked"].append({"gap": g, "covered_by": cover})
            continue
        kept.append(g)
    return kept, learn


def overlay_candidates(
    cfg: Config, decs: list[dict[str, Any]], rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Areas with at least ``learning.overlay_after`` (default 3) decisions that the overlay
    holds no rule for: area, decision ids and answers, for the project's overlay build."""
    need = int(cfg.data.get("learning", {}).get("overlay_after", 3))
    held = {a.rstrip("/") for r in rules for a in r["areas"]}
    by: dict[str, list[dict[str, Any]]] = {}
    for d in decs:
        for a in d["areas"]:
            by.setdefault(a, []).append(d)
    return [
        {
            "area": a,
            "decisions": [d["id"] for d in ds],
            "answers": [d["answer"][:300] for d in ds],
        }
        for a, ds in sorted(by.items())
        if len(ds) >= need and a.rstrip("/") not in held
    ]


def learning_part(
    cfg: Config,
    decs: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    after: str | None = None,
) -> dict[str, Any]:
    """What gaps and plan agents read: decision record paths in id order (at most
    ``limits.decision_items``, with ``more`` and the paging command) and the overlay
    candidates (capped the same way)."""
    cap = cfg.limit("decision_items")
    if after is not None and after not in {d["id"] for d in decs}:
        raise HarnessError(f"unknown decision {after} to page after")
    rows = decs[[d["id"] for d in decs].index(after) + 1 :] if after is not None else decs
    page = rows[:cap]
    base = cfg.file("answers")
    cands = overlay_candidates(cfg, decs, rules)
    return {
        "decisions": [
            {"id": d["id"], "path": _rel(cfg, base / f"{d['id']}.json")}
            for d in page
            if base is not None
        ],
        "more": len(rows) - len(page),
        "next": page[-1]["id"] if len(rows) > len(page) else None,
        "paging": "bh-state --part learning --after D-n",
        "overlay_candidates": cands[:cap],
        "overlay_candidates_more": max(0, len(cands) - cap),
        "overlay": overlay_path(cfg),
    }


def learning_counts(
    cfg: Config,
    kept: list[dict[str, Any]],
    learn: dict[str, Any],
    decs: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per cycle: owner questions opened (answered, re-asked and still open together),
    answered (a valid cite), re-asked (covered by a decision that existed, cited nothing),
    bad cites, decisions and the date of the latest one; missing-context findings. Never scored."""
    answered, again = len(learn["answered"]), len(learn["re_asked"])
    return {
        "opened": sum(_is_question(g) for g in kept) + answered + again,
        "answered": answered,
        "re_asked": again,
        "bad_cites": len(learn["bad_cites"]),
        "decisions": len(decs),
        "latest_decision": max((d["date"] for d in decs), default=None),
        "missing_context": sum(
            1
            for g in (findings or [])
            if g.get("kind") == "missing-context" and g.get("state", "open") == "open"
        ),
        "overlay_candidates": overlay_candidates(cfg, decs, rules),
    }


def record_answer(
    cfg: Config,
    gap: str,
    answer: str,
    source: str,
    kinds: list[str],
    areas: list[str],
    question: str | None = None,
    date: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Make the owner's answer to gap ``gap`` (an id in gaps.json) a decision record D-n:
    ``{id, gap, question, answer, source, kinds, areas, date}``. ``source`` is where the
    owner's answer is stated (file:line, checked, or a tracker ref). The same gap and answer
    again returns the record that exists. Written (under the harness lock) only with
    ``write``; bh-commit commits it."""
    doc = _gaps_doc(cfg)
    listed = doc["gaps"] + [x["gap"] for x in doc.get("answered", []) + doc.get("re_asked", [])]
    found = next((g for g in listed if g.get("id") == gap), None)
    if found is None:
        raise HarnessError(f"gap {gap} is not in the gap report")
    why = _cite_problem(cfg, source)
    if why:
        raise HarnessError(f"answer {why}")
    bad = [k for k in kinds if k not in GAP_KINDS]
    if bad or not kinds or not areas:
        raise HarnessError(f"kinds must be gap kinds (got {bad or kinds}) and areas must be given")
    base = cfg.file("answers")
    assert base is not None
    rec = {
        "question": question or found["summary"],
        "answer": answer,
        "gap": gap,
        "source": source,
        "kinds": kinds,
        "areas": areas,
        "date": date or datetime.now(UTC).date().isoformat(),
    }
    with harness_lock(cfg):
        have = load_decisions(cfg)
        same = next((d for d in have if d["gap"] == gap and d["answer"] == answer), None)
        if same is not None:
            return {"decision": same, "created": False, "written": [], "dry_run": not write}
        nxt = max((int(d["id"][2:]) for d in have), default=0) + 1
        out = {"id": f"D-{nxt}", **rec}
        errs = validate(out, load_schema("decision"))
        if errs:
            raise HarnessError("decision fails its schema: " + "; ".join(errs[:5]))
        written = []
        if write:
            base.mkdir(parents=True, exist_ok=True)
            path = base / f"{out['id']}.json"
            with path.open("x") as f:  # create-only: an id is never reused
                f.write(json.dumps(out, indent=2) + "\n")
            written.append(_rel(cfg, path))
    return {"decision": out, "created": True, "written": written, "dry_run": not write}


# ---------------------------------------------------------------- work packet (SG-18)


def _show_at(top: Path | None, ref: str | None, rel: str) -> str | None:
    """File ``rel`` (project-root relative; may sit in a subdirectory of the repository)
    as it is in commit ``ref``, or None."""
    if top is None or not ref:
        return None
    p = subprocess.run(["git", "-C", str(top), "show", f"{ref}:{rel}"], capture_output=True)
    return p.stdout.decode(errors="replace") if p.returncode == 0 else None


def packet_context(cfg: Config) -> dict[str, Any]:
    """Everything a work packet shares between items, read once."""
    problems: list[str] = []
    bricks, targets, catalogue = _load_plan(cfg, problems)
    top = git_top(cfg.dir)
    return {
        "bricks": {b["id"]: b for b in bricks},
        "targets": targets,
        "catalogue": catalogue,
        "versions": lock_versions(cfg.files("lockfiles"), problems),
        "top": top,
        "plan_head": plan_head(cfg, top) if top is not None else None,
    }


def _passage(cfg: Config, ctx: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """One cited passage: its text at the plan commit (the working file when the plan is not
    committed), its sha256, and whether its lines differ at HEAD from the plan commit."""
    top, ph = ctx["top"], ctx["plan_head"]
    a, b = (int(x) for x in c["lines"].split("-"))
    full = (cfg.dir / c["path"]).resolve()
    git_rel = (
        full.relative_to(top).as_posix() if top is not None and full.is_relative_to(top) else None
    )

    def cut(text: str | None) -> str | None:
        ls = text.splitlines() if text is not None else []
        return "\n".join(ls[a - 1 : b]) if text is not None and 1 <= a <= b <= len(ls) else None

    planned = cut(_show_at(top, ph, git_rel)) if git_rel else None
    now = cut(_show_at(top, "HEAD", git_rel)) if git_rel else None
    text = planned
    if text is None:
        text = cut(full.read_text(errors="replace")) if full.is_file() else None
    problem = None if text is not None else f"{c['path']}:{c['lines']} does not exist"
    return {
        "path": c["path"],
        "lines": c["lines"],
        "text": text or "",
        "sha256": hashlib.sha256((text or "").encode()).hexdigest(),
        "problem": problem,
        "stale": planned is not None and now != planned,
    }


def packet_rules(cfg: Config, item: str, ctx: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """The rules a work packet carries for ``item``: ``[{id, text}]`` (SG-19). The item's own
    ``rules`` ids first, then judgment rules chosen by its tags and ranked by findings
    (``bhrules.packet_rules``), at most ``limits.packet_rules``. A rule the catalog has no row
    for takes the line that states it in the overlay or in a catalog given as a path."""
    import bhrules

    ctx = ctx or packet_context(cfg)
    b = ctx["bricks"].get(item)
    if b is None:
        raise HarnessError(f"unknown item {item}")
    cat = cfg.data.get("standards", {}).get("catalog", "")
    docs: list[Path] = []
    if cat and not cat.startswith("<") and "/" in cat:
        c = (cfg.dir / cat).resolve()
        docs += sorted(c.rglob("*.md")) if c.is_dir() else [c]
    docs += list(_standard_layers(cfg).values())
    lines = [ln for d in docs if d.is_file() for ln in _lines(d)]
    out = bhrules.packet_rules(cfg, b, list(ctx["bricks"].values()))
    for r in out:
        if not r["text"]:
            pat = _bounded(r["id"])
            hit = next((ln for ln in lines if pat.search(ln)), "")
            r["text"] = re.sub(r"\bcovers:.*$", "", pat.sub("", hit, count=1)).strip(" -*|:`")[:160]
    return out


def work_packet(cfg: Config, item: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """The work packet of ``item``, assembled from the plan's citations and never from
    anything an agent typed: ``{item, text, tokens, passages, stale}``. ``text`` holds the job
    and purpose, the contract, the targets, the test and bench commands, each cited passage by
    line range with its sha256, the contracts (never the code) of the items it depends on, its
    owned paths, the stack pins of its ecosystem and its rule ids. ``tokens`` is characters / 4.
    ``stale`` lists the passages whose lines changed since the plan commit, and the cited
    lines that do not exist."""
    import bhrules

    ctx = ctx or packet_context(cfg)
    b = ctx["bricks"].get(item)
    if b is None:
        raise HarnessError(f"unknown item {item}")
    top, ph = ctx["top"], ctx["plan_head"]

    def read(rel: str) -> str | None:
        full = (cfg.dir / rel).resolve()
        if top is not None and full.is_relative_to(top):
            got = _show_at(top, ph, full.relative_to(top).as_posix())
            if got is not None:
                return got
        return full.read_text(errors="replace") if full.is_file() else None

    def contract(i: str) -> str:
        rel = ctx["bricks"][i].get("contract")
        return (read(rel) or "(contract file missing)").rstrip() if rel else "(none)"

    out = [f"# Work packet: {item}", f"Plan commit: {ph or 'not committed'}", "", "## Job"]
    out.append(b["job"] + (f"\nPurpose: {b['purpose']}" if b.get("purpose") else ""))
    for k in ("hides", "interface"):
        if b.get(k):
            out.append(f"{k.capitalize()}: {b[k]}")
    out += ["", f"## Contract ({b.get('contract') or 'none'})", contract(item), "", "## Targets"]
    out += [
        f"- {t['metric']} {t['op']} {t['value']}"
        for t in bhrules.item_targets(cfg, ctx["targets"], item)
    ]
    out += ["", "## Commands"]
    for k, v in rendered_commands(cfg, b).items():
        out.append(f"- {k}: " + (v if isinstance(v, str) else v.get("run") or v.get("pending", "")))
    passages = [_passage(cfg, ctx, c) for c in b.get("context", [])]
    out += ["", "## Context (cited passages)"]
    for p in passages:
        out += [f"### {p['path']}:{p['lines']} sha256 {p['sha256']}", "~~~~", p["text"], "~~~~"]
    out += ["", "## Contracts of the items it depends on (not their code)"]
    for d in b.get("depends_on", []):
        if d in ctx["bricks"]:
            out += [f"### {d}", contract(d)]
    out += ["", "## Owned paths"] + [f"- {p}" for p in _own_paths(b)]
    eco = b.get("ecosystem")
    out += ["", f"## Stack pins ({eco or 'no ecosystem'})"]
    for e in ctx["catalogue"]:
        if e["ecosystem"] == eco:
            out.append(
                f"- {e['library']} {ctx['versions'].get(norm(e['library'])) or 'unpinned'} ({e['job']})"
            )
    out += ["", "## Rules"]
    out += [
        f"- {r['id']}" + (f": {r['text']}" if r["text"] else "")
        for r in packet_rules(cfg, item, ctx)
    ]
    text = "\n".join(out) + "\n"
    return {
        "item": item,
        "text": text,
        "tokens": -(-len(text) // 4),
        "passages": [{k: p[k] for k in ("path", "lines", "sha256")} for p in passages],
        "stale": [
            {
                "path": p["path"],
                "lines": p["lines"],
                "why": p["problem"] or "changed since the plan commit",
            }
            for p in passages
            if p["stale"] or p["problem"]
        ],
    }


def packet_report(cfg: Config, items: list[str]) -> dict[str, Any]:
    """Packet facts for ``items``: sizing notes for packets over ``sizing.packet_tokens``
    (default 1600), the stale-context facts, and the largest packet sizes (capped)."""
    limit = {**SIZING_DEFAULT, **cfg.data.get("sizing", {})}["packet_tokens"]
    ctx = packet_context(cfg)
    sizes: list[tuple[int, str]] = []
    notes: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for i in items:
        if i not in ctx["bricks"]:
            continue
        pk = work_packet(cfg, i, ctx)
        sizes.append((pk["tokens"], i))
        if pk["tokens"] > limit:
            notes.append(
                {
                    "item": i,
                    "note": f"work packet {pk['tokens']} tokens above sizing.packet_tokens {limit}: consider a split",
                }
            )
        facts += [{"kind": "stale-context", "item": i, **s} for s in pk["stale"]]
    sizes.sort(key=lambda x: (-x[0], x[1]))
    cap = cfg.limit("decision_items")
    return {
        "notes": notes,
        "facts": facts,
        "packets": {
            "tokens": {i: n for n, i in sizes[:cap]},
            "more": max(0, len(sizes) - cap),
        },
    }


# ---------------------------------------------------------------- sizing notes (SG-14)

SIZING_DEFAULT = {"min_loc": 150, "max_loc": 2000, "packet_tokens": 1600}


def _measured_loc(cfg: Config, top: Path | None, b: dict[str, Any]) -> int | None:
    """Lines in the tracked files under the item's own paths, or None without any."""
    own = _own_paths(b)
    if top is None or not own:
        return None
    spec = [_under(cfg.dir / p, top) for p in own]
    n = 0
    for f in _git(top, "ls-files", "--", *spec).splitlines():
        try:
            n += len((top / f).read_text().splitlines())
        except (OSError, UnicodeDecodeError):
            continue
    return n or None


def sizing_notes(
    cfg: Config, bricks: list[dict[str, Any]], board: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Facts about how items are sized, for the owner: est_loc or measured lines outside
    config ``sizing`` (min_loc 150, max_loc 2000; measured lines count against min_loc only for
    an item the scoreboard has met), a purpose that may join two jobs, one
    declared consumer, an OSS tool that already fits. Never a gap, never a status."""
    s = {**SIZING_DEFAULT, **cfg.data.get("sizing", {})}
    top = git_top(cfg.dir)
    notes = []
    for b in bricks:
        i = b["id"]
        est = b.get("est_loc")
        got = _measured_loc(cfg, top, b)
        built = ((board or {}).get("items", {}).get(i) or {}).get("status") == "met"
        for label, n in (("est_loc", est), ("measured lines", got)):
            if n is None:
                continue
            if n > s["max_loc"]:
                notes.append(
                    (
                        i,
                        f"{label} {n} above sizing.max_loc {s['max_loc']}: may be too large for one agent session",
                    )
                )
            elif n < s["min_loc"] and (label == "est_loc" or built):
                notes.append(
                    (
                        i,
                        f"{label} {n} below sizing.min_loc {s['min_loc']}: may be too small to justify a package",
                    )
                )
        purpose = b.get("purpose", "")
        if re.search(r"\band\b|;", purpose):
            notes.append((i, f"purpose may join two jobs: {purpose[:120]}"))
        if len(b.get("consumers", [])) == 1:
            notes.append((i, f"a single consumer ({b['consumers'][0]}): is a package justified?"))
        for o in b.get("oss_checked", []):
            if o.get("fits"):
                notes.append(
                    (i, f"OSS tool {o['tool']} {o['version']} fits the job: is code needed?")
                )
    return [{"item": i, "note": n} for i, n in notes]
