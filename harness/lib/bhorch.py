"""The harness orchestrator: a program that runs every mechanical step and starts an agent job
only for judgement work.

Mechanical steps (the builder's clone, git branches, state, measuring, merging, committing, gap
merging, tracker reconcile and admit, ordering) run here, through the ``bhcore`` and
``bhtracker`` Python API or the ``bh-measure`` CLI (one process per item, so measuring runs in
parallel). An agent job is started for exactly these kinds of work: ``gaps`` (read documents for
meaning), ``plan`` (derive items, targets, contracts), ``test_author`` and ``regression_row``
(acceptance rows), ``harvest_find`` (duplicate helpers) and ``review`` (a feature that became
sellable). The one builder launch is ``bhpacket.launch_builder`` (a clone and its own settings,
``bhbuilder``), never an agent job here. Nothing else ever reaches a model.

A job is the host's own CLI, headless::

    claude -p --json-schema <schema> --output-format json
        --max-budget-usd <usd> --no-session-persistence --permission-mode dontAsk
        --allowedTools <the agent file's tools> --add-dir <jobs dir> <plugin root> <auth flags>
        (login: --plugin-dir <plugin> --agent agent-compliance:<agent>;
         bare: --agents <the agent file as JSON> --agent <agent>)

The prompt is a short instruction plus file PATHS, written to the CLI's stdin (``--allowedTools``
and ``--add-dir`` take lists, so a positional prompt would be swallowed); the state a job needs
is a file under ``<measure_out>/jobs/`` that the job reads itself. Model, effort and tools come
from the plugin's ``agents/<agent>.md`` frontmatter (the project config may override model and
effort per phase); the job's rules live in the agent file, stable text first, so jobs of one
kind share a prefix.

Auth mode is chosen mechanically, never asked: ``ANTHROPIC_API_KEY`` set or an ``apiKeyHelper``
in a settings file -> ``--bare`` (no hooks, memory, CLAUDE.md, other plugins, and no plugin
agents: the agent file is passed with ``--agents``); otherwise login mode, ``--setting-sources "" --strict-mcp-config
--disable-slash-commands --plugin-dir <plugin>``. A bare job that fails with an authentication
error, or whose agent the CLI does not find, is re-run once in login mode and the run switches to login mode; the run result names the
mode, each job's cost and tokens (from the CLI's JSON result).

Concurrency is ``asyncio.Semaphore(config.concurrency)``; each job has a deadline
(``asyncio.wait_for``; then terminate, then kill). Every wait is on a process exit; there is no
timer, poll or retry loop. A job result is saved as ``<measure_out>/jobs/<key>.json`` with
key = digest of (job, agent file, schema, input incl. the item's own tree key); a restart finds the
file and skips the job (the same way a measured result is keyed by tree sha).

OSS and stdlib checked before writing any helper (orchestrator vetting: stdlib asyncio driving
the host CLI, vetted 2026-11-20 at base catalog 1.3.0; claude-agent-sdk 0.2.186 wraps the same CLI and adds dependencies;
ComposioHQ agent-orchestrator, vibe-kanban, chipping-orchestrator, openai/symphony,
claude-squad, Snakemake, Prefect and DBOS rejected there). Also checked: ``json``,
``hashlib``, ``argparse``, ``shutil.which`` (stdlib), ``bhcore.validate`` (the harness's own schema
checker, reused for job outputs). The frontmatter reader is 12 lines: PyYAML is not a
dependency of the plugin and the agent files use flat ``key: value`` lines only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bhcore
import bhinfer
import bhintake
import bhpacket
import bhrules
import bhreview
import bhtracker
from bhcore import Config, HarnessError

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PLUGIN_ROOT / "agents"
AGENT_PREFIX = "agent-compliance:"  # the plugin name: plugin agents are namespaced by it
JOBS: dict[str, tuple[str, str]] = {  # job -> (agent, config phase for model/effort override)
    "gaps": ("harness-gaps-reader", "gaps"),
    "plan": ("harness-planner", "plan"),
    "harvest_find": ("harness-harvester", "harvest"),
    "review": ("harness-reviewer", "review"),
    "test_author": ("harness-test-author", "test_author"),
    "judge": ("harness-judge", "judge"),
    "regression_row": (
        "harness-reviewer",
        "test_author",
    ),  # a defect the reviewer found: the reviewer writes its row
}
ROLE = {  # job -> jobs[*].role
    "plan": "planner",
    "review": "reviewer",
    "test_author": "test_author",
    "judge": "judge",
    "regression_row": "reviewer",
}
READ_ONLY_BASH = ["Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(bh rule:*)"]  # bh rule: a rule in full (QBC-105 iii)
REMEASURE = ("unmeasured", "stale", "conflict", "met-uncommitted")  # no current measurement
DEFAULT_JOB_USD = 2.0
MISSED = ("red", "red_by_error")  # the measurer facts of a missed check
SETUP_COMMIT = (  # Conventional Commits 1.0.0: build = build system and dev dependencies
    "build(setup): add the files the harness setup wrote\n\n"
    "The owner-approved standard files (presets, hooks, CODEOWNERS) and the harness config; "
    "they are committed once, before any build, so a human's next commit starts from a clean tree."
)
FACTS_SHOWN = 20  # facts of one item kept in the run result; the run report has them all
DEFAULT_JOB_TIMEOUT_S = 1800
KILL_GRACE_S = 10
AUTH_RE = re.compile(
    r"invalid api key|authentication|unauthori[sz]ed|not logged in|please run /login|oauth token",
    re.I,
)
AGENT_MISSING_RE = re.compile(r"--agent .* not found\. Available agents", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


# ---------------------------------------------------------------- small mechanical helpers


def sha(obj: Any) -> str:
    """Digest of a JSON value (sorted keys), first 16 hex characters."""
    blob = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def git(top: Path, *a: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(["git", "-C", str(top), *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise HarnessError(f"git {' '.join(a)}: {p.stderr.strip() or p.stdout.strip()}")
    return p


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory and ``os.replace`` (the stdlib's atomic write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def agent_def(agent: str) -> dict[str, Any]:
    """Frontmatter of ``agents/<agent>.md``: model, effort, tools (list); flat ``key: value``."""
    text = (AGENTS_DIR / f"{agent}.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise HarnessError(f"agents/{agent}.md has no frontmatter")
    fm = dict(
        (k.strip(), v.strip()) for k, _, v in (ln.partition(":") for ln in m.group(1).splitlines())
    )
    return {
        "name": fm.get("name", agent),
        "description": fm.get("description", ""),
        "prompt": text[m.end() :].strip(),
        "model": fm.get("model"),
        "effort": fm.get("effort"),
        "tools": [t.strip() for t in fm.get("tools", "").split(",") if t.strip()],
        "digest": sha(text),
    }


def job_schema(job: str) -> dict[str, Any]:
    """The output schema of a job: ``$defs/<job>`` of jobs.schema.json with every ``$ref`` inlined
    (the CLI gets one self-contained schema) and the finding schema merged in."""
    doc = json.loads((bhcore.SCHEMA_DIR / "jobs.schema.json").read_text())
    defs = {
        **doc["$defs"],
        "finding": bhcore.load_schema("finding")["$defs"]["finding"],
        "criterion": bhcore.load_schema("packet")["$defs"]["criterion"],  # the packet's one definition
    }

    def target(ref: str) -> Any:
        """A local ``#/$defs/x`` or another harness schema's ``name.schema.json#/json/pointer``."""
        file, _, pointer = ref.partition("#")
        if not file:
            return defs[pointer.rsplit("/", 1)[-1]]
        node: Any = bhcore.load_schema(file.removesuffix(".schema.json"))
        for part in filter(None, pointer.split("/")):
            node = node[part]
        return node

    def inline(n: Any) -> Any:
        if isinstance(n, dict):
            if "$ref" in n:
                return inline(target(n["$ref"]))
            return {k: inline(v) for k, v in n.items() if k != "description"}
        if isinstance(n, list):
            return [inline(v) for v in n]
        return n

    return inline(defs[job])  # type: ignore[no-any-return]


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def auth_mode(root: Path) -> tuple[str, str | None]:
    """``("bare", helper command or None)`` when ``ANTHROPIC_API_KEY`` is set or a settings file
    configures an ``apiKeyHelper``; else ``("login", None)``. Bare mode reads no settings, so a
    helper is handed to the CLI as ``--settings '{"apiKeyHelper": ...}'``: that one key only."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "bare", None
    for f in (
        claude_config_dir() / "settings.json",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ):
        try:
            helper = json.loads(f.read_text()).get("apiKeyHelper")
            if helper:
                return "bare", str(helper)
        except (OSError, ValueError, AttributeError):
            continue
    return "login", None


def agents_json(agent: str) -> str:
    """``--agents`` value defining one agent from ``agents/<agent>.md``: ``{name: {description,
    prompt (the body), tools, model, effort}}`` (the shape of the Claude Code subagent
    definition; ``claude --help`` says ``--agents <json-or-file>``, and a run of 2.1.329 accepted
    it with ``--agent <name>``). Bare mode loads no plugin agents, so the definition travels in
    argv; the model and effort frontmatter lines are passed when set."""
    ad = agent_def(agent)
    d: dict[str, Any] = {"description": ad["description"], "prompt": ad["prompt"]}
    d["tools"] = ad["tools"]
    for k in ("model", "effort"):
        if ad[k]:
            d[k] = ad[k]
    return json.dumps({agent: d}, separators=(",", ":"))


def mode_flags(mode: str, helper: str | None, agent: str | None = None) -> list[str]:
    """Auth-mode flags and the flags that select the agent. Login mode loads the plugin and names
    the agent ``agent-compliance:<agent>``; bare mode loads no plugin agents (the CLI answers
    ``--agent ... not found. Available agents: ...``), so it passes the definition with
    ``--agents`` and names the agent unprefixed."""
    if mode == "bare":
        settings = ["--settings", json.dumps({"apiKeyHelper": helper})] if helper else []
        sel = ["--agents", agents_json(agent), "--agent", agent] if agent else []
        return ["--bare", *sel, *settings]
    sel = ["--agent", AGENT_PREFIX + agent] if agent else []
    return [
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--plugin-dir",
        str(PLUGIN_ROOT),
        *sel,
    ]


def parse_cli_result(stdout: str) -> dict[str, Any] | None:
    """The ``result`` object of ``--output-format json`` (an object, or a list of messages)."""
    try:
        doc = json.loads(stdout)
    except ValueError:
        return None
    if isinstance(doc, list):
        doc = next(
            (m for m in reversed(doc) if isinstance(m, dict) and m.get("type") == "result"), None
        )
    return doc if isinstance(doc, dict) else None


def job_key(job: str, core: dict[str, Any]) -> str:
    """Result key of a job: digest of the job, its agent file, its schema and its input core."""
    return sha([job, agent_def(JOBS[job][0])["digest"], job_schema(job), core])


def tokens_of(usage: dict[str, Any] | None) -> dict[str, int]:
    u = usage or {}
    return {
        "input": int(u.get("input_tokens") or 0),
        "output": int(u.get("output_tokens") or 0),
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
        "cache_write": int(u.get("cache_creation_input_tokens") or 0),
    }


def fingerprint(cfg: Config) -> str:
    """Digest of every measured number on the scoreboard (item, metric, actual, met), without
    refs or times: two equal fingerprints mean a round moved no measured number (W6)."""
    board, _ = bhcore.read_board(cfg.file("scoreboard"))  # type: ignore[arg-type]
    rows = []
    for part in ("items", "candidates"):
        for item, r in sorted(board.get(part, {}).items()):
            rows.append(
                [part, item, r.get("status")]
                + [[t.get("metric"), t.get("actual"), t.get("met")] for t in r.get("targets", [])]
            )
    return sha(rows)


# ---------------------------------------------------------------- the runner


def setup_presets(root: Path, approved: bool, owners: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """The linter presets as a setup write (QBC-61 C + D): approved, ``bhpresets.apply`` writes
    them into the project's pyproject and .pre-commit-config.yaml and records the owner answers
    in CODEOWNERS; else the files it would write while a stack's preset hooks are missing. Either
    way, owners named only after their package folder are one question, asked while CODEOWNERS lacks them."""
    import bhpresets
    from ruamel.yaml import YAML

    cfg = root / ".pre-commit-config.yaml"
    doc = YAML(typ="safe").load(cfg.read_text()) if cfg.is_file() else None
    have = {h.get("id") for r in (doc or {}).get("repos", []) for h in r.get("hooks") or []}
    out: dict[str, Any] = {}
    if approved:
        out = {"report": bhpresets.apply(root, owners)}
    elif owners:
        for stack in bhpresets.stacks(root)[:1]:  # an answer is the standard file, written as given
            for pattern, who in owners:
                bhpresets.record_owner(root, bhpresets.presets()[stack], pattern, who)
    missing = [s for s in bhpresets.stacks(root) if {h["id"] for h in bhpresets.presets()[s]["hooks"]} - have]
    if missing and not approved:
        out["pending"] = sorted({"pyproject.toml", ".pre-commit-config.yaml", "justfile"})  # the recipe runs the lint (QBC-16)
    folder = sorted(
        o
        for s in bhpresets.stacks(root)
        for o, v in bhpresets.owner_map(root, bhpresets.presets()[s]).items()
        if v["source"] == "package folder"
    )
    if folder:
        out["question"] = {
            "id": "Q-owners",
            "kind": "owner-unknown",
            "summary": f"who owns {', '.join(folder)}? Each is named only after its package folder; "
            "answer with `bh run --owner PATTERN=OWNER` (recorded in CODEOWNERS)",
            "evidence": "CODEOWNERS",
        }
    return out


class Orchestrator:
    """One run of one or more phases over a project (``cfg``)."""

    def __init__(self, cfg: Config, dry: bool = False) -> None:
        self.cfg, self.dry = cfg, dry
        self.top = bhcore.git_top(cfg.dir)
        if self.top is None:
            raise HarnessError("not a git repository")
        self.out = cfg.file("measure_out")
        assert self.out is not None
        self.jobs_dir = self.out / "jobs"
        self.claude = shutil.which("claude")
        if self.claude is None and not dry:
            raise HarnessError("the claude CLI is not on PATH")
        self.n = int(cfg.data.get("concurrency", 2))
        self.sem = asyncio.Semaphore(self.n)
        self.free_slots = list(range(self.n))
        self.mode, self.helper = auth_mode(cfg.dir)
        self.mode_start = self.mode
        self.fallbacks = 0
        self.records: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.spent = {"cost_usd": 0.0, "tokens": 0}
        self.facts: list[dict[str, Any]] = []  # every fact of this run's items, for the run report
        self.open_reviews: dict[str, tuple[dict[str, Any], str]] = {}  # item -> (SARIF log, sha) of changes requested
        self.outs: dict[str, str] = {}  # each item's last measurement output dir (result items[*].out)

    # ------------------------------------------------------------ files and state

    def rel(self, p: Path | str) -> str:
        return bhcore._rel(self.cfg, Path(p))

    def state(self) -> dict[str, Any]:
        return bhcore.state(self.cfg)

    def files_view(self, s: dict[str, Any]) -> dict[str, Any]:
        return {
            k: {x: v[x] for x in ("rel", "section", "exists", "create") if x in v}
            for k, v in s["files"].items()
        }

    def commit(self, name: str) -> dict[str, Any]:
        if self.dry:
            return {"committed": False, "dry_run": True}
        try:
            return bhcore.commit_harness(self.cfg, f"brick-harness: {name}")
        except HarnessError as e:
            self.errors.append(f"commit {name}: {e}")
            return {"committed": False, "error": str(e)}

    def write_gaps(
        self, found: list[dict[str, Any]], source: str, unmet: list[str] | None = None
    ) -> dict[str, Any]:
        """``merge_gaps``: merge findings (unresolvable evidence is rejected), write the report."""
        cfg = self.cfg
        try:
            return bhcore.merge_gaps(
                cfg,
                found,
                source,
                not self.dry,
                unmet or [],
                bhtracker.show_resolver(cfg),
                lambda st, bricks: bhtracker.gap_facts(cfg, st, bricks),
                bhtracker.parent_is_feature(cfg),
            )
        except (HarnessError, OSError, ValueError, KeyError, TypeError) as e:
            self.errors.append(f"gaps {source}: {e}")
            return {"error": str(e), "gaps": []}

    def tracker(self, tool: str) -> dict[str, Any]:
        fn = bhtracker.reconcile if tool == "reconcile" else bhtracker.admit
        try:
            return fn(self.cfg, not self.dry)  # type: ignore[no-any-return]
        except (HarnessError, OSError, ValueError, KeyError, TypeError) as e:
            self.errors.append(f"{tool}: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------ one agent job

    def job_usd(self, phase: str) -> float:
        v = self.cfg.data.get("budgets", {}).get("job_usd", DEFAULT_JOB_USD)
        if isinstance(v, dict):
            v = v.get(phase, v.get("default", DEFAULT_JOB_USD))
        return float(v)

    def argv(self, job: str, schema: dict[str, Any], mode: str) -> list[str]:
        agent, phase = JOBS[job]
        ad = agent_def(agent)
        tools = ad["tools"]
        if job == "review":  # read only: git's read-only commands instead of every command
            tools = [t for t in tools if t != "Bash"] + READ_ONLY_BASH
        dirs = [self.jobs_dir, PLUGIN_ROOT]
        args = [
            self.claude or "claude",
            "-p",
            "--json-schema",
            json.dumps(schema, separators=(",", ":")),
            "--output-format",
            "json",
            "--max-budget-usd",
            str(self.job_usd(phase)),
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(tools),
            "--add-dir",
            *[str(d) for d in dirs],
        ]
        model = self.cfg.data.get("models", {}).get(phase)
        effort = self.cfg.data.get("efforts", {}).get(phase)
        args += (["--model", model] if model else []) + (["--effort", effort] if effort else [])
        return args + mode_flags(mode, self.helper, agent)

    async def _exec(
        self, argv: list[str], prompt: str, cwd: Path, deadline: float
    ) -> tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        except OSError as e:
            return 127, "", f"cannot start {argv[0]}: {e}"
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), deadline)
        except TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), KILL_GRACE_S)
            except TimeoutError:
                proc.kill()
                await proc.wait()
            return 124, "", f"deadline of {deadline:.0f}s exceeded"
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def job(
        self,
        job: str,
        label: str,
        core: dict[str, Any],
        extra: dict[str, Any],
        instruction: str,
        cwd: Path | None = None,
        locked: bool = False,
    ) -> dict[str, Any]:
        """Run one agent job. ``core`` is what the result key and the input file hold; ``extra``
        (slot-dependent values) goes into the input file only. Returns the job record, with
        ``ok`` and ``output`` (the schema-checked structured output). ``locked``: the caller
        already holds a concurrency slot."""
        agent = JOBS[job][0]
        schema = job_schema(job)
        key = job_key(job, core)
        done = self.jobs_dir / f"{key}.json"
        rec: dict[str, Any] = {"job": job, "label": label, "agent": agent, "key": key}
        if job in ROLE:
            rec.update(kind="agent", role=ROLE[job], item=label.partition(":")[0])
        if done.exists():  # a restart: the job finished before
            saved = json.loads(done.read_text())
            self.records.append({**saved["record"], "skipped": True})
            return {**saved["record"], "skipped": True, "output": saved["output"], "ok": True}
        inp = self.jobs_dir / f"{key}.input.json"
        if self.dry:
            rec.update(dry_run=True, ok=False, input=self.rel(inp), mode=self.mode)
            self.records.append(rec)
            return rec
        write_atomic(inp, json.dumps({**core, **extra}, indent=2, sort_keys=True) + "\n")
        prompt = (
            f'Job: {job}. Follow the section "Job: {job.replace("_", " ")}" of your instructions.\n'
            f"{instruction}\nInput file (read it first; it names every other path): {inp}\n"
            "Answer with the JSON object of your schema only."
        )
        timeout = float(
            self.cfg.data.get("budgets", {}).get("job_timeout_s", DEFAULT_JOB_TIMEOUT_S)
        )
        rec["started_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        if locked:
            res = await self._run_cli(job, schema, prompt, cwd or self.cfg.dir, timeout)
        else:
            async with self.sem:
                res = await self._run_cli(job, schema, prompt, cwd or self.cfg.dir, timeout)
        rec.update(res["record"])
        rec["ended_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        if res["ok"]:
            self.keep(rec, res["output"])
        else:
            self.records.append(rec)
            write_atomic(self.jobs_dir / f"{key}.error.json", json.dumps(rec, indent=2) + "\n")
            self.errors.append(f"job {label}: {rec.get('error')}")
        return {**rec, "output": res.get("output"), "ok": res["ok"]}

    async def _attempt(
        self, job: str, schema: dict[str, Any], prompt: str, cwd: Path, timeout: float, mode: str
    ) -> dict[str, Any]:
        t0 = time.monotonic()
        code, out, err = await self._exec(self.argv(job, schema, mode), prompt, cwd, timeout)
        r = parse_cli_result(out)
        ok, error, output = self._judge(code, out, err, r, schema)
        rec: dict[str, Any] = {
            "mode": mode,
            "ok": ok,
            "cost_usd": float((r or {}).get("total_cost_usd") or 0),
            "tokens": tokens_of((r or {}).get("usage")),
            "duration_ms": int((r or {}).get("duration_ms") or (time.monotonic() - t0) * 1000),
            "turns": (r or {}).get("num_turns"),
            "subtype": (r or {}).get("subtype"),
            **({"error": error} if error else {}),
        }
        self.spent["cost_usd"] += rec["cost_usd"]
        self.spent["tokens"] += sum(rec["tokens"].values())
        return {
            "ok": ok,
            "output": output,
            "record": rec,
            # an authentication failure or a missing agent costs nothing: a job that spent money
            # failed on its work
            "fallback_reason": (
                None
                if ok or rec["cost_usd"]
                else "auth"
                if AUTH_RE.search(f"{error}\n{err}")
                else "agent_not_found"
                if AGENT_MISSING_RE.search(f"{error}\n{err}")
                else None
            ),
        }

    async def _run_cli(
        self, job: str, schema: dict[str, Any], prompt: str, cwd: Path, timeout: float
    ) -> dict[str, Any]:
        """One attempt in the run's auth mode; a bare attempt that fails to authenticate, or whose
        agent the host does not find (``not found. Available agents``), is re-run once in login
        mode, and every later job goes straight to login mode."""
        res = await self._attempt(job, schema, prompt, cwd, timeout, self.mode)
        if res["fallback_reason"] and self.mode == "bare":
            self.mode, self.fallbacks = "login", self.fallbacks + 1
            first, why = res["record"], res["fallback_reason"]
            res = await self._attempt(job, schema, prompt, cwd, timeout, "login")
            res["record"] = {
                **res["record"],
                "auth_fallback": True,
                "fallback_reason": why,
                "first_attempt_error": first.get("error"),
                "cost_usd": res["record"]["cost_usd"] + first["cost_usd"],
            }
        return res

    def _judge(
        self, code: int, out: str, err: str, r: dict[str, Any] | None, schema: dict[str, Any]
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        if r is None:
            return False, (err.strip() or out.strip() or f"exit {code}, no result")[:500], None
        sub = r.get("subtype")
        if r.get("is_error") or code != 0 or (sub and sub != "success"):
            text = str(r.get("result") or err or sub or f"exit {code}")
            more = "; ".join(str(e) for e in (r.get("errors") or []) if e)
            if more and more not in text:
                text = f"{text} ({more})" if r.get("result") else more
            return False, f"{sub or 'error'}: {text}"[:500], None
        output = r.get("structured_output")
        if output is None and isinstance(r.get("result"), str):
            try:
                output = json.loads(r["result"])
            except ValueError:
                output = None
        if not isinstance(output, dict):
            return False, "no structured output in the result", None
        errs = bhcore.schema_errors(output, schema)
        if errs:
            return False, "output fails its schema: " + "; ".join(errs[:5]), None
        return True, None, output

    # ------------------------------------------------------------ the order engine's state: jobs[*]

    def keep(self, rec: dict[str, Any], output: dict[str, Any] | None = None) -> None:
        """A finished job, agent or program step: in this run's ``jobs[*]`` and in the order
        engine's state, one file per job under the jobs dir (``<key or id>.json``), which every
        later run reads (``recorded``); an agent job's output is kept with it for its restart."""
        self.records.append(rec)
        if not self.dry:
            doc = {"record": rec, "output": output}
            write_atomic(self.jobs_dir / f"{rec.get('key') or rec['id']}.json", json.dumps(doc, indent=2) + "\n")

    def stamp(self, rec: dict[str, Any], **fields: Any) -> None:
        """Add facts known only after the job finished (the packet it wrote) to its kept record."""
        kept = next((r for r in self.records if r.get("key") == rec.get("key") and not r.get("skipped")), None)
        if kept is None or self.dry:
            return
        kept.update(fields)
        f = self.jobs_dir / f"{kept['key']}.json"
        doc = json.loads(f.read_text())
        write_atomic(f, json.dumps({**doc, "record": kept}, indent=2) + "\n")

    def recorded(self, item: str) -> list[dict[str, Any]]:
        """Every finished job of ``item`` the state holds, from this run and every earlier one."""
        out = []
        for f in sorted(self.jobs_dir.glob("*.json")):
            if f.name.endswith((".input.json", ".error.json")):
                continue
            try:
                rec = json.loads(f.read_text()).get("record") or {}
            except (OSError, ValueError, AttributeError):
                continue
            if rec.get("item") == item:
                out.append(rec)
        return out

    # ------------------------------------------------------------ measuring

    async def measure_one(self, item: str, ref: str) -> dict[str, Any]:
        """``bh-measure --item ITEM@REF --slot N`` as a process (parallel, one slot each)."""
        async with self.sem:
            slot = self.free_slots.pop()
            try:
                p = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(PLUGIN_ROOT / "bin" / "bh-measure"),
                    "--config",
                    str(self.cfg.path),
                    "--item",
                    f"{item}@{ref}",
                    "--slot",
                    str(slot),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                out, err = await p.communicate()
            finally:
                self.free_slots.append(slot)
        try:
            run = json.loads(out.decode())
        except ValueError:
            run = {"error": (err.decode() or "no output")[:300], "items": {}}
        it = (run.get("items") or {}).get(item)
        return {
            "item": item,
            "ref": ref,
            "status": it["status"] if it else "not measured",
            "errors": it.get("errors", []) if it else [run.get("error", "no result")],
        }

    async def measure_all(self, pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
        if self.dry:
            return [{"item": i, "ref": r, "status": "dry-run", "errors": []} for i, r in pairs]
        return list(await asyncio.gather(*(self.measure_one(i, r) for i, r in pairs)))

    async def phase_measure(self, refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Measure refs ({ref, items?}), merge what the scoreboard says is met, re-measure the
        merged items and their dependents at HEAD; with no refs measure what is ready at HEAD."""
        out: dict[str, Any] = {"measured": [], "merged": [], "conflicts": [], "remeasured": []}
        pairs: list[tuple[str, str]] = []
        for r in refs or []:
            for i in r.get("items") or bhcore.affected(self.cfg, r["ref"]):
                pairs.append((i, r["ref"]))
        out["measured"] = await self.measure_all(pairs)
        s = self.state()
        if s["unmerged"] and not self.dry:
            self.commit("scoreboard")
            try:
                m = bhcore.merge_unmerged(self.cfg)
            except HarnessError as e:
                self.errors.append(f"merge: {e}")
                return {**out, "error": str(e)}
            out["merged"], out["conflicts"] = m["merged"], m["conflicts"]
            out["remeasured"] = await self.measure_all([(i, "HEAD") for i in m["remeasure"]])
        if refs is None:  # standalone: every item with no current met result at HEAD
            # Chosen by the item's own record, not by build readiness: a commit made by hand (a
            # merge, a test edit) makes stale every item whose paths, dependencies' paths or
            # protected tests it changed, and each of them is measured at HEAD now, dependents
            # included, whatever a build queue would wait for (G2: same measurement for any author).
            done = {r["item"] for r in out["remeasured"]}
            s = self.state()
            out["remeasured"] += await self.measure_all(
                [(b["id"], "HEAD") for b in s["bricks"] if b["status"] in bhcore.READY_FROM and b["id"] not in done]
            )
        out["commit"] = self.commit("scoreboard")
        return out

    # ------------------------------------------------------------ phase: gaps

    def docs_digest(self) -> str:
        """Digest of the content of every project document a gaps or plan job reads (the
        project documents, the owner's feature data, the owner's answers, the overlay): the job
        key holds it, so an unchanged document set is not read again (W2, W3)."""
        h = hashlib.sha256()
        cfg = self.cfg
        paths = [
            p for k in (*bhcore.PROJECT_KEYS, "feature_slices", "answers") for p in cfg.files(k)
        ]
        ov = bhcore.overlay_file(cfg)
        for p in sorted([*paths, *([ov] if ov else [])]):
            for f in sorted(p.rglob("*")) if p.is_dir() else [p]:
                if f.is_file():
                    h.update(
                        str(f.relative_to(cfg.dir) if f.is_relative_to(cfg.dir) else f).encode()
                    )
                    h.update(f.read_bytes())
        return h.hexdigest()[:16]

    async def phase_gaps(self) -> dict[str, Any]:
        s = self.state()
        cfg = self.cfg
        core = {  # what the result key holds: the same documents give the same review
            "task": "gaps",
            "docs": self.docs_digest(),
            "standards": cfg.data.get("standards"),
            "design_checklist": cfg.data.get("checklist"),
            "not_applicable": cfg.data.get("na"),
            "rules": bhrules.project_rules(cfg),  # the selection, never the whole catalog (QBC-106)
        }
        extra = {
            "documents": self.files_view(s),
            "owner_answers_dir": (s["files"].get("answers") or {}).get("rel"),
            "overlay": s["overlay"],
            "mechanical_gaps": [g["summary"] for g in s["gaps"]],
            "review_input": bhcore.review_input(cfg),
        }
        j = await self.job(
            "gaps", "gaps review", core, extra, "Find spec gaps in the project's own documents."
        )
        if j.get("dry_run"):
            return {"dry_run": True, "job": j}
        if not j["ok"]:
            return {"error": j.get("error", "gaps job failed")}
        report = self.write_gaps(j["output"]["gaps"], "review")
        commit = self.commit("gaps")
        return {
            "counts": report.get("counts"),
            "received": report.get("received"),
            "accepted": report.get("accepted"),
            "rejected": report.get("rejected", []),
            "written": report.get("written", []),
            "commit": commit,
            **({"error": report["error"]} if report.get("error") else {}),
        }

    # ------------------------------------------------------------ phase: plan

    async def phase_plan(self) -> dict[str, Any]:
        cfg = self.cfg
        rec = self.tracker("reconcile")  # the tracker follows the measured status
        adm = self.tracker("admit")
        s = self.state()
        admitted = set(adm.get("admitted") or [])
        core = {  # re-planned only when a document, an answer or the tracker's admissions changed
            "task": "plan",
            "docs": self.docs_digest(),
            "standards": cfg.data.get("standards"),
            "sizing": cfg.data.get("sizing"),
            "admitted_from_tracker": [a for a in adm.get("admit", []) if a.get("id") in admitted],
        }
        extra = {
            "documents": self.files_view(s),
            "owner_answers_dir": (s["files"].get("answers") or {}).get("rel"),
            "items_not_met": [
                {"id": b["id"], "kind": b["kind"], "status": b["status"]}
                for b in s["bricks"]
                if b["status"] != "met"
            ],
            "features": s["features"],
            "open_gaps": [g["summary"] for g in s["gaps"] if g["kind"] != "unsettled-area"],
        }
        core["schemas"] = {  # the plan files' contract, by path: the planner writes them to it
            k: str(bhcore.SCHEMA_DIR / f"{k}.schema.json") for k in ("bricks", "targets")
        }
        for rnd in range(1, int(cfg.data.get("max_rounds", 3)) + 1):
            j = await self.job(
                "plan", f"derive plan:{rnd}", core, extra, "Derive the plan files from the documents."
            )
            if j.get("dry_run"):
                return {"dry_run": True, "job": j}
            if not j["ok"]:
                return {"error": j.get("error", "plan job failed"), "reconcile": rec, "admit": adm}
            bad = self.plan_file_errors()
            if not bad:
                break
            core["feedback"] = bad  # back to the planner: the files it wrote break their schema
        else:
            return {"error": "; ".join(bad)[:500], "reconcile": rec, "admit": adm}
        out = j["output"]
        report = self.write_gaps(out["not_derivable"], "plan")
        commit = self.commit("plan")
        s = self.state()
        return {
            **{k: out[k] for k in ("added_items", "added_targets", "added_contracts")},
            "gaps": report.get("counts"),
            "rejected": report.get("rejected", []),
            "overlay_candidates": s["learning"]["overlay_candidates"],
            "commit": commit,
            "admitted": sorted(admitted),
            **({"error": report["error"]} if report.get("error") else {}),
        }

    def plan_file_errors(self) -> list[str]:
        """What the plan files the planner wrote break in their schemas (bricks, targets)."""
        bad = []
        for k in ("bricks", "targets"):
            f = self.cfg.file(k)
            if f is not None and f.exists():
                try:
                    bhcore.load_json(f, k)
                except HarnessError as e:
                    bad.append(f"{self.rel(f)}: {e}"[:400])
        return bad

    # ------------------------------------------------------------ phase: build

    # ------------------------------------------------------------ phase: harvest

    async def phase_harvest(self) -> dict[str, Any]:
        s = self.state()
        merged = s["merged"]["items"]
        dups = s["catalogue"]["duplicates"]
        if len(merged) < 2 and not dups:
            return {
                "candidates": [],
                "skipped": "fewer than two items met since the last harvest and no duplicate catalogue jobs",
            }
        core = {
            "task": "harvest_find",
            "catalogue": (s["files"].get("catalogue") or {}).get("rel"),
            "catalogue_duplicates": dups,
            "bricks_file": (s["files"].get("bricks") or {}).get("rel"),
            "items_met_since_last_harvest": merged,
        }
        j = await self.job(
            "harvest_find",
            "find duplicates",
            core,
            {},
            "Find helper code that two or more items duplicate.",
        )
        if j.get("dry_run"):
            return {"dry_run": True, "job": j}
        if not j["ok"]:
            return {"error": j.get("error", "harvest find failed")}
        cands = j["output"]["candidates"]
        entries = s["catalogue"]["entries"]

        def settled(c: dict[str, Any]) -> bool:
            libs = {
                e["library"]
                for e in entries
                if e["job"] == c["job"] and e["ecosystem"] == c["ecosystem"]
            }
            return len(libs) == 1 and c.get("pick") in libs

        todo = [c for c in cands if settled(c)]
        open_ = [
            {
                "kind": "helper-without-library",
                "tag": "owner-decides",
                "evidence": c["evidence"],
                "summary": f"helper job {c['job']} ({c['ecosystem']}) is duplicated in "
                f"{', '.join(c['bricks'])} and the catalogue names no single library for it",
            }
            for c in cands
            if not settled(c)
        ]
        report = self.write_gaps(open_, "harvest")  # an empty list clears resolved findings
        self.commit("harvest gaps")
        self.tracker("reconcile")
        return {
            "candidates": cands,
            "reported": len(open_),
            "rejected": report.get("rejected", []),
            "settled": len(todo),
        }

    # ------------------------------------------------------------ the run

    # Standard-file writes setup offers (QBC-61 D): name -> writer(root, approved) returning
    # {"written", ...} when approved, else {"pending": [...]} naming what it would write.
    SETUP_WRITES: dict[str, Any] = {"forms": bhintake.install_forms, "presets": None}  # presets: setup_presets

    def phase_setup(
        self,
        approve: list[str] | None = None,
        owners: list[tuple[str, str]] | None = None,
        decline: list[str] | None = None,
    ) -> dict[str, Any]:
        """The one setup path, at the start of every run: what the project's standard files say
        (``bhinfer.infer``, each value a fact naming its file), the harness's own state ignored
        by git, then the standard-file writes the owner approved (``--approve``). What is not
        approved yet is one owner question for all of them together, asked again only while a
        write is still pending; the files written are the answer, so nothing is stored in a
        plugin file (QBC-60 to QBC-63). ``owners`` are the owner's answers about who owns a
        package (``--owner PATTERN=OWNER``), recorded in CODEOWNERS."""
        root = self.cfg.dir
        facts = bhinfer.infer(root)
        out: dict[str, Any] = {"facts": bhinfer.facts_lines(facts), "written": {}, "questions": bhinfer.questions(facts)}
        before = set(bhcore.dirty_paths(self.top))  # a human's uncommitted work: never committed here
        if not self.dry:
            bhcore.ignore_state(self.cfg)
        if decline and not self.dry:  # a "no" is kept like a "yes": asked again only when removed
            self.cfg.record_declined(decline)
        declined = {*self.cfg.data.get("setup", {}).get("declined", []), *(decline or [])}
        pending: list[str] = []
        for name, write in self.SETUP_WRITES.items():
            yes = approve is not None and (not approve or name in approve) and not self.dry
            if name in declined and not yes:
                out.setdefault("declined", []).append(name)
                continue
            r = setup_presets(root, yes, owners) if write is None else write(root, yes)
            if yes:
                out["written"][name] = r
            elif r.get("pending"):
                pending.append(f"{name} ({', '.join(r['pending'])})")
            if r.get("question"):
                out["questions"].append(r["question"])
        if pending:
            out["questions"].append(
                {
                    "id": "Q-setup",
                    "kind": "setup-approval",
                    "summary": "the harness would write into the project's own standard files: "
                    + "; ".join(pending)
                    + ". Ask the owner once; on yes rerun `bh run --approve` (or name the ones approved), "
                    "on no `bh run --decline NAME ...` (kept in .brick-harness/config.json setup.declined)",
                    "evidence": ", ".join(p.split(" (")[0] for p in pending),
                }
            )
        if not self.dry:  # what setup wrote is one commit before any build (Conventional Commits 1.0.0)
            wrote = sorted(set(bhcore.dirty_paths(self.top)) - before)
            if wrote:
                try:
                    out["commit"] = bhcore.commit_harness(self.cfg, SETUP_COMMIT, paths=wrote)
                except HarnessError as e:
                    self.errors.append(f"commit setup: {e}")
                    out["commit"] = {"committed": False, "error": str(e)}
        return out

    async def run(
        self,
        skip: list[str] | None = None,
        approve: list[str] | None = None,
        owners: list[tuple[str, str]] | None = None,
        decline: list[str] | None = None,
    ) -> dict[str, Any]:
        cfg, skip = self.cfg, skip or []
        res: dict[str, Any] = {
            "dry_run": self.dry,
            "setup": self.phase_setup(approve, owners, decline),
            "gaps": None,
            "plan": None,
            "rounds": [],
            "harvest": None,
            "stopped": None,
        }
        s0 = self.state()
        sellable0 = set(s0["value"]["sellable_at_head"])
        # Kanban pull (WIP limit, finish before start): the work queue is every packet that is not
        # met (R5: the planner's and orchestrator's output is packets, L2). Gaps and plan run only
        # when that queue is empty; their jobs are keyed by their inputs' digest, so unchanged
        # documents never re-plan. Each ready plan item then gets its packet from the program.
        if not self.queue(set()):
            if "gaps" not in skip:
                res["gaps"] = await self.phase_gaps()
            if "plan" not in skip:
                res["plan"] = await self.phase_plan()
        # Building goes one way only: each queued packet gets the test author's acceptance tests,
        # the builder's clone, the measurer and, when met, the merge.
        why: dict[str, str] = {}
        budgets = cfg.data.get("budgets", {})
        tried: set[str] = set()
        s = self.state()
        # the queue again after each item: a merge makes its dependents ready; every kind is built
        # one way; a re-tiered item runs once more at its new tier (a tier only rises, so at most once)
        for _ in range((len(s["bricks"]) + len(self.held())) * len(bhpacket.TIER_RANK)):
            item = next(iter(self.queue(tried)), None)
            if item is None:
                break
            tried.add(item)
            if self.over_budget(budgets):
                res["stopped"] = "budget"
                break
            if self.dry:  # the first agent job this item would start, listed and not launched
                await self.job("test_author", f"{item}:1", {"task": "test_author", "item": item}, {}, "")
                res["rounds"].append({"item": item, "dry_run": True})
                continue
            facts: list[dict[str, Any]] = []
            try:
                st = await self.packet_flow(item, facts)
            except HarnessError as e:
                st, facts = "unmet", [*facts, {"kind": "gap", "item": item, "detail": str(e)}]
            self.facts += facts  # all of them go to the run report; the result keeps the last ones
            res["rounds"].append(
                {"item": item, "status": st, "facts": facts[-FACTS_SHOWN:], **({"out": self.outs[item]} if item in self.outs else {})}
            )
            if st == "re-tiered":  # re-planned at the tier its diff showed (QBC-30): queued again
                tried.discard(item)
                continue
            if st != "met":
                why[item] = st
                break  # the next item is cut from a HEAD this one did not reach
            stale = [b["id"] for b in self.state()["bricks"] if b["status"] == "stale"]
            if stale:  # this item's plan commit changed what earlier items were measured with
                res.setdefault("remeasured", []).extend(await self.measure_all([(i, "HEAD") for i in stale]))
                self.commit("scoreboard")
        if not self.dry:
            self.tracker("reconcile")
        s = self.state()
        halted = self.over_budget(budgets)  # a spent budget starts no further job
        if halted:
            res["stopped"] = "budget" if res["stopped"] in (None, "budget") else res["stopped"]
            res["not_run_for_budget"] = ["harvest"]
        left = [b["id"] for b in s["bricks"] if b["status"] != "met"]
        reasons = {i: why[i] for i in left if i in why}
        if res["stopped"] == "budget":
            reasons.update({i: "budget" for i in s["ready"] + s["ready_system"]})
        cyc = self.write_gaps([], "cycle", [f"{i}:{r}" for i, r in reasons.items()])
        if not self.dry:
            self.commit("unmet items reported")
        s = self.state()
        if (
            "harvest" not in skip
            and not (self.dry or halted)
            and any(b["status"] == "met" for b in s["bricks"])
        ):
            h = await self.phase_harvest()
            res["harvest"] = h
            self.tracker("reconcile")
        if not self.dry:  # the run report: one line per fact of the run, as every program step writes it
            lines = [f"{f['kind']}: {f.get('item', '')}: {f.get('detail', '')}\n" for f in self.facts]
            write_atomic(self.top / bhpacket.RUN_REPORT, "".join(lines) or "no facts\n")
        return self.finish(res, cyc, sellable0)

    # ------------------------------------------------------------ packets: the test author goes first (d6)

    def held(self) -> list[str]:
        """The items whose packet the planner or orchestrator wrote (R5)."""
        return sorted(p.stem for p in (self.top / bhpacket.PACKETS_DIR).glob("*.json"))

    def queue(self, tried: set[str]) -> list[str]:
        """The work queue: every packet not yet met, in plan order. A ready plan item gets its
        packet from the program first (no agent); a plan item that is not ready waits for its
        dependencies; a packet outside the plan is met when the measurer recorded it met."""
        s = self.state()
        if not self.dry:
            for i in s["ready"] + s["ready_system"]:
                bhpacket.write_plan_packet(self.cfg, i)
        plan = {b["id"]: b for b in s["bricks"]}
        ready = set(s["ready"] + s["ready_system"])
        # finish before start (Kanban WIP): a packet whose acceptance tests are on main, red by
        # design, goes first, even when a dependency went stale since it started; every other item
        # is measured with those red tests in its suite, so it waits for this one, never the reverse
        doing = [
            i
            for i in self.held()
            if i not in tried
            and not (plan[i]["status"] == "met" if i in plan else self.packet_met(i))
            and self.in_progress(i)
        ]
        order = doing + [i for i in s["ready"] + s["ready_system"] if i not in tried and i not in doing]
        for i in self.held():
            if i in tried or i in order or (i in plan and i not in ready):
                continue
            if i not in plan and self.packet_met(i):
                continue
            order.append(i)
        return order

    def in_progress(self, item: str) -> bool:
        """The state records, for the packet's current bytes, its acceptance tests red by an
        assertion on main (the red run) and no merge: its plan commit is on main, unbuilt."""
        if self.dry:
            return False
        digest = hashlib.sha256(bhpacket.packet_path(self.top, item).read_bytes()).hexdigest()
        mine = [j for j in self.recorded(item) if j.get("packet_sha256") == digest]
        return any(j.get("step") == "red_run" and j.get("exit_code") == 0 for j in mine) and not any(
            j.get("step") == "merge" for j in mine
        )

    def packet_met(self, item: str) -> bool:
        """A packet outside the plan (the scoreboard holds plan items only) is met when the order
        engine's state records, for its current bytes, the merge of a met build, or the measurer's
        met verdict with no build (its tests passed at HEAD already)."""
        digest = hashlib.sha256(bhpacket.packet_path(self.top, item).read_bytes()).hexdigest()
        mine = [j for j in self.recorded(item) if j.get("packet_sha256") == digest]
        if any(j.get("step") == "merge" for j in mine):
            return True
        built = any(j.get("role") == "builder" for j in mine)
        return not built and any(j.get("step") == "measurer" and j.get("exit_code") == 0 for j in mine)

    def program_step(
        self, name: str, item: str, started: datetime, digest: str, code: int = 0
    ) -> None:
        self.keep(bhpacket.program_job(name, item, started, digest, code))

    async def packet_flow(self, item: str, facts: list[dict[str, Any]]) -> str:
        """One item: the program writes its packet from the plan; the test author (or, for a defect
        found by an agent other than the builder, that agent) writes the acceptance criteria and their
        tests in the project's own framework; the program commits them with the packet (the plan
        commit) and records them red on main; then the builder, the measurer and, when met, the merge.
        A test that errors, or a criterion with no red test, goes back to the author; rounds are capped
        by ``max_rounds``."""
        root = self.top
        planned = not bhpacket.packet_path(root, item).exists()
        bhpacket.write_plan_packet(self.cfg, item)
        packet, _ = bhpacket.load_packet(root, item)
        defect = packet.get("kind") == "defect"
        if defect and planned:  # QBC-108: a later defect is measured once, when it is planned
            facts += self.defect_misses(item)
        job = "regression_row" if defect and packet.get("found_by") == "reviewer" else "test_author"
        test_path = bhpacket.acceptance_file(packet)
        feedback: list[dict[str, str]] = []
        rounds = range(1, int(self.cfg.data.get("max_rounds", 3)) + 1)
        now = hashlib.sha256(bhpacket.packet_path(root, item).read_bytes()).hexdigest()
        authored = any(  # a restart: the state records this step done for this very packet
            j.get("job") == job and j.get("packet_sha256") == now for j in self.recorded(item)
        )
        reddened = authored and any(
            j.get("step") == "red_run" and j.get("packet_sha256") == now and j.get("exit_code") == 0
            for j in self.recorded(item)
        )
        if reddened:  # the red run is recorded done for this packet as well
            red = True
        elif authored:
            feedback, met_at_head = self.red_on_main(packet, facts)
            if met_at_head:
                await self.measure_all([(item, "HEAD")])
                self.commit("scoreboard")
                return "met"
            red = not feedback
        else:
            red = False
        rnd = 0
        for rnd in [] if red else rounds:
            core = {
                "task": job,
                "item": item,
                "packet": packet,
                "test_path": test_path,
                "test_command": self.cfg.inferred.get("test", {}).get("value", "pytest"),
                "feedback": feedback,
            }
            j = await self.job(
                job,
                f"{item}:{rnd}",
                core,
                {},
                f"Write the acceptance criteria and tests of packet {item}.",
                cwd=root,
            )
            if not j["ok"]:
                return "unmet"
            packet = {**packet, "acceptance": j["output"]["acceptance"]}
            errs = bhpacket.validate_packet(packet)
            if errs:  # outside the packet contract: back to the author with the teaching
                facts += [{"kind": "gap", "item": item, "detail": bhpacket.teaching(e)} for e in errs[:5]]
                feedback = [{"id": item, "error": bhpacket.teaching(e)} for e in errs[:5]]
                continue
            write_atomic(bhpacket.packet_path(root, item), json.dumps(packet, indent=2) + "\n")
            write_atomic(root / test_path, j["output"]["test_code"])
            packet, raw, cap_facts, _ = bhpacket.assemble(root, item)  # the plan commit holds the bytes the builder gets
            facts += [{**f, "item": item} for f in cap_facts]
            digest = bhpacket.custody_store(root, raw)
            self.stamp(j, packet_sha256=digest)  # the step is done for this packet
            # the plan commit names its packet as a build commit does, so the red run measures against it
            self.commit(f"acceptance {item}\n\nPacket: {bhpacket.trailer(packet, digest)}")
            feedback, met_at_head = self.red_on_main(packet, facts)
            if met_at_head:  # the acceptance tests pass on main: built before, nothing to build
                await self.measure_all([(item, "HEAD")])
                self.commit("scoreboard")
                return "met"
            if not feedback:
                red = True
                break
        if not red:
            facts.append(
                {"kind": "stuck", "item": item, "detail": f"{item} acceptance tests are not red by assertion on main after {rnd} rounds"}
            )
            return "stuck"
        # L4 then L5, in rounds (QBC-51): a measurer miss, or a critical or major review finding of a
        # met build, goes back to the same builder in its clone with those messages only.
        feedback: list[str] = []
        met_sha, base = None, git(root, "rev-parse", "HEAD").stdout.strip()  # the plan commit
        digest = hashlib.sha256(bhpacket.packet_path(root, item).read_bytes()).hexdigest()
        first = 1 + max(  # rounds count per packet across runs: the state, never a counter of this run
            (j.get("round") or 0 for j in self.recorded(item) if j.get("role") == "builder" and j.get("packet_sha256") == digest),
            default=0,
        )
        # a round whose acceptance test defect the program confirmed is given back to the builder
        limit = len(rounds) + sum(1 for j in self.recorded(item) if j.get("step") == "test_defect" and j.get("packet_sha256") == digest and j.get("exit_code") == 0)
        rnd = first
        while rnd <= limit:
            code, out, err = bhpacket.launch_builder(root, item, self.job_usd("build"), feedback, base, rnd)
            built = (
                json.loads(out)
                if code == 0
                else {"facts": [{"kind": "gap", "item": item, "detail": err.strip()}], "jobs": []}
            )
            facts += built["facts"]
            for b in built["jobs"]:
                self.spent["cost_usd"] += b.get("cost_usd", 0)
                self.spent["tokens"] += b.get("tokens", 0)
                self.keep(b)
            if code:
                break
            sha, feedback, tier = await self.measure_packet(root, packet, facts)
            if tier:  # re-planned at the tier its diff showed: built again from that packet
                return "re-tiered"
            met_sha = sha or met_sha  # a later round that misses never undoes a met build
            rnd += 1
            if not sha and built.get("test_defects"):  # the builder says a failing test is wrong
                taught, fixed = await self.test_defects(packet, digest, built["test_defects"], facts)
                if fixed is None:  # the corrected tests are not red by assertion at the new base
                    return "stuck"
                if fixed:  # its author corrected it: a fresh clone of the new base, the round given back
                    base, limit = git(root, "rev-parse", "HEAD").stdout.strip(), limit + 1
                feedback = taught + feedback
            if not feedback:
                break
        if met_sha:  # findings left at the round limit never change met (P4)
            if item in self.open_reviews:  # changes requested, no reviewed build followed: settle them
                log, at = self.open_reviews.pop(item)
                self.settle_findings(packet, log, at, facts)
            return await self.merge_item(root, packet, met_sha, facts)
        if feedback or first > limit:
            facts.append(
                {"kind": "stuck", "item": item, "detail": f"{item} reached the round limit of {len(rounds)} builder rounds for this packet; a changed packet or a higher max_rounds starts more"}
            )
        return "unmet"

    def red_on_main(
        self, packet: dict[str, Any], facts: list[dict[str, Any]]
    ) -> tuple[list[dict[str, str]], bool]:
        """The red run on main by the one measurer (``bhcore.measure_ref`` at HEAD against the kept
        packet): every criterion needs a test that fails by an assertion, and no test of the
        acceptance file may error. Returns the author's feedback (empty when all is red) and
        whether the measurer says met at HEAD already (an item built before it was planned)."""
        root, item = self.top, packet["id"]
        digest = bhpacket.custody_store(root, bhpacket.packet_path(root, item).read_bytes())
        t0 = datetime.now(UTC)
        plan = git(  # the plan commit, found by its Packet trailer (on a restart HEAD has moved on)
            root, "log", "-1", "--format=%H", "--fixed-strings", f"--grep=Packet: {bhpacket.trailer(packet, digest)}", check=False
        ).stdout.strip()
        res = bhcore.measure_ref(self.cfg, plan or "HEAD", orch=root)
        self.outs[item] = res["items"][0]["out"]
        accept = res["items"][0]["acceptance"]
        if accept and all(a["status"] == "met" for a in accept):  # no criterion measured is never met
            self.program_step("red_run", item, t0, digest, 1)  # not red: exit 0 is recorded only for red
            self.program_step("measurer", item, t0, digest, 0)  # the measurer's verdict: met at HEAD
            return [], True  # every criterion's test passes at HEAD
        module = bhpacket.acceptance_file(packet).removesuffix(".py").replace("/", ".")
        ids = [a["id"] for a in packet["acceptance"]]
        mine = [  # this file's cases: by module (pytest's classname) or by criterion id (any runner)
            f
            for f in res["facts"]
            if f["kind"] in ("red", "red_by_error")
            and (module in f["detail"] or bhcore._acceptance_of(f["detail"].rsplit("::", 1)[-1], ids))
        ]
        facts += [{"kind": f["kind"], "item": item, "detail": f["detail"]} for f in mine]
        feedback = [
            {"id": f["detail"], "error": f["message"]} for f in mine if f["kind"] == "red_by_error"
        ]
        reds = [f["detail"] for f in mine if f["kind"] == "red"]
        for a in packet["acceptance"]:
            if not any(bhcore._acceptance_of(d.rsplit("::", 1)[-1], [a["id"]]) for d in reds):
                feedback.append(
                    {
                        "id": a["id"],
                        "error": f"no test named after {a['id']} (test_{a['id'].replace('-', '_')}...) "
                        "fails by an assertion on main; write one that does",
                    }
                )
        self.program_step("red_run", item, t0, digest, 1 if feedback else 0)  # 0: every criterion is red
        if packet.get("kind") == "defect" and not feedback:  # the regression test's first half, observed
            facts.append(
                {
                    "kind": "regression_recorded",
                    "item": item,
                    "detail": f"the regression tests of {item} fail by an assertion at the parent {(plan or 'HEAD')[:12]}",
                }
            )
        return feedback, False

    async def test_defects(
        self, packet: dict[str, Any], digest: str, claims: list[dict[str, str]], facts: list[dict[str, Any]]
    ) -> tuple[list[str], bool | None]:
        """The builder's claims that a failing acceptance test is faulty. The builder never edits a
        test (R3); a test red by its own fault goes back to its author (IR-M2, ATDD: the tests are
        the author's). The program checks each claim (P3): the test failed in the measured suite,
        it is an acceptance test of a packet, it was corrected fewer than ``limits.test_corrections``
        times, and it passes alone at the build (an Interacting Test, Meszaros' xUnit Test
        Patterns). A refused claim teaches the builder and its round stays spent (P4, P5). Confirmed
        claims go, with the evidence, to the author of the file that holds the test, for one
        corrected round; the program commits the corrected file with this packet's trailer, records
        the claim confirmed, and records this packet red by an assertion at that new base (L3).
        Returns the builder's lines and whether a test was corrected, or None when the corrected
        tests broke the red run (the item is stuck)."""
        root, item = self.top, packet["id"]
        try:
            cases = bhcore._cases(bhcore.read_junit(root / self.outs.get(item, "-") / "junit.xml"))
        except HarnessError:
            cases = []
        failed = [(c.classname, c.name) for c in cases if any(type(x).__name__ == "Failure" for x in c.result)]
        red = set(failed) | {(k, n.split("[")[0]) for k, n in failed}  # a test is red when one of its parameters is
        owners = {}  # the dotted module of each packet's acceptance file -> its packet
        for i in self.held():
            p, _ = bhpacket.load_packet(root, i)
            owners[bhpacket.acceptance_file(p).removesuffix(".py").replace("/", ".")] = p
        corrected = [j.get("test") for j in self.recorded(item) if j.get("step") == "test_defect" and j.get("exit_code") == 0]
        taught: list[str] = []

        def record(test: str, ok: bool, wrong: str, right: str, prevent: str) -> None:
            t0 = datetime.now(UTC)
            self.keep({**bhpacket.program_job("test_defect", item, t0, digest, 0 if ok else 1), "id": f"{item}-test_defect-{digest[:12]}-{sha([test, len(corrected)])[:12]}", "test": test})
            line = bhcore._teach("test-defect", wrong, right, prevent)
            facts.append({"kind": "test_defect" if ok else "test_defect_refused", "item": item, "detail": test, "message": line})
            taught.append(line)

        shown = bhreview.limits(self.cfg.data)["findings_shown"]
        if len(claims) > shown:
            facts.append({"kind": "test_defect_refused", "item": item, "detail": f"{len(claims) - shown} more claims", "message": f"only the first {shown} claims are checked"})
        checkable: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        for c in claims[:shown]:
            head, _, name = c["test"].rpartition("::")
            mod, _, cls = head.partition(".py::") if ".py" in head else (head, "", "")
            classname = ".".join(x for x in [mod.removesuffix(".py").replace("/", "."), cls.replace("::", ".")] if x)
            test = f"{classname}::{name}"
            owner = next((p for m, p in owners.items() if classname == m or classname.startswith(m + ".")), None)
            if (classname, name) not in red:
                record(test, False, f"{test} did not fail by an assertion in the measured suite", "make the failing tests pass in your owned paths", "claim a test defect only for a test the measurer reported red")
            elif owner is None:
                record(test, False, f"{test} is not an acceptance test of any packet", "fix the tests you own in your owned paths", "claim a test defect only for an acceptance test")
            elif corrected.count(test) >= self.cfg.limit("test_corrections"):
                record(test, False, f"{test} was already corrected by its author", "make it pass in your owned paths", "read a test's fixtures before claiming it is faulty")
            else:
                checkable[(classname, name)] = (owner, c["evidence"])
        alone = bhcore.run_alone(self.cfg, bhpacket.BUILD_REF.format(item=item), list(checkable)) if checkable else {}
        confirmed: dict[str, list[tuple[str, str]]] = {}  # owner -> its tests that passed alone, with the evidence
        for key, (owner, evidence) in checkable.items():
            test = "::".join(key)
            if alone[key] != "passed":
                record(test, False, f"{test} fails in the suite and {alone[key]} alone at your build, so the build is wrong, not the test ({evidence[:80]})", "make it pass in your owned paths", "run the test alone before claiming a test defect")
            else:
                confirmed.setdefault(owner["id"], []).append((test, evidence))
        fixed = False
        for oid, tests in confirmed.items():
            op, _ = bhpacket.load_packet(root, oid)
            path = bhpacket.acceptance_file(op)
            fb = [
                {
                    "id": t,
                    "error": bhcore._teach(
                        "test-isolation",
                        f"it passes alone and fails in the suite after other tests ran ({ev[:80]})",
                        "set up and reset every state the test reads in a fixture of its own file; keep its criterion and assertions",
                        "each test owns its state: a fresh fixture per test, never the run order (xUnit Test Patterns)",
                    ),
                }
                for t, ev in tests
            ]
            core = {"task": "test_author", "item": oid, "packet": op, "test_path": path, "test_command": self.cfg.inferred.get("test", {}).get("value", "pytest"), "feedback": fb}
            j = await self.job("test_author", f"{oid}:test-defect:{item}", core, {}, f"Correct the acceptance tests of packet {oid} that the feedback names.", cwd=root)
            if not j["ok"]:  # nothing changed: the claims stay unconfirmed and the builder is told so
                for t, _ in tests:
                    record(t, False, f"{t} passes alone, but its author ({oid}) returned no correction", "make the failing tests pass in your owned paths", "the item goes on with the tests as they are")
                continue
            write_atomic(root / path, j["output"]["test_code"])  # the criteria stay the packet's: only the test file changes
            self.commit(f"acceptance {item}: the tests of {oid} corrected\n\nPacket: {bhpacket.trailer(packet, digest)}")
            fixed = True
            for t, _ in tests:  # confirmed once the correction is committed
                record(t, True, f"{t} passes alone and fails in the suite at your build: it depends on state another test leaves", f"its author ({oid}) corrected it; build again on the corrected tests", "claim a test defect only with that evidence")
        if not fixed:
            return taught, False
        again, _ = self.red_on_main(packet, facts)  # L3 again at the new base
        try:
            now = bhcore._cases(bhcore.read_junit(root / self.outs[item] / "junit.xml"))
        except (HarnessError, KeyError):
            now = []
        others = [m for m, p in owners.items() if p["id"] in confirmed and p["id"] != item]
        broken = [
            f"{c.classname}::{c.name}"
            for c in now
            if any(type(x).__name__ in ("Failure", "Error") for x in c.result)
            and any(c.classname == m or c.classname.startswith(m + ".") for m in others)
        ]
        if again or broken:
            facts.append({"kind": "stuck", "item": item, "detail": f"the corrected tests are not red by assertion at the new base: {', '.join([a['id'] for a in again] + broken)[:200]}"})
            return taught, None
        return taught, True

    async def measure_packet(
        self, root: Path, packet: dict[str, Any], facts: list[dict[str, Any]]
    ) -> tuple[str | None, list[str], str | None]:
        """The measurer step for a packet: the builder's commit, which the program's commit step
        brought into the repository as the item's build ref (a ref the builder cannot move), is measured by the one measurer, ``bhcore.measure_ref``, against the
        packet kept in custody; a met build gets the triggered review of its whole diff, recorded
        before any merge. Returns the met commit (None when unmet), the builder's feedback for
        another round (the missed checks' messages, or the critical and major findings), and the
        tier the packet was re-planned at when its diff raised it (R6, QBC-30), else None."""
        item, t0 = packet["id"], datetime.now(UTC)
        clones = sorted(
            (root / bhpacket.CLONES_DIR).glob(f"{item}-*"), key=lambda p: p.stat().st_mtime
        )
        digest = bhpacket.custody_digest(root, item) or ""  # identity comes from custody alone
        if not clones:
            self.program_step("measurer", item, t0, digest, 1)
            return None, [], None
        ref = bhpacket.BUILD_REF.format(item=item)  # set by the program's commit of the build
        res = bhcore.measure_ref(self.cfg, ref, orch=root)
        self.outs[item] = res["items"][0]["out"]
        facts += res["facts"]
        self.program_step("measurer", item, t0, digest, 0 if res["items"][0]["status"] == "met" else 1)  # the verdict
        tier = res["items"][0].get("tier") or packet["tier"]
        if bhpacket.TIER_RANK[tier] > bhpacket.TIER_RANK[packet["tier"]]:  # the diff's tier (QBC-30)
            self.replan(packet, tier)
            return None, [], tier
        if res["items"][0]["status"] != "met":  # only the missed checks' messages (QBC-55)
            missed = [f["message"] for f in res["facts"] if f["kind"] in MISSED and f.get("message")]
            missed += [
                f"[{a['id']}] the acceptance criterion is unmet -> make its test pass . {bhpacket.SPEC}"
                for a in res["items"][0].get("acceptance", [])
                if a["status"] != "met"
            ]
            return None, self.shown(missed), None
        sha = git(root, "rev-parse", ref).stdout.strip()
        return sha, self.shown(await self.review_item(packet, digest, sha, tier, facts)), None

    async def merge_item(
        self, root: Path, packet: dict[str, Any], sha: str, facts: list[dict[str, Any]]
    ) -> str:
        """Merge the item's met commit into the default branch (``bhcore.merge_refs``) and re-measure
        it at HEAD, which records it in the scoreboard."""
        item, t0 = packet["id"], datetime.now(UTC)
        digest = bhpacket.custody_digest(root, item) or ""
        if packet.get("kind") == "defect":
            facts.append(
                {
                    "kind": "regression_recorded",
                    "item": item,
                    "detail": f"the regression tests of {item} pass at the fix {sha[:12]}",
                }
            )
        merged, conflicts = bhcore.merge_refs(self.cfg, root, [{"item": item, "ref": sha}])
        if conflicts:
            facts += [{"kind": "conflict", "item": item, "detail": ", ".join(c["paths"])} for c in conflicts]
            return "unmet"
        self.program_step("merge", item, t0, digest)
        (at_head,) = await self.measure_all([(item, "HEAD")])
        self.commit("scoreboard")
        if at_head.get("status") == "unmet":  # red on merged HEAD: a defect under it
            misses = [str(e) for e in at_head.get("errors") or []] or [f"{item} is {at_head.get('status')} at HEAD after its merge"]
            self.plan_defect(packet, "measurer", misses, git(root, "rev-parse", "HEAD").stdout.strip(), facts)
        return "met"

    def shown(self, lines: list[str]) -> list[str]:
        """The first ``limits.findings_shown`` messages, then the count of the rest (QBC-55)."""
        n = bhreview.limits(self.cfg.data)["findings_shown"]
        return lines[:n] + ([f"... and {len(lines) - n} more"] if len(lines) > n else [])

    async def review_item(
        self, packet: dict[str, Any], digest: str, sha: str, tier: str, facts: list[dict[str, Any]]
    ) -> list[str]:
        """The review (QBC-36) of a met build, before its merge, in code review's request-changes
        loop (Google engineering practices): the one review job judges the item's whole diff, and a
        critical or major finding goes back to the builder for at most ``limits.review_rounds``
        rounds per packet, counted from the state. Past them the review still runs on the build that
        merges; its critical and major findings become a defect item under this one, its minor and
        trivial ones Known issues lines (§0 R8, P4: findings never change met). Returns the
        builder's feedback lines."""
        root, item = self.top, packet["id"]
        base = git(root, "merge-base", "HEAD", sha).stdout.strip()
        label = f"{item}:review:{sha[:12]}"
        prior = sum(
            1
            for j in self.recorded(item)
            if j.get("job") == "review" and j.get("packet_sha256") == digest and j.get("label") != label
        )
        log = await self.review_diff(packet, digest, base, sha, tier, facts)
        if log is None:
            return []
        errs = bhreview.errors(log)
        self.open_reviews.pop(item, None)  # this review supersedes an earlier one
        if errs and prior < self.cfg.limit("review_rounds"):  # request changes
            self.open_reviews[item] = (log, sha)  # settled at the merge if no reviewed build follows
            return errs
        self.settle_findings(packet, log, sha, facts)
        return []

    async def review_diff(
        self,
        packet: dict[str, Any],
        digest: str,
        base: str,
        sha: str,
        tier: str,
        facts: list[dict[str, Any]],
        record: bool = True,
    ) -> dict[str, Any] | None:
        """The one review job of a diff, for an item's build and for ``bh review`` alike: the
        program judges the triggers on the whole diff ``base..sha``; a fresh reviewer that never
        built it (P6) judges the diff against exactly the packet's rule lines (the builder's) and
        the triggered domains; its findings are recorded as SARIF facts and, for a build
        (``record``), in gaps.json with a commit. Returns the SARIF log, or None when no review runs."""
        root, item = self.top, packet["id"]
        trig = bhreview.triggers(root, self.cfg.data, base, sha, tier, packet.get("kind", "slice"))
        if not trig:
            return None
        selected = packet["verifier"].get("rules", [])
        rules = selected + self.diff_rules(item, base, sha, selected)
        core = {
            "task": "review",
            "item": item,
            "packet_sha256": digest,
            "diff": f"git diff {base} {sha}",
            "triggers": trig,
            "rules": rules,  # the builder's lines plus those the actual diff's facts add (QBC-105 ii)
            # the published interfaces only where duplication is judged: the input stays small (M4)
            **(
                {"interfaces": packet["constraints"].get("interfaces", [])}
                if any(t["domain"] == "duplication" for t in trig)
                else {}
            ),
        }
        j = await self.job(
            "review",
            f"{item}:review:{sha[:12]}",
            core,
            {},
            f"Review the whole diff of item {item} against its packet's rules and the triggered domains.",
            cwd=root,
        )
        if not j["ok"]:
            facts.append({"kind": "gap", "item": item, "detail": f"review of {item} did not finish: {j.get('error')}"})
            return None
        # severity and the right way come from each rule's own metadata (QBC-114, QBC-115)
        house = bhrules.rules_doc(self.cfg).get("house", {})
        findings, settled = bhreview.settle(j["output"]["findings"], house, root, sha)
        misses = self.selector_misses(item, [r["id"] for r in selected], findings, base, sha)
        facts += misses
        # the review rounds of a packet are counted from the state; bh metrics counts the misses
        # from the run result's facts (QBC-108: one source)
        self.stamp(j, packet_sha256=digest)
        chars = bhreview.limits(self.cfg.data)["message_chars"]
        log = bhreview.sarif(findings, item, digest, chars, house)
        log["runs"][0]["properties"]["rules"] = [r["id"] for r in rules]  # what the review judged
        if settled:
            log["runs"][0]["properties"]["severity_settled"] = settled
        if not self.dry:
            write_atomic(self.out / item / f"review-{sha[:12]}.sarif", json.dumps(log, indent=2) + "\n")
        if record and findings:
            bhcore.add_findings(self.cfg, [{**f, "source": "review"} for f in findings], write=True)
            self.commit(f"review {item}")
        return log

    def diff_rules(self, item: str, base: str, sha: str, have: list[dict[str, str]]) -> list[dict[str, str]]:
        """The rule lines the diff ``base..sha``'s own facts (c) add beyond ``have`` (QBC-105 ii):
        a capability the builder added without plan is still judged, and the finding teaches it.
        An unplanned item is the change itself, scoped to the packages it touches (QBC-116); the
        input keeps at most ``limits.packet_rules`` full lines (``bhrules.review_lines``)."""
        ctx = bhcore.packet_context(self.cfg)
        brick = bhrules.unit(self.cfg, ctx["bricks"], item, base, sha)
        diff = bhrules.diff_tags(self.cfg, base, sha)
        sel = bhrules.select_rules(self.cfg, brick, list(ctx["bricks"].values()), diff=diff, base=base)
        ids = {r["id"] for r in have}
        return bhrules.review_lines(self.cfg, have, [r for r in sel["added_by_diff"] if r not in ids])

    def selector_misses(
        self, item: str, selected: list[str], findings: list[dict[str, Any]], base: str | None = None, sha: str | None = None
    ) -> list[dict[str, Any]]:
        """A finding whose rule the item's selection missed, as a ``selector_miss`` fact in teach
        form naming the entry that would have selected it (QBC-108): the mapping's ratchet."""
        bricks = bhcore.packet_context(self.cfg)["bricks"]
        brick = bhrules.unit(self.cfg, bricks, item, base, sha) if base and sha else bricks.get(item) or {"id": item}
        out = []
        for m in bhrules.selector_misses(self.cfg, brick, selected, findings, base=base):  # tags as planned
            wrong = f"rule {m['rule']} judged a finding but was not in {item}'s packet"
            right = f"add tag {m['missing_tag']} to the capability table or to {m['rule']}'s applies, so the facts select it"
            out.append({**m, "item": item, "detail": f"{m['rule']}: {m['missing_tag']}", "message": bhcore._teach("selector_miss", wrong, right, "QBC-108")})
        return out

    def defect_misses(self, item: str) -> list[dict[str, Any]]:
        """A later defect whose broken rule its parent item's packet lacked, as ``selector_miss``
        facts on the parent (QBC-108). The defect plan item is the one source: every creator (the
        review's settle, the measurer at HEAD, tracker intake) records it there with ``breaks``. A
        reviewer's defect is skipped: its finding was already measured at the review, once."""
        bricks = bhcore.packet_context(self.cfg)["bricks"]
        d = bricks.get(item) or {}
        if d.get("found_by") == "reviewer" or not d.get("breaks"):
            return []
        parent = str(d.get("parent"))
        owner = next((b for b in bricks.values() if b["id"] == parent or parent in map(str, b.get("refs", []))), None)
        if owner is None:
            return []
        path = bhpacket.packet_path(self.top, owner["id"])  # the lines its builder was given, else its selection now
        given = bhpacket.load_packet(self.top, owner["id"])[0]["verifier"]["rules"] if path.exists() else bhpacket.item_rules(self.cfg, owner["id"])
        return self.selector_misses(owner["id"], [r["id"] for r in given], [{"rule": r} for r in d["breaks"]])

    async def phase_review(self, rng: str, item: str | None) -> dict[str, Any]:
        """``bh review BASE..HEAD [--item X]``: the same review job on any diff, a human's commits
        included (G2, QBC-16, QBC-107). With ``--item`` it judges that item's selection at BASE
        (``bhrules.rules_cmd``) plus the rules the diff's facts add; without, the core, the stack's
        and the diff's rules (QBC-104, QBC-105). The tier is the diff's (R6). Findings are facts in
        SARIF under the measure output and the result, misses ``selector_miss`` facts; it commits
        nothing and starts no round."""
        root = self.top
        base, _, head = rng.partition("..")
        base = git(root, "rev-parse", "--verify", f"{base}^{{commit}}").stdout.strip()
        sha = git(root, "rev-parse", "--verify", f"{head or 'HEAD'}^{{commit}}").stdout.strip()
        changed = git(root, "diff", "--name-only", base, sha).stdout.split()
        bricks = bhcore.packet_context(self.cfg)["bricks"]
        if item and item not in bricks:
            raise HarnessError(f"[review-unknown-item] {item} is not in the plan -> name a planned item or leave --item out")
        # the item's selection as of BASE, where the diff starts, else the project's core and stack
        # (QBC-107): read from a worktree at BASE, so the diff's own facts are not taken as planned
        scope = None if item else bhrules.unit(self.cfg, {}, None, base, sha).get("paths")  # QBC-116: the touched packages
        at = json.loads(bhrules.rules_cmd(str(self.cfg.path), item, at=base, scope=scope))
        rules = [{"id": r["id"], "message": r["text"] or r["id"]} for r in [*at["chosen"], *at["more"]]]
        kind = "defect" if item and bricks[item].get("kind") == "defect" else "slice"
        packet = {
            "id": item or "(project)",
            "kind": kind,
            "verifier": {"rules": rules},
            "constraints": bhreview.packet_owners(root, changed, bhreview.limits(self.cfg.data)["message_chars"]),
        }
        tier = bhcore.diff_tier(self.cfg.data, root, base, sha, kind)[0]
        digest = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
        facts: list[dict[str, Any]] = []
        # a review of any diff writes no commit: a pre-push hook or a replay leaves the branch as it was
        log = await self.review_diff(packet, digest, base, sha, tier, facts, record=False)
        results = log["runs"][0]["results"] if log else []
        return {
            "item": packet["id"],
            "tier": tier,
            "reviewed": log is not None,
            "rules": log["runs"][0]["properties"]["rules"] if log else [],
            "findings": [r["message"]["text"] for r in results],
            "facts": facts,
        }

    def settle_findings(
        self, packet: dict[str, Any], log: dict[str, Any], sha: str, facts: list[dict[str, Any]]
    ) -> None:
        """Findings left open by the review that starts no round: the critical and major ones become
        one defect item under this item (planned once per build), the minor and trivial ones lines
        of the single Known issues list (§0 R8), or facts when the project keeps no such list."""
        item = packet["id"]
        major = bhreview.errors(log)
        minor = [r["message"]["text"] for r in log["runs"][0]["results"] if r["level"] != "error"]
        if major:
            broke = [r["ruleId"] for r in log["runs"][0]["results"] if r["level"] == "error"]
            self.plan_defect(packet, "reviewer", major, sha, facts, broke)
        ref, parent = (self.cfg.data.get("tracker") or {}).get("known_issues"), packet.get("parent_issue")
        for line in minor:
            added = False
            if ref and parent and not self.dry:
                try:
                    added = bhintake.known_add(self.cfg, bhtracker.Tracker(self.cfg), f"#{parent} {item}: {line}")["added"]
                except bhtracker.TrackerError as e:
                    facts.append({"kind": "gap", "item": item, "detail": f"Known issues not reached: {e}"})
            if not added:
                facts.append({"kind": "known_issue", "item": item, "detail": line})

    def plan_defect(
        self,
        packet: dict[str, Any],
        found_by: str,
        evidence: list[str],
        sha: str,
        facts: list[dict[str, Any]],
        breaks: list[str] | None = None,
    ) -> None:
        """Record a defect found on ``packet``'s item as a plan item of kind defect under it (§0 R8),
        naming the rules it ``breaks`` as its findings cite them. A defect fix that still leaves one
        starts no chain of defects: it is stuck, for its owner."""
        if packet.get("kind") == "defect":
            facts.append({"kind": "stuck", "item": packet["id"], "detail": f"the fix still leaves a defect found by the {found_by}: {evidence[0][:200]}"})
            return
        d = bhpacket.defect_item(self.cfg, packet, found_by, self.shown(evidence), sha, breaks)
        facts.append({"kind": "defect_planned", "item": packet["id"], "detail": f"{d['id']}, found by the {found_by}"})
        if self.dry:
            return
        bhtracker.append_items(self.cfg, [d])
        self.commit(f"defect {d['id']}")

    def replan(self, packet: dict[str, Any], tier: str) -> None:
        """Re-plan a packet at the tier its diff showed (QBC-30): the program rewrites the packet
        with that tier, keeps it in custody and commits it as a plan commit naming it, so the item
        is built again from a packet at its real tier. Nothing is refused or merged."""
        root, item = self.top, packet["id"]
        path = bhpacket.packet_path(root, item)
        cons = packet.get("constraints", {})  # the re-plan declares the paths its tier absorbs (L4)
        declared = [*cons.get("declared_paths", []), *bhpacket.outside_paths(root, packet)]
        write_atomic(path, json.dumps({**packet, "tier": tier, "constraints": {**cons, "declared_paths": declared}}, indent=2) + "\n")
        digest = bhpacket.custody_store(root, path.read_bytes())
        new, _ = bhpacket.load_packet(root, item)
        self.commit(f"re-tier {item} as {tier}\n\nPacket: {bhpacket.trailer(new, digest)}")

    def over_budget(self, budgets: dict[str, Any]) -> bool:
        return bool(
            (budgets.get("run_tokens") and self.spent["tokens"] >= budgets["run_tokens"])
            or (budgets.get("run_usd") and self.spent["cost_usd"] >= budgets["run_usd"])
        )

    def job_table(self) -> list[dict[str, Any]]:
        keep = (
            "job",
            "label",
            "agent",
            "key",
            "mode",
            "ok",
            "skipped",
            "cost_usd",
            "tokens",
            "duration_ms",
            "turns",
            "subtype",
            "auth_fallback",
            "fallback_reason",
            "error",
            "dry_run",
            "kind",
            "role",
            "step",
            "item",
            "started_at",
            "ended_at",
            "exit_code",
            "packet_sha256",
            "id",
            "round",
        )
        rows = [{k: r[k] for k in keep if k in r} for r in self.records]
        for row in rows:  # a skipped job spent nothing in this run (as the totals say)
            if row.get("skipped"):
                row["cached_cost_usd"], row["cost_usd"] = row.get("cost_usd", 0), 0.0
        return rows

    def finish(
        self, res: dict[str, Any], cyc: dict[str, Any], sellable0: set[str]
    ) -> dict[str, Any]:
        """The run result: the product view first, then met, stuck and gaps, the owner questions,
        the auth mode and what each job cost."""
        s = self.state()
        return self.compose(res, s, cyc.get("stuck", []), cyc.get("stuck_more", 0), sellable0)

    def compose(
        self,
        res: dict[str, Any],
        s: dict[str, Any],
        stuck: list[Any],
        stuck_more: int,
        sellable0: set[str] | None = None,
    ) -> dict[str, Any]:
        cfg = self.cfg
        v = s["value"]
        try:
            feats = {f["id"]: f for f in bhcore.load_features(cfg)}
        except HarnessError:
            feats = {}
        nxt = v.get("next")
        nxt_f = feats.get((nxt or {}).get("feature"), {})
        sellable = [
            {"feature": f, "slice": (feats.get(f) or {}).get("slice")}
            for f in v["sellable_at_head"]
        ]
        counts: dict[str, int] = {}
        for b in s["bricks"]:
            counts[b["status"]] = counts.get(b["status"], 0) + 1
        questions = list((res.get("setup") or {}).get("questions", []))
        gp = cfg.file("gaps")
        if gp and gp.exists() and not self.dry:
            for g in json.loads(gp.read_text()).get("gaps", []):
                if bhcore._is_question(g) and not g.get("answered_by"):
                    questions.append(
                        {
                            k: g.get(k)
                            for k in ("id", "kind", "summary", "evidence", "resolve_with")
                            if g.get(k) is not None
                        }
                    )
        result = {
            "product": {
                "sellable_at_head": sellable,
                "became_sellable_this_run": [
                    f for f in v["sellable_at_head"] if f not in (sellable0 or set())
                ],
                "current_slice": nxt_f.get("slice") if nxt else None,
                "next": (
                    {
                        "feature": nxt["feature"],
                        "slice": nxt_f.get("slice"),
                        "value": nxt_f.get("value"),
                        "remaining_cost_est_loc": nxt["remaining_cost"],
                        "why": "earliest slice, then highest value per remaining cost",
                    }
                    if nxt
                    else None
                ),
                "unvalued_features": v.get("unvalued", []),
            },
            "status": {
                "all_met": s["all_met"],
                "items": counts,
                "met": [b["id"] for b in s["bricks"] if b["status"] == "met"],
                "stuck": stuck,
                "stuck_more": stuck_more,
                "gaps": {
                    "owner-decides": sum(1 for g in s["gaps"] if g["tag"] == "owner-decides"),
                    "fixable": sum(1 for g in s["gaps"] if g["tag"] == "fixable"),
                },
                "problems": s["problems"],
            },
            "owner_questions": questions,
            "overlay_candidates": s["learning"]["overlay_candidates"],
            "auth": {
                "mode_at_start": self.mode_start,
                "mode_at_end": self.mode,
                "fallbacks_to_login": self.fallbacks,
            },
            "jobs": self.job_table(),
            "totals": {
                **self.spent,
                "jobs": len(self.records),
                "skipped": sum(1 for r in self.records if r.get("skipped")),
            },
            "errors": self.errors,
            "phases": res,
        }
        return result


# ---------------------------------------------------------------- printing and the CLI


def result_doc(cmd: str, r: dict[str, Any]) -> dict[str, Any]:
    """The result JSON a bh command prints as its last stdout line, made of d0's decided result and
    ``jobs[*]`` fields only (docs/atdd/fields.yaml); the whole run document stays in
    ``<command>-result.json`` and the summary text."""
    phases = r.get("phases") or {}
    measured = phases.get("measure") or {}
    # every item a verdict was reached for: the build rounds and the measure phase's measurements
    # (measured at their refs, then at HEAD; the last one is the item's verdict)
    rounds = [x for x in phases.get("rounds") or [] if "status" in x]
    rounds = list(
        {
            x["item"]: x
            for x in [*rounds, *measured.get("measured", []), *measured.get("remeasured", [])]
            if x.get("status") != "dry-run"
        }.values()
    )
    verdict = lambda st: st if st in ("met", "unmet", "stuck") else "unmet"  # noqa: E731
    jobs = []
    for j in r.get("jobs", []):
        tok = j.get("tokens") or 0
        row = {
            "id": j.get("id") or j.get("key"),
            "kind": j.get("kind", "agent"),
            "exit_code": j.get("exit_code", 0 if j.get("ok") else 1),
            "cost_usd": j.get("cost_usd", 0.0),
            "tokens": sum(tok.values()) if isinstance(tok, dict) else tok,
            "cached": bool(j.get("skipped")),
        }
        keep = ("role", "step", "item", "started_at", "ended_at", "packet_sha256", "round")
        jobs.append(row | {k: j[k] for k in keep if j.get(k) is not None})
    return {
        "schema_version": bhcore.RESULT_VERSION,
        "command": cmd,
        "items": [
            {"id": x["item"], "status": verdict(x["status"]), **({"out": x["out"]} if x.get("out") else {})} for x in rounds
        ],
        "facts": [
            {k: str(f[k]) for k in ("kind", "detail", "item", "message") if f.get(k) is not None}
            for f in [*(f for x in rounds for f in x.get("facts", [])), *(phases.get("review") or {}).get("facts", [])]
        ],
        "jobs": jobs,
    }


def summary_text(r: dict[str, Any], path: Path | None) -> str:
    """The short text a run prints: product view first."""
    if "product" not in r:
        return json.dumps(r, indent=2, default=str)
    p, st = r["product"], r["status"]
    lines = ["PRODUCT"]
    sell = (
        ", ".join(f"{x['feature']} (slice {x['slice']})" for x in p["sellable_at_head"])
        or "nothing yet"
    )
    lines.append(f"  sellable at HEAD: {sell}")
    if p["became_sellable_this_run"]:
        lines.append(f"  became sellable this run: {', '.join(p['became_sellable_this_run'])}")
    n = p["next"]
    lines.append(
        f"  current slice: {p['current_slice']}; next: "
        + (
            f"{n['feature']} (value {n['value']}, ~{n['remaining_cost_est_loc']} est_loc left; {n['why']})"
            if n
            else "none"
        )
    )
    if p["unvalued_features"]:
        lines.append(f"  unvalued features: {len(p['unvalued_features'])}")
    lines.append("STATUS")
    lines.append(f"  items: {st['items']} all_met={st['all_met']}")
    for x in st["stuck"][:10]:
        lines.append(f"  stuck: {x.get('item') or x.get('id') or x}: {x.get('reason', '')}")
    lines.append(f"  gaps: {st['gaps']}")
    review = (r.get("phases") or {}).get("review")
    if review is not None:  # bh review: its findings in teach form; it never blocks (P4)
        lines.append(f"REVIEW {review['item']} ({review['tier']}): " + (f"{len(review['findings'])} findings" if review["reviewed"] else "no review ran (no trigger, 0 tokens)"))
        lines += [f"  {f}" for f in review["findings"][:20]]
    misses = [
        f
        for f in [*(f for x in (r.get("phases") or {}).get("rounds") or [] for f in x.get("facts", [])), *(review or {}).get("facts", [])]
        if f.get("kind") == "selector_miss"
    ]
    if misses:  # QBC-108: each miss teaches which mapping entry would have selected its rule
        lines.append(f"SELECTOR MISSES ({len(misses)})")
        lines += [f"  {m['message']}" for m in misses[:20]]
    if r["owner_questions"]:
        lines.append(f"OWNER QUESTIONS ({len(r['owner_questions'])})")
        lines += [f"  {q['id']}: {q['summary']}" for q in r["owner_questions"][:20]]
    setup = (r.get("phases") or {}).get("setup") or {}
    if setup.get("facts"):
        lines.append("SETUP (inferred from the project's standard files)")
        lines += [f"  {f['kind']} {f['detail']}" for f in setup["facts"]]
    if r.get("overlay_candidates"):
        lines.append(
            f"OVERLAY RULES TO BUILD ({len(r['overlay_candidates'])}): areas the owner answered often"
        )
        lines += [
            f"  {c['area']}: {', '.join(c['decisions'])}" for c in r["overlay_candidates"][:20]
        ]
    a, t = r["auth"], r["totals"]
    lines.append(
        f"AUTH {a['mode_at_start']} -> {a['mode_at_end']} (fallbacks {a['fallbacks_to_login']})"
    )
    lines.append(
        f"JOBS {t['jobs']} ({t['skipped']} skipped), cost ${t['cost_usd']:.4f}, tokens {t['tokens']}"
    )
    for j in r["jobs"]:
        c = 0.0 if j.get("skipped") else j.get("cost_usd", 0) or 0  # skipped: nothing spent now
        earlier = j.get("cached_cost_usd") or 0
        note = f" (skipped, cached; earlier ${earlier:.4f})" if j.get("skipped") else ""
        tok = j.get("tokens") or 0  # an agent job counts by kind, a builder or program step in one number
        tok = sum(tok.values()) if isinstance(tok, dict) else tok
        label = j.get("label") or f"{j.get('item')} {j.get('step') or j.get('role')}"
        ok = j.get("ok", j.get("exit_code") == 0)
        lines.append(
            f"  {label}: {'ok' if ok else 'FAILED'}{note} ${c:.4f} {tok} tok [{j.get('mode') or j.get('kind')}]"
        )
    for e in r["errors"][:10]:
        lines.append(f"ERROR {e}")
    if path:
        lines.append(f"result: {path}")
    return "\n".join(lines)


async def dispatch(orch: Orchestrator, cmd: str, a: argparse.Namespace) -> dict[str, Any]:
    if cmd == "run":
        owners = [tuple(o.split("=", 1)) for o in a.owner]
        if any(len(o) != 2 for o in owners):
            raise HarnessError("--owner takes PATTERN=OWNER")
        return await orch.run(a.skip, a.approve, owners, a.decline)  # type: ignore[arg-type]
    s0 = orch.state()
    sellable0 = set(s0["value"]["sellable_at_head"])
    phases: dict[str, Any]
    if cmd == "gaps":
        phases = {"gaps": await orch.phase_gaps()}
    elif cmd == "plan":
        phases = {"plan": await orch.phase_plan()}
    elif cmd == "measure":
        refs = [
            {"ref": r.partition("@")[2] or "HEAD", "items": [r.partition("@")[0]]}
            for r in a.item or []
        ]
        phases = {"measure": await orch.phase_measure(refs or None)}
    elif cmd == "harvest":
        phases = {"harvest": await orch.phase_harvest()}
    elif cmd == "review":
        phases = {"review": await orch.phase_review(a.range, a.item)}
    else:
        raise HarnessError(f"unknown command {cmd}")
    s = orch.state()
    return orch.compose(phases, s, [], 0, sellable0)


def _intake_cmd(a: argparse.Namespace) -> int:
    """metrics, intake: one JSON result, printed (QBC-87 to QBC-90, R11)."""
    import bhmetrics

    try:
        cfg = Config(a.config)
        if a.cmd == "metrics":
            res = bhmetrics.metrics(cfg)
        else:
            tr = bhtracker.Tracker(cfg)
            res = bhintake.known_add(cfg, tr, a.known) if a.known else bhintake.check_parents(tr)
    except (HarnessError, bhtracker.TrackerError) as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(json.dumps({"command": a.cmd, **res}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bh", description="Run the build harness (orchestrator).")
    common = argparse.ArgumentParser(add_help=False)  # accepted before or after the subcommand
    for p, dflt in ((ap, None), (common, argparse.SUPPRESS)):
        p.add_argument("--config", default=dflt or ".brick-harness/config.json")
        p.add_argument(
            "--dry-run",
            action="store_true",
            default=dflt or False,
            help="list the agent jobs that would start; write nothing, spend nothing",
        )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", parents=[common], help="gaps, plan, then each packet (test author, builder clone, measurer); harvest")
    r.add_argument("--skip", nargs="*", default=[], choices=["gaps", "plan", "harvest"])
    r.add_argument(
        "--approve",
        nargs="*",
        choices=list(Orchestrator.SETUP_WRITES),
        help="the owner approved the setup's standard-file writes (none named: all it asked for)",
    )
    r.add_argument(
        "--decline",
        nargs="+",
        choices=list(Orchestrator.SETUP_WRITES),
        help="the owner declined these setup writes: kept in .brick-harness/config.json, not asked again",
    )
    r.add_argument(
        "--owner",
        action="append",
        default=[],
        metavar="PATTERN=OWNER",
        help="the owner's answer about who owns a package, recorded in CODEOWNERS",
    )
    sub.add_parser("gaps", parents=[common], help="find spec gaps")
    sub.add_parser("plan", parents=[common], help="derive items, targets, contracts")
    m = sub.add_parser(
        "measure", parents=[common], help="measure ITEM@REF (repeatable), merge, re-measure"
    )
    m.add_argument("--item", action="append", help="ID[@REF]; none: the ready items at HEAD")
    sub.add_parser("harvest", parents=[common], help="find duplicated helpers")
    rv = sub.add_parser(
        "review", parents=[common], help="review BASE..HEAD against the item's packet rules, as a build's review does"
    )
    rv.add_argument("range", metavar="BASE..HEAD")
    rv.add_argument("--item", help="the planned item whose rules judge the diff (default: the items it touches)")
    sub.add_parser("metrics", parents=[common], help="DORA measures, baseline and current")
    it = sub.add_parser("intake", parents=[common], help="parent check on open issues; --known LINE adds a Known issues line")
    it.add_argument("--known", metavar="LINE")
    sub.add_parser(
        "check", parents=[common], help="measure the working tree as the measurer does (builder)"
    )
    dc = sub.add_parser("decide", parents=[common], help="a fresh judge job scores a decision record's options")
    dc.add_argument("record", help="the MADR 4.0 decision record (markdown)")
    vt = sub.add_parser("vet", help="a package's deps.dev, OpenSSF Scorecard and OSV facts; no config")
    vt.add_argument("system", help="deps.dev system: pypi, npm, go, maven, cargo, nuget")
    vt.add_argument("name")
    vt.add_argument("version", nargs="?", help="default: the version deps.dev marks default")
    st = sub.add_parser("step", help="run one program step with no agent and no config")
    st.add_argument("name", choices=bhpacket.STEPS)
    st.add_argument("--item")  # required by every step but merge
    ru = sub.add_parser("rule", parents=[common], help="print a rule in full: text, why, right way, question, sources")
    ru.add_argument("id")
    rs = sub.add_parser("rules", parents=[common], help="the candidate and chosen rules of an item; no agent")
    rs.add_argument("--item", help="a planned item (default: the project, core and stack only)")
    rs.add_argument("--at", metavar="REV", help="select as at this commit (default: the working tree)")
    rs.add_argument(
        "--diff", nargs="*", metavar="BASE [REF]",
        help="add the rules the change's facts add: the working tree against BASE (default HEAD), or BASE..REF",
    )  # fmt: skip
    a = ap.parse_args(argv)
    if a.cmd in ("rule", "rules"):  # catalog, plan and code facts only: no orchestrator, no agent
        if a.cmd == "rules" and a.diff is not None and len(a.diff) > 2:
            ap.error("--diff takes at most BASE and REF")
        import bhrules

        try:
            out = bhrules.rule_cmd(a.config, a.id) if a.cmd == "rule" else bhrules.rules_cmd(a.config, a.item, a.at, a.diff)
        except HarnessError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(out, end="")
        return 0
    if a.cmd == "vet":  # public services only: no orchestrator, no config
        import bhvet

        return bhvet.main(a.system, a.name, a.version)
    if a.cmd == "step":  # a program step reads only its packet: no orchestrator, no config
        return bhpacket.run_step(a.name, a.item)
    if a.cmd in ("metrics", "intake"):  # tracker and git facts only: no orchestrator
        return _intake_cmd(a)
    try:
        bare = (a.cmd == "measure" and not a.item) or a.cmd in ("check", "decide")
        cfg = Config(a.config, partial=bare)  # a bare measurement reads the file as an override
        if a.cmd == "decide":  # one judge job; no plan needed
            import bhdecide

            orch = Orchestrator(cfg, a.dry_run)
            return bhdecide.print_result(asyncio.run(bhdecide.decide(orch, Path(a.record).resolve())))
        if a.cmd == "check":  # no orchestrator and no lock: it only reads and writes under the clone
            top = bhcore.git_top(cfg.dir)
            if top is None:
                raise HarnessError("not a git repository")
            res = bhcore.measure_ref(cfg, bhcore.snapshot_working_tree(top), self_check=True)
            for f in res["facts"]:  # the teaching lines first, the result JSON last
                print(f["message"])
            print(json.dumps(res))
            return 0 if all(i["status"] == "met" for i in res["items"]) else 1
        bricks = cfg.file("bricks")
        if bare and not (bricks and bricks.exists()):
            res = bhcore.measure_ref(cfg)  # no plan: measure HEAD against its plan commit
            for f in res["facts"]:  # the teaching lines first, the result JSON last
                print(f["message"])
            print(json.dumps(res))
            return 0 if all(i["status"] == "met" for i in res["items"]) else 1
        if bare:
            cfg = Config(a.config)  # a plan exists: the whole config is validated
        orch = Orchestrator(cfg, a.dry_run)
        result = asyncio.run(dispatch(orch, a.cmd, a))
    except HarnessError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    path = orch.out / f"{a.cmd}-result.json"
    if not a.dry_run:
        write_atomic(path, json.dumps(result, indent=2, default=str) + "\n")
    print(summary_text(result, None if a.dry_run else path))  # the human's view first, the result JSON last
    print(json.dumps(result_doc(a.cmd, result), default=str))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
