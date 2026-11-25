"""The harness orchestrator: a program that runs every mechanical step and starts an agent job
only for judgement work.

Mechanical steps (git worktrees and branches, state, measuring, merging, committing, gap
merging, tracker reconcile and admit, ordering) run here, through the ``bhcore`` and
``bhtracker`` Python API or the ``bh-measure`` CLI (one process per item, so measuring runs in
parallel). An agent job is started for exactly six kinds of work: ``gaps`` (read documents for
meaning), ``plan`` (derive items, targets, contracts), ``build`` (one item, in its own
worktree), ``harvest_find`` (duplicate helpers), ``harvest_apply`` (apply a settled pick) and
``review`` (a feature that became sellable). Nothing else ever reaches a model.

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
``hashlib``, ``argparse``, ``shutil.which`` (stdlib), ``git worktree`` (git; used for the item
worktrees instead of any worktree helper), ``bhcore.validate`` (the harness's own schema
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
import bhpacket
import bhtracker
from bhcore import Config, HarnessError

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PLUGIN_ROOT / "agents"
AGENT_PREFIX = "agent-compliance:"  # the plugin name: plugin agents are namespaced by it
SKILLS = {  # the judging method and skill files an agent reads by path (a headless job may have skills disabled)
    "method": PLUGIN_ROOT / "catalog" / "method.md",
    "vet-oss": PLUGIN_ROOT / "skills" / "vet-oss" / "SKILL.md",
}
JOBS: dict[str, tuple[str, str]] = {  # job -> (agent, config phase for model/effort override)
    "gaps": ("harness-gaps-reader", "gaps"),
    "plan": ("harness-planner", "plan"),
    "build": ("harness-builder", "build"),
    "harvest_find": ("harness-harvester", "harvest"),
    "harvest_apply": ("harness-builder", "harvest"),
    "review": ("harness-reviewer", "review"),
    "test_author": ("harness-test-author", "test_author"),
    "regression_row": (
        "harness-reviewer",
        "test_author",
    ),  # a defect the reviewer found: the reviewer writes its row
}
ROLE = {  # job -> jobs[*].role
    "plan": "planner",
    "build": "builder",
    "review": "reviewer",
    "test_author": "test_author",
    "regression_row": "reviewer",
}
READ_ONLY_BASH = ["Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)"]
REMEASURE = ("unmeasured", "stale", "conflict", "met-uncommitted")  # no current measurement
DEFAULT_JOB_USD = 2.0
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
    rows = json.loads((PLUGIN_ROOT / "docs" / "atdd" / "criteria.schema.json").read_text())["$defs"]
    defs = {
        **doc["$defs"],
        "finding": bhcore.load_schema("finding")["$defs"]["finding"],
        **{k: rows[k] for k in ("row", "given", "when", "then")},  # the one row definition
    }

    def inline(n: Any) -> Any:
        if isinstance(n, dict):
            if "$ref" in n:
                return inline(defs[n["$ref"].rsplit("/", 1)[-1]])
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
        self.records.append(rec)
        if res["ok"]:
            write_atomic(
                done, json.dumps({"record": rec, "output": res["output"]}, indent=2) + "\n"
            )
        else:
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
            "errors": (it or {}).get("errors") or [run.get("error", "no result")],
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
        if refs is None:  # standalone: whatever is ready at HEAD (e.g. work committed by hand)
            done = {r["item"] for r in out["remeasured"]}
            s = self.state()
            out["remeasured"] += await self.measure_all(
                [(b["id"], "HEAD") for b in s["bricks"] if b["ready"] and b["id"] not in done]
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
            "skills": {"method": str(SKILLS["method"])},
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
            "skills": {"method": str(SKILLS["method"])},
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
        j = await self.job(
            "plan", "derive plan", core, extra, "Derive the plan files from the documents."
        )
        if j.get("dry_run"):
            return {"dry_run": True, "job": j}
        if not j["ok"]:
            return {"error": j.get("error", "plan job failed"), "reconcile": rec, "admit": adm}
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

    # ------------------------------------------------------------ phase: build

    def worktree(self, name: str, base: str) -> Path:
        path = self.out / "worktrees" / name
        if path.exists():
            git(self.top, "worktree", "remove", "--force", str(path), check=False)
        git(self.top, "worktree", "prune")
        path.parent.mkdir(parents=True, exist_ok=True)
        git(self.top, "worktree", "add", "--detach", str(path), base)
        return path

    def drop_worktree(self, path: Path) -> None:
        git(self.top, "worktree", "remove", "--force", str(path), check=False)

    def feedback(self, b: dict[str, Any]) -> dict[str, Any] | None:
        last = b.get("last")
        if not last:
            return None
        return {
            "previous_ref": last["ref"],
            "measurer_status": last["status"],
            "unmet": [
                f"{u['metric']}: actual {'not measured' if u['actual'] is None else u['actual']}, "
                f"required {u['op']} {u['value']}"
                for u in last.get("unmet", [])
            ],
            "measurer_errors": last.get("errors", []),
        }

    def fill(self, template: str, slot: int) -> str:
        sl = self.cfg.data.get("slots", {})
        port = sl.get("port_base", 20000) + slot * sl.get("port_stride", 100)
        return template.replace("{slot}", str(slot)).replace("{port_base}", str(port))

    def commands_for(self, s: dict[str, Any], item: str, slot: int) -> dict[str, str]:
        out = {}
        for k, v in (s["commands"].get(item) or {}).items():
            if k not in ("env_setup", "test", "bench"):
                continue
            v = {"run": v} if isinstance(v, str) else v
            out[k] = (
                f"pending ({v['pending']}); the measurer cannot score it yet"
                if v.get("pending")
                else self.fill(v["run"], slot)
            )
        return out

    def item_key(self, item: str) -> str:
        """What a build of ``item`` depends on: its own and its dependencies' files and the
        protected paths at HEAD (blob shas, from ``git ls-tree``), and its targets. Other items
        and the harness's own reports (scoreboard, gaps) do not move it, so a second process
        over the same code finds the first one's builder result. Same file set as
        ``bhcore.tree_key`` less the result files, which change on every run."""
        top, cfg = self.top, self.cfg
        bricks, targets, _ = bhcore._load_plan(cfg, [])
        by_id = {b["id"]: b for b in bricks}
        spec = bhcore._item_pathspec(cfg, top, by_id, item)
        pats = [p for p in spec if not p.startswith(":(")]
        excl = [p[len(":(exclude)") :] for p in spec if p.startswith(":(exclude)")]
        excl += bhcore._keyed(cfg, bhcore.RESULT_KEYS, top)
        mine = {
            n: b
            for n, b in bhcore._tree_files(top, "HEAD").items()
            if bhcore._matches(n, pats) and not bhcore._matches(n, excl)
        }
        return bhcore.digest(
            [sorted(mine.items()), bhcore.target_digest(cfg, by_id[item], targets)]
        )

    async def build_one(self, s: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        item, head = b["id"], s["head"]
        fb = self.feedback(b)
        packet = bhcore.work_packet(self.cfg, item)
        pfile = self.jobs_dir / f"{item}.{sha(packet['text'])}.packet.md"
        core = {
            "task": "build",
            "item": item,
            "tree": self.item_key(item),
            "feedback": fb,
            "packet_sha": sha(packet["text"]),
            "protected": self.cfg.data.get("protected", []),
            "catalogue": (s["files"].get("catalogue") or {}).get("rel"),
            "commands": s["commands"].get(item),
            "skills": {"vet-oss": str(SKILLS["vet-oss"])},
        }
        rec: dict[str, Any] = {"item": item, "ok": False}
        cached = (self.jobs_dir / f"{job_key('build', core)}.json").exists()
        wt = None
        async with self.sem_slot() as slot:
            if not cached and not self.dry:
                write_atomic(pfile, packet["text"])
                wt = self.worktree(item, head)
                prev = (fb or {}).get("previous_ref")
                if (
                    prev
                    and SHA_RE.match(prev)
                    and git(self.top, "cat-file", "-e", prev, check=False).returncode == 0
                ):
                    git(
                        wt, "merge", "--no-edit", prev, check=False
                    )  # a conflict is the builder's to resolve
            extra = {
                "work_packet": str(pfile),
                "worktree": str(wt) if wt else None,
                "slot": slot,
                "commands_for_your_slot": self.commands_for(s, item, slot),
                "started_from": head,
                "plan_commit": s["plan_head"],
            }
            instruction = f"Build item {item} in your worktree (your working directory). Work packet: {pfile}."
            j = await self.job(
                "build",
                item,
                core,
                extra,
                instruction,
                cwd=wt if wt else self.cfg.dir,
                locked=True,
            )
        rec["job"] = {k: j.get(k) for k in ("key", "ok", "error", "skipped")}
        if j.get("dry_run") or not j["ok"]:
            return rec | {"error": j.get("error"), "dry_run": j.get("dry_run")}
        out = j["output"]
        rec["missing_context"] = out.get("missing_context", [])
        rec["catalogue_added"] = out.get("catalogue_added", [])
        ref = git(wt, "rev-parse", "HEAD").stdout.strip() if wt and wt.exists() else out["ref"]
        if wt and wt.exists() and git(wt, "status", "--porcelain").stdout.strip():
            rec["notes"] = "uncommitted changes in the worktree were not part of the commit"
        if ref == head or ref == s["plan_head"]:
            rec.update(ok=True, nochange=True, ref="HEAD")
        else:
            try:
                bhcore.set_branch(self.cfg, item, ref)
                rec.update(ok=True, ref=ref)
            except HarnessError as e:
                rec["error"] = f"branch bh/{item} not set: {e}"
                self.errors.append(rec["error"])
                return rec
        if wt:
            self.drop_worktree(wt)
        return rec

    def sem_slot(self) -> Any:
        """``async with`` over the concurrency semaphore that yields a free slot number."""
        orch = self

        class _Slot:
            async def __aenter__(self) -> int:
                await orch.sem.acquire()
                self.slot = orch.free_slots.pop()
                return self.slot

            async def __aexit__(self, *a: Any) -> None:
                orch.free_slots.append(self.slot)
                orch.sem.release()

        return _Slot()

    async def phase_build(self, only: list[str] | None = None) -> dict[str, Any]:
        s = self.state()
        ready = s["ready"] + s["ready_system"]  # system items: wiring code and end-to-end tests
        todo = [i for i in (only or ready) if i in ready]
        skipped = [i for i in (only or []) if i not in ready]
        res: dict[str, Any] = {
            "refs": [],
            "failed": [],
            "nochange": [],
            "attempted": todo,
            "skipped": skipped,
        }
        if not todo:
            return res
        if s["uncommitted"] and not self.dry:  # builders fork from HEAD: the plan must be in it
            self.commit("plan before build")
            s = self.state()
            if s["uncommitted"]:
                return {
                    **res,
                    "failed": todo,
                    "error": f"plan files still uncommitted: {s['uncommitted']}",
                }
        by_id = {b["id"]: b for b in s["bricks"]}
        # Measure at HEAD first: code that already exists may be met; only the unmet get a builder.
        pre = [i for i in todo if by_id[i]["status"] in REMEASURE]
        res["measured_head"] = await self.measure_all([(i, "HEAD") for i in pre]) if pre else []
        if pre and not self.dry:
            self.commit("scoreboard")
            s = self.state()
            by_id = {b["id"]: b for b in s["bricks"]}
        met = {m["item"] for m in res["measured_head"] if m["status"] in ("met", "met-uncommitted")}
        now_ready = set(s["ready"] + s["ready_system"])
        to_build = [i for i in todo if i not in met and i in now_ready]
        if not to_build:
            return res
        built = await asyncio.gather(*(self.build_one(s, by_id[i]) for i in to_build))
        res["built"], res["missing_context"] = built, []
        for r in built:
            if r.get("dry_run"):
                continue
            if not r.get("ok"):
                res["failed"].append(r["item"])
                continue
            if r.get("nochange"):
                res["nochange"].append(r["item"])
            res["refs"].append({"ref": r["ref"], "items": [r["item"]]})
            res["missing_context"] += [
                {
                    "summary": f"missing context for {r['item']}: {m}",
                    "kind": "missing-context",
                    "source": "build",
                    "impact": [r["item"]],
                }
                for m in r.get("missing_context", [])
            ]
        if res["missing_context"] and not self.dry:
            try:
                bhcore.add_findings(self.cfg, res["missing_context"], write=True)
            except HarnessError as e:
                self.errors.append(f"missing-context findings not recorded: {e}")
        return res

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
            "items_file": (s["files"].get("bricks") or {}).get("rel"),
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
        commit = self.commit("harvest gaps")
        self.tracker("reconcile")
        head = (commit or {}).get("head") or s["head"]
        applied = await asyncio.gather(*(self.apply_one(s, c, head) for c in todo))
        refs = [{"ref": a["ref"]} for a in applied if a.get("ok")]
        return {
            "candidates": cands,
            "reported": len(open_),
            "rejected": report.get("rejected", []),
            "applied": applied,
            "refs": refs,
            "settled": len(todo),
        }

    async def apply_one(self, s: dict[str, Any], c: dict[str, Any], head: str) -> dict[str, Any]:
        core = {
            "task": "harvest_apply",
            "candidate": c,
            "catalogue": (s["files"].get("catalogue") or {}).get("rel"),
            "items_file": (s["files"].get("bricks") or {}).get("rel"),
            "tests": {
                i: (s["merged"]["commands"].get(i) or s["commands"].get(i) or {}).get("test")
                for i in c["bricks"]
            },
            "protected": self.cfg.data.get("protected", []),
            "started_from": head,
        }
        wt = None
        if not self.dry:
            wt = self.worktree("harvest-" + sha(c), head)
        j = await self.job(
            "harvest_apply",
            c["job"],
            core,
            {},
            "Apply the settled helper pick in your worktree.",
            cwd=wt if wt else self.cfg.dir,
        )
        if j.get("dry_run") or not j["ok"]:
            return {"candidate": c["job"], "ok": False, "error": j.get("error")}
        ref = git(wt, "rev-parse", "HEAD").stdout.strip() if wt else j["output"]["ref"]
        if wt:
            git(
                self.top, "update-ref", f"refs/heads/bh/harvest-{sha(c)}", ref
            )  # keep the commit reachable
            self.drop_worktree(wt)
        return {"candidate": c["job"], "ok": ref != head, "ref": ref}

    # ------------------------------------------------------------ phase: review

    async def phase_review(self, features: list[str]) -> list[dict[str, Any]]:
        import bhrules

        out = []
        for f in features:
            try:
                fr = bhrules.feature_review(self.cfg, f)
            except HarnessError as e:
                out.append({"feature": f, "error": str(e)})
                continue
            core = {
                "task": "review",
                "feature": fr,
                "skills": {"method": str(SKILLS["method"])},
            }
            j = await self.job(
                "review",
                f"review {f}",
                core,
                {},
                f"Review the diff of feature {f}, which became sellable.",
            )
            if j.get("dry_run"):
                out.append({"feature": f, "dry_run": True})
                continue
            if not j["ok"]:
                out.append({"feature": f, "error": j.get("error")})
                continue
            found = [{**x, "source": "sellable-review"} for x in j["output"]["findings"]]
            rec = None
            if found:
                try:
                    bhcore.add_findings(self.cfg, found, write=True)
                    rec = True
                except HarnessError as e:
                    rec = False
                    self.errors.append(f"review findings of {f} not recorded: {e}")
            out.append({"feature": f, "findings": len(found), "recorded": rec})
        return out

    # ------------------------------------------------------------ the run

    async def run(self, skip: list[str] | None = None) -> dict[str, Any]:
        cfg, skip = self.cfg, skip or []
        res: dict[str, Any] = {
            "dry_run": self.dry,
            "gaps": None,
            "plan": None,
            "rounds": [],
            "harvest": None,
            "stopped": None,
        }
        s0 = self.state()
        sellable0 = set(s0["value"]["sellable_at_head"])
        if "gaps" not in skip:
            res["gaps"] = await self.phase_gaps()
        if "plan" not in skip:
            res["plan"] = await self.phase_plan()
        max_rounds = 1 if self.dry else int(cfg.data.get("max_rounds", 3))
        why: dict[str, str] = {}
        budgets = cfg.data.get("budgets", {})
        for n in range(1, max_rounds + 1):
            s = self.state()
            if not (s["ready"] or s["ready_system"] or s["unmerged"]):
                break
            if self.over_budget(budgets):
                res["stopped"] = "budget"
                break
            before = fingerprint(cfg)
            b = await self.phase_build()
            for r in b.get("refs", []):
                why.update({i: "unmet" for i in r["items"]})
            why.update({i: "no-change" for i in b.get("nochange", [])})
            why.update({i: "build-failed" for i in b.get("failed", [])})
            m = await self.phase_measure(b.get("refs", []))
            res["rounds"].append({"round": n, "build": b, "measure": m})
            if self.dry:
                break
            if fingerprint(cfg) == before:  # W6: no measured number moved
                res["stopped"] = res["stopped"] or "no progress"
                break
        if not self.dry:
            self.tracker("reconcile")
        s = self.state()
        halted = self.over_budget(budgets)  # a spent budget starts no further job
        if halted:
            res["stopped"] = "budget" if res["stopped"] in (None, "budget") else res["stopped"]
            res["not_run_for_budget"] = ["reviews", "harvest"]
        became = [f for f in s["value"]["sellable_at_head"] if f not in sellable0]
        res["reviews"] = await self.phase_review(became) if not (self.dry or halted) else []
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
            if h.get("refs"):
                h["measured"] = await self.phase_measure(h["refs"])
            res["harvest"] = h
            self.tracker("reconcile")
        return self.finish(res, cyc, sellable0)

    # ------------------------------------------------------------ packets: the test author goes first (d6)

    async def run_packets(self, items: list[str]) -> dict[str, Any]:
        """The packet flow of one run: for each item the test author (or, for a defect found by an agent
        other than the builder, that agent) writes the acceptance rows, the generator turns them into the
        collected tests, the red run on main is recorded, then the builder and the measurer run. A row that
        errors goes back to the author; the rounds are capped by ``max_rounds``."""
        facts: list[dict[str, Any]] = []
        status: dict[str, str] = {}
        for item in items:
            status[item] = await self.packet_flow(item, facts)
        write_atomic(
            self.top / bhpacket.RUN_REPORT, "".join(f"{f['kind']}: {f['detail']}\n" for f in facts)
        )
        return {
            "schema_version": bhpacket.RESULT_VERSION,
            "command": "run",
            "facts": facts,
            "items": [{"id": i, "status": st} for i, st in status.items()],
            "jobs": self.job_table(),
            "errors": self.errors,
        }

    def program_step(
        self, name: str, item: str, started: datetime, digest: str, code: int = 0
    ) -> None:
        self.records.append(bhpacket.program_job(name, item, started, digest, code))

    async def packet_flow(self, item: str, facts: list[dict[str, Any]]) -> str:
        import bhtests

        root = self.top
        packet, raw = bhpacket.load_packet(root, item)
        defect = packet.get("kind") == "defect"
        job = "regression_row" if defect and packet.get("found_by") == "reviewer" else "test_author"
        feedback: list[dict[str, str]] = []
        for rnd in range(1, int(self.cfg.data.get("max_rounds", 3)) + 1):
            core = {
                "task": job,
                "item": item,
                "packet": packet,
                "feedback": feedback,
                "catalog": str(PLUGIN_ROOT / "docs" / "atdd" / "catalog.yaml"),
            }
            j = await self.job(
                job,
                f"{item}:{rnd}",
                core,
                {},
                f"Write the acceptance rows of packet {item}.",
                cwd=root,
            )
            if not j["ok"]:
                return "unmet"
            packet = {**packet, "acceptance": j["output"]["acceptance"]}
            errs = bhpacket.validate_packet(packet)
            if (
                errs
            ):  # the rows are outside the closed catalog: back to the author with the teaching
                facts += [
                    {"kind": "gap", "item": item, "detail": bhpacket.teaching(e)} for e in errs[:5]
                ]
                feedback = [{"id": item, "error": bhpacket.teaching(e)} for e in errs[:5]]
                packet = bhpacket.load_packet(root, item)[0]
                continue
            write_atomic(bhpacket.packet_path(root, item), json.dumps(packet, indent=2) + "\n")
            t0 = datetime.now(UTC)
            code, out, err = bhpacket.generate_tests(root, item)
            res = (
                json.loads(out)
                if code == 0
                else {"facts": [{"kind": "gap", "item": item, "detail": err.strip()}]}
            )
            facts += res["facts"]
            digest = res.get("packet_sha256", "")
            self.program_step("generator", item, t0, digest, code)
            if code:
                return "unmet"
            red = bhtests.red_facts(
                packet,
                bhtests.run_rows(root, packet),
                git(root, "rev-parse", "HEAD").stdout.strip(),
            )
            facts += red
            errored = [f for f in red if f["kind"] == "red_by_error"]
            if not errored:
                break
            feedback = [{"id": f["detail"].split()[0], "error": f["detail"]} for f in errored]
        else:
            facts.append(
                {
                    "kind": "stuck",
                    "item": item,
                    "detail": f"{item} rows still error on main after {rnd} rounds",
                }
            )
            return "stuck"
        t0 = datetime.now(UTC)
        code, out, err = bhpacket.launch_builder(root, item)
        built = (
            json.loads(out)
            if code == 0
            else {"facts": [{"kind": "gap", "item": item, "detail": err.strip()}], "jobs": []}
        )
        facts += built["facts"]
        self.records += built["jobs"]
        if code:
            return "unmet"
        return self.measure_packet(root, packet, facts)

    def measure_packet(
        self, root: Path, packet: dict[str, Any], facts: list[dict[str, Any]]
    ) -> str:
        """The measurer step for a packet: the builder's commit is fetched into the repository (a ref
        the builder cannot move) and measured by the one measurer, ``bhcore.measure_ref``, against the
        packet kept in custody; met when the measurer says met."""
        item, t0 = packet["id"], datetime.now(UTC)
        clones = sorted(
            (root / bhpacket.CLONES_DIR).glob(f"{item}-*"), key=lambda p: p.stat().st_mtime
        )
        digest = bhpacket.hashlib.sha256(bhpacket.packet_path(root, item).read_bytes()).hexdigest()
        met = False
        if clones:
            ref = f"refs/bh/{item}"
            git(root, "fetch", "-q", str(clones[-1]), f"+HEAD:{ref}")
            res = bhcore.measure_ref(self.cfg, ref, packet=digest, orch=root)
            facts += res["facts"]
            met = res["items"][0]["status"] == "met"
        if met and packet.get("kind") == "defect":
            facts.append(
                {
                    "kind": "regression_recorded",
                    "item": item,
                    "detail": f"the packet's rows pass at the builder's result {item}",
                }
            )
        self.program_step("measurer", item, t0, digest)
        return "met" if met else "unmet"

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
        questions = []
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
    if r["owner_questions"]:
        lines.append(f"OWNER QUESTIONS ({len(r['owner_questions'])})")
        lines += [f"  {q['id']}: {q['summary']}" for q in r["owner_questions"][:20]]
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
        lines.append(
            f"  {j['label']}: {'ok' if j.get('ok') else 'FAILED'}{note} ${c:.4f} {sum((j.get('tokens') or {}).values())} tok [{j.get('mode')}]"
        )
    for e in r["errors"][:10]:
        lines.append(f"ERROR {e}")
    if path:
        lines.append(f"result: {path}")
    return "\n".join(lines)


async def dispatch(orch: Orchestrator, cmd: str, a: argparse.Namespace) -> dict[str, Any]:
    if cmd == "run":
        return await orch.run(a.skip)
    s0 = orch.state()
    sellable0 = set(s0["value"]["sellable_at_head"])
    phases: dict[str, Any]
    if cmd == "gaps":
        phases = {"gaps": await orch.phase_gaps()}
    elif cmd == "plan":
        phases = {"plan": await orch.phase_plan()}
    elif cmd == "build":
        phases = {"build": await orch.phase_build(a.item or None)}
    elif cmd == "measure":
        refs = [
            {"ref": r.partition("@")[2] or "HEAD", "items": [r.partition("@")[0]]}
            for r in a.item or []
        ]
        phases = {"measure": await orch.phase_measure(refs or None)}
    elif cmd == "harvest":
        h = await orch.phase_harvest()
        if h.get("refs"):
            h["measured"] = await orch.phase_measure(h["refs"])
        phases = {"harvest": h}
    else:
        raise HarnessError(f"unknown command {cmd}")
    s = orch.state()
    return orch.compose(phases, s, [], 0, sellable0)


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
    r = sub.add_parser("run", parents=[common], help="gaps, plan, build+measure rounds, harvest")
    r.add_argument("--skip", nargs="*", default=[], choices=["gaps", "plan", "harvest"])
    sub.add_parser("gaps", parents=[common], help="find spec gaps")
    sub.add_parser("plan", parents=[common], help="derive items, targets, contracts")
    b = sub.add_parser("build", parents=[common], help="build the ready items (one round)")
    b.add_argument("--item", action="append", help="only this item (repeatable)")
    m = sub.add_parser(
        "measure", parents=[common], help="measure ITEM@REF (repeatable), merge, re-measure"
    )
    m.add_argument("--item", action="append", help="ID[@REF]; none: the ready items at HEAD")
    sub.add_parser("harvest", parents=[common], help="find duplicated helpers; apply settled picks")
    st = sub.add_parser("step", help="run one program step with no agent and no config")
    st.add_argument("name", choices=bhpacket.STEPS)
    st.add_argument("--item")  # required by every step but merge
    a = ap.parse_args(argv)
    if a.cmd == "step":  # a program step reads only its packet: no orchestrator, no config
        return bhpacket.run_step(a.name, a.item)
    try:
        bare = a.cmd == "measure" and not a.item
        cfg = Config(a.config, partial=bare)  # a bare measurement reads the file as an override
        bricks = cfg.file("bricks")
        if bare and not (bricks and bricks.exists()):
            res = bhcore.measure_ref(cfg, packet=os.environ.get("BH_PACKET_SHA256"))  # no plan: measure HEAD against its plan commit
            for f in res["facts"]:  # the teaching lines first, the result JSON last
                print(f["message"])
            print(json.dumps(res))
            return 0 if all(i["status"] == "met" for i in res["items"]) else 1
        if bare:
            cfg = Config(a.config)  # a plan exists: the whole config is validated
        orch = Orchestrator(cfg, a.dry_run)
        packets = sorted(p.stem for p in (orch.top / bhpacket.PACKETS_DIR).glob("*.json"))
        if a.cmd == "run" and packets:  # the packet flow: the test author goes first
            result = asyncio.run(orch.run_packets(packets))
        else:
            result = asyncio.run(dispatch(orch, a.cmd, a))
    except HarnessError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    path = orch.out / f"{a.cmd}-result.json"
    if not a.dry_run:
        write_atomic(path, json.dumps(result, indent=2, default=str) + "\n")
    print(summary_text(result, None if a.dry_run else path))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
