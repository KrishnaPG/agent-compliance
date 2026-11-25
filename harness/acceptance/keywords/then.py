"""Then keywords: one assertion per catalog key. A missing thing in the system under test is an AssertionError."""

from __future__ import annotations

import glob as _glob
import hashlib
import json
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

import atdd_engine.teaching as teaching
from atdd_engine.runtime import KeywordError
from support import CONTRACT, catalog_entry, execute, sut_argv, FixtureError, REF, apply_op, get_path, git, globs, missing, need, nonempty, repo, say
from when import BEFORE_WHEN, digests, load_instance, load_schema, run_validation, _front, when_scan

P = CONTRACT["paths"]
R = CONTRACT["refs"]
RJ = CONTRACT["result_json"]


def last(ctx):
    if ctx.last is None:
        raise KeywordError("a then step ran with no when step before it")
    return ctx.last


# ---------- result JSON and its parts ----------

def result(ctx):
    run = last(ctx)
    j = run.extra.get("hook_json") if run.kind == "hook" else run.json
    if j is None:
        missing(f"{run.extra.get('what', run.kind)} printed no result JSON on stdout (exit {run.exit_code})", "print the result JSON on stdout")
    if run.kind != "hook":
        for k in (RJ["schema_version"], RJ["command"]):
            if not (isinstance(j, dict) and j.get(k)):
                missing(f"the result JSON has no `{k}` field", "give every result JSON its schema_version and command")
    return j


def facts(ctx) -> list:
    r = result(ctx)
    if not isinstance(r, dict) or RJ["facts"] not in r:
        missing(f"the result JSON has no `{RJ['facts']}` field", "record facts in the result JSON")
    return r[RJ["facts"]]


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def fact_texts(f) -> list:
    return list(strings(f))


def report_text(ctx) -> str:
    r = result(ctx)
    p = r.get(RJ["run_report"]) if isinstance(r, dict) else None
    cand = [Path(p)] if p else []
    cand.append(repo(ctx) / P["run_report"])
    for c in cand:
        c = c if c.is_absolute() else repo(ctx) / c
        if c.is_file():
            return c.read_text()
    missing(f"the run report {P['run_report']} does not exist", "write the run report next to the result JSON")


def packet_values(ctx) -> dict:
    pk = ctx.state.get("packet")
    if not pk:
        raise FixtureError(say("ATDD-ORDER", "a $placeholder is used with no packet given", "add a packet given", REF))
    return {"packet_sha256": pk["sha256"], "acceptance_ids": ", ".join(a["id"] for a in pk["data"].get("acceptance", []))}


def packet_path(ctx, path):
    """$packet.<path>: the value (or list of values) at a packet path."""
    pk = ctx.state.get("packet")
    if not pk:
        raise FixtureError(say("ATDD-ORDER", "a $packet.<path> placeholder is used with no packet given", "add a packet given", REF))
    try:
        vals = get_path(pk["data"], path)
    except KeyError:
        raise FixtureError(say("ATDD-FIXTURE", f"the packet fixture has no {path}", "add the field to the packet fixture", REF)) from None
    flat = [x for v in vals for x in (v if isinstance(v, list) else [v])]
    return flat if (isinstance(vals[0], list) or len(vals) > 1) else vals[0]


def subst(ctx, v):
    if isinstance(v, str) and v.startswith("$"):
        m = re.fullmatch(r"\$packet\.(\S+)", v)
        if m:
            return packet_path(ctx, m.group(1))
        m = re.fullmatch(r"\$(\w+)", v)
        if m and m.group(1) in ("packet_sha256", "acceptance_ids"):
            return packet_values(ctx)[m.group(1)]
    return v


# ---------- sources for `field` ----------

def load_json_file(p: Path, what: str):
    if not p.is_file():
        missing(f"{what} {p.name} does not exist", f"produce {what}")
    return json.loads(p.read_text())


def source(ctx, name):
    run = ctx.last
    r = repo(ctx) if ctx.state.get("repo") else None
    if name == "result_json":
        return result(ctx)
    if name in ("eval_report", "hook_output"):
        return result(ctx)
    if name == "config_effective":
        res = result(ctx)
        if RJ["config_effective"] not in res:
            missing(f"the result JSON has no `{RJ['config_effective']}` (effective config)", "print the effective config")
        return res[RJ["config_effective"]]
    if name == "packet":
        pk = ctx.state.get("packet")
        if pk and pk["repo_copy"].is_file():
            return json.loads(pk["repo_copy"].read_text())
        files = sorted((r / P["packets_dir"]).glob("*.json")) if r else []
        if not files:
            missing(f"no packet file under {P['packets_dir']}", "write the packet where the program reads packets")
        return json.loads(files[-1].read_text())
    if name == "builder_settings":
        return load_json_file(r / P["builder_settings"], "the generated builder settings")
    if name == "hooks_json":
        return load_json_file(ctx.tree / P["hooks_json"], "hooks/hooks.json")
    if name == "register":
        return load_json_file(r / P["register"], "the safeguard register")
    if name == "manifest":
        return load_json_file(r / P["manifest"], "the manifest")
    if name == "baseline_file":
        d = r / P["baselines_dir"]
        merged = {}
        for f in sorted(d.glob("*")) if d.is_dir() else []:
            try:
                data = json.loads(f.read_text()) if f.suffix == ".json" else tomllib.loads(f.read_text()) if f.suffix == ".toml" else {f.stem.lstrip("."): f.read_text()}
            except ValueError:
                data = {f.stem.lstrip("."): f.read_text()}
            merged.update(data if isinstance(data, dict) else {f.stem: data})
        if not merged:
            missing(f"no ratchet baseline file under {P['baselines_dir']}", "write the baseline files at adoption")
        return merged
    if name == "launch_args":
        log = Path(ctx.state["env"][CONTRACT["env"]["model_log"]])
        if not log.is_file():
            missing("no builder or judge job was launched", "launch the job through `claude`")
        entry = json.loads(log.read_text().splitlines()[-1])
        argv = entry["argv"]
        out = {"argv": argv, "prompt": entry["stdin"] or next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-p", "--print")), "")}
        for i, a in enumerate(argv):
            if a.startswith("--"):
                out[a] = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else True
        return out
    if name == "commit_message":
        full = git(ctx, "log", "-1", "--format=%B").stdout
        subject, _, body = full.partition("\n")
        tr = git(ctx, "interpret-trailers", "--parse", input=full).stdout.splitlines()
        return {"subject": subject, "body": body.strip(), "trailers": tr, "message": full}
    if name == "sarif":
        files = sorted(_glob.glob(str(r / P["sarif_glob"])))
        if not files:
            missing(f"no SARIF log matches {P['sarif_glob']}", "write the SARIF log of the stage")
        return json.loads(Path(files[0]).read_text())
    if name == "skill_md":
        sc = ctx.last.extra
        if "files" not in sc:
            raise KeywordError("skill_md is read after a scan step")
        out = {"files": sc["files"]}
        f = repo(ctx) / sc["files"][0]
        text = f.read_text()
        fm = _front(text)
        out.update(fm)
        out["body"] = text.split("\n---\n", 1)[-1]
        out["references"] = [m for m in re.findall(r"[\w./-]+\.(?:md|py|json|yaml|yml|sh)", text)]
        return out
    if name == "decision_record":
        files = sorted(_glob.glob(str(r / P["decision_glob"])))
        if not files:
            missing(f"no decision record matches {P['decision_glob']}", "write the L1 decision record")
        text = Path(files[-1]).read_text()
        sections = re.findall(r"^#{1,3}\s+(.*)$", text, re.M)
        cons = re.search(r"^#+\s+Constraints?\s*$(.*?)(?=^#+\s|\Z)", text, re.M | re.S)
        constraints = [{"text": ln, "cites": ", ".join(re.findall(r"\b(?:G|P|R)\d+\b|QBC-\d+", ln))} for ln in (cons.group(1).splitlines() if cons else []) if ln.strip().startswith(("-", "*"))]
        return {"front_matter": _front(text), "tracking_issue": _front(text).get("tracking_issue"), "sections": sections, "constraints": constraints}
    raise KeywordError(f"unknown field source {name}")


# ---------- keywords ----------

def special_op(ctx, src, obj, op, values, value):
    r = repo(ctx)
    if op == "in_file":
        f = r / value
        if not f.is_file():
            missing(f"{value} does not exist", f"write {value}")
        body = _norm(f.read_text())
        gone = [v for v in values if _norm(str(v)) not in body]
        return f"{gone[0]!r} is not in {value}" if gone else None
    if op == "covered_by":
        pool = [json.dumps(x, sort_keys=True) for x in get_path(obj, value)]
        gone = [v for v in values if json.dumps(v, sort_keys=True) not in pool]
        return f"{gone[0]!r} is not among the values at {value}" if gone else None
    base = (repo(ctx) / (ctx.last.extra.get("files") or ["."])[0]).parent if src == "skill_md" else repo(ctx)
    gone = [v for v in values if not (base / str(v)).exists()]
    return f"{gone[0]!r} does not exist relative to {base.name}" if gone else None


def then_lines(ctx, channel, pattern, count=None, op=None, every=False):
    run = last(ctx)
    if pattern == "@teaching_shape":
        pattern = r"^\[[^\]]+\] .+ -> .+ \. \S.*$"
    ls = _lines(run.stdout)
    rx = re.compile(pattern)
    n = sum(1 for ln in ls if rx.search(ln))
    if count is not None:
        need(_cmp(op, n, count), f"{n} stdout lines match {pattern!r}, expected {op} {count}", f"make it {op} {count}")
    if every:
        bad = [ln for ln in ls if not rx.search(ln)]
        need(not bad, f"{len(bad)} stdout line(s) do not match {pattern!r}: {bad[:1]}", "make every line match")


def then_exit_code(ctx, code):
    run = last(ctx)
    for x in run.runs or [run]:
        need(x.exit_code == code, f"{run.extra.get('what', run.kind)} exited {x.exit_code}, not {code}", f"make it exit {code}")


def _items(ctx):
    res = result(ctx)
    if RJ["items"] not in res:
        missing(f"the result JSON has no `{RJ['items']}` (per-item status)", "record each item's status in the result JSON")
    return res[RJ["items"]]


def then_met(ctx, status, item=None):
    items = _items(ctx)
    if item is not None:
        sel = [i for i in items if i.get("id") == item]
        need(sel, f"the result JSON has no item {item}", "report every measured item")
    else:
        sel = items
        need(len(sel) == 1, f"the result JSON holds {len(sel)} items, not one", "name the item in the row")
    need(sel[0].get("status") == status, f"item status is {sel[0].get('status')!r}, not {status!r}", f"measure it as {status}")


def _fact_match(ctx, kind, detail=None):
    fs = [f for f in facts(ctx) if isinstance(f, dict) and f.get("kind") == kind]
    if detail is not None:
        fs = [f for f in fs if any(detail.lower() in s.lower() for s in fact_texts(f))]
    return fs


def then_fact(ctx, kind, detail=None, count=None):
    fs = _fact_match(ctx, kind, detail)
    if count is None:
        need(fs, f"no {kind} fact{' containing ' + repr(detail) if detail else ''} in the result JSON", f"record a {kind} fact")
    else:
        need(len(_fact_match(ctx, kind)) == count, f"the result JSON holds {len(_fact_match(ctx, kind))} {kind} facts, not {count}", f"record exactly {count}")
    rep = report_text(ctx)
    need(any(kind.lower() in ln.lower() for ln in rep.splitlines()), f"the run report has no line for the {kind} fact", "list every fact in the run report")


def then_no_fact(ctx, kind):
    need(not _fact_match(ctx, kind), f"a {kind} fact is recorded", f"record none for this case")


def _hook_strings(run):
    return list(strings(run.extra.get("hook_json"))) if run.extra.get("hook_json") is not None else []


def _lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def channel_messages(ctx, channel) -> list:
    run = last(ctx)
    if channel == "stdout":
        return _lines(run.stdout) + ([run.stdout.strip()] if run.stdout.strip() else [])
    if channel == "stderr":
        return _lines(run.stderr) + ([run.stderr.strip()] if run.stderr.strip() else [])
    if channel == "hook_output":
        hj = run.extra.get("hook_json") or run.json
        if hj is None:
            missing("the hook printed no JSON on stdout", "print the hook's JSON on stdout")
        return list(strings(hj))
    if channel == "fact":
        out = []
        for f in facts(ctx):
            out += [s for s in fact_texts(f)] + [" ".join(s for s in fact_texts(f))]
        return out
    if channel == "run_report":
        return _lines(report_text(ctx))
    if channel == "issue_comment":
        out = []
        for e in ctx.state.get("api_log", []):
            if "comment" in e["operation"].lower():
                try:
                    out.append(json.loads(e["body"]).get("body", e["body"]))
                except ValueError:
                    out.append(e["body"])
        return out
    if channel == "tool_result":
        return [run.extra.get("tool_result", run.stdout)]
    if channel == "sarif":
        out = []
        for res in source(ctx, "sarif")["runs"][0].get("results", []):
            rules = {r.get("id"): r for r in source(ctx, "sarif")["runs"][0].get("tool", {}).get("driver", {}).get("rules", [])}
            rule = rules.get(res.get("ruleId"), {})
            parts = [res.get("message", {}).get("text", ""), rule.get("help", {}).get("text", "")] + [f.get("description", {}).get("text", "") for f in res.get("fixes", [])]
            out.append(" ".join(p for p in parts if p))
        return out
    raise KeywordError(f"unknown channel {channel}")


def _teaching_check(msgs, wrong, right, prevent, where):
    need(msgs, f"nothing was written to {where}", "write the teaching message there")
    reasons = []
    for m in msgs:
        why = teaching.match(m, wrong, right, prevent)
        if why is None:
            return
        reasons.append(why)
    need(False, f"no message on {where} teaches: {reasons[0] if reasons else ''}", f"use the shape [rule] wrong -> right . ref with {wrong}")


def then_teaching(ctx, channel, wrong, right, prevent):
    _teaching_check(channel_messages(ctx, channel), wrong, right, prevent, channel)


def then_refused(ctx, by, wrong, right, prevent):
    run = last(ctx)
    ex = run.extra
    if run.kind == "builder_action":
        need(ex.get("refused") and not ex.get("changed"), "the builder's change was not refused", "refuse it before it happens")
        need(ex.get("by") == by, f"it was refused by {ex.get('by')}, not {by}", f"refuse it through the {by}")
    else:
        hj = ex.get("hook_json") if run.kind == "hook" else None
        denied = run.exit_code != 0 or any(w in json.dumps(hj).lower() for w in ("deny", "block"))
        need(denied, f"{ex.get('what', run.kind)} was not refused (exit {run.exit_code})", "refuse it with a non-zero exit or a deny decision")
    msgs = _lines(run.stderr) + _lines(run.stdout) + [run.stderr.strip(), run.stdout.strip()] + _hook_strings(run) + [ex.get("tool_result", "")]
    try:
        msgs += channel_messages(ctx, "fact")
    except AssertionError:
        pass
    _teaching_check([m for m in msgs if m], wrong, right, prevent, "the refusal message")


def _norm(s):
    return " ".join(s.split())


def then_output_contains(ctx, channel, text, max_chars=None, negate=False):
    run = last(ctx)
    if channel == "stdout":
        body = run.stdout
    elif channel == "stderr":
        body = run.stderr
    elif channel == "run_report":
        body = report_text(ctx)
    elif channel == "packet_markdown":
        pk = ctx.state.get("packet")
        f = (repo(ctx) / P["packets_dir"] / f"{pk['id']}.md") if pk else None
        body = f.read_text() if f and f.is_file() else run.stdout
        need(body.strip(), "no rendered packet Markdown was produced", "render the packet to Markdown")
    elif channel == "additional_context":
        hj = run.extra.get("hook_json") or run.json
        if hj is None:
            missing("the hook printed no JSON on stdout", "print the hook's JSON on stdout")
        body = "\n".join(s for s in _find(hj, "additionalContext"))
    else:
        body = "\n".join(channel_messages(ctx, "issue_comment"))
    has = _norm(text) in _norm(body)
    if negate:
        need(not has, f"{channel} contains {text!r}", "remove it")
    else:
        need(has, f"{channel} does not contain {text!r}", "print that text")
        if max_chars is not None:
            need(len(body) <= max_chars, f"the message is {len(body)} characters, over {max_chars}", f"keep it within {max_chars}")


def _find(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                yield v
            yield from _find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find(v, key)


def then_field(ctx, source: str, path, op, value=None):  # noqa: A002
    obj = globals()["source"](ctx, source)
    try:
        values = get_path(obj, path)
    except KeyError:
        if op == "absent":
            return
        missing(f"{source} has no field {path}", f"add {path} to the {source}")
    if op in ("in_file", "covered_by", "exists"):
        why = special_op(ctx, source, obj, op, values, value)
    else:
        why = apply_op(op, values, subst(ctx, value))
    need(why is None, f"{source} {path}: {why}", f"make {path} {op} {value!r}")


def _jobs_list(ctx):
    res = result(ctx)
    if RJ["jobs"] not in res:
        missing(f"the result JSON has no `{RJ['jobs']}`", "record every job in the result JSON")
    return res[RJ["jobs"]]


def _job_name(j):
    """A job's name: its role when kind is agent, its step when kind is program_step."""
    return j.get("role") if j.get("kind") == "agent" else j.get("step")


def then_jobs(ctx, **kw):
    a, values = kw["assert"], kw["values"]
    jobs = _jobs_list(ctx)
    names = [_job_name(j) for j in jobs]
    if a == "order":
        pos, ok = 0, True
        for v in values:
            while pos < len(names) and names[pos] != v:
                pos += 1
            ok = ok and pos < len(names)
            pos += 1
        need(ok, f"job names {names} do not hold {values} in order", "start the jobs in that order")
    elif a == "distinct":
        need(all(names.count(v) >= 1 for v in values) and len({v for v in values}) == len(values), f"{values} are not each a separate job in {names}", "run each as its own job")
    elif a == "present":
        need(all(v in names for v in values), f"no job is named {[v for v in values if v not in names]} in {names}", "run those jobs")
    elif a == "absent":
        need(not any(v in names for v in values), f"jobs named {[v for v in values if v in names]} ran", "run none of them")
    else:  # program_only
        sel = [j for j in jobs if _job_name(j) in values]
        need(sel and all(j.get("kind") == "program_step" for j in sel), f"jobs {values} are not all program steps that ran", "do these steps in the program, with no agent")


def then_file_unchanged(ctx, target):
    run = last(ctx)
    before = (ctx.state.get("after_first") if run.first is not None else ctx.state.get("before")) or {}
    after = digests(ctx)
    need(before.get(target) == after[target], f"{target} changed during the run", f"leave {target} untouched")


def _expand_placeholder(ctx, s):
    """A $packet.<path> placeholder as a list: a match of any one element satisfies a path parameter."""
    if isinstance(s, str) and s.startswith("$packet."):
        v = subst(ctx, s)
        return v if isinstance(v, list) else [v]
    return None


def then_paths(ctx, paths, exist):
    r = repo(ctx)
    for p in paths:
        alt = _expand_placeholder(ctx, p)
        pats = alt if alt is not None else [p]
        hit = any(globs(r, [x]) or (r / x).exists() for x in pats)
        if alt is not None:
            need(hit == exist, f"none of {pats} {'exists' if exist else 'is absent'}", "match the packet's paths")
        else:
            need(hit == exist, f"{p} {'does not exist' if exist else 'exists'}", f"{'create' if exist else 'delete'} {p}")


def _cmp(op, a, b):
    return {"eq": a == b, "lt": a < b, "le": a <= b, "ge": a >= b, "gt": a > b}[op]


def then_scan_count(ctx, op, value, distinct=False):
    run = last(ctx)
    n = run.extra["distinct_count"] if distinct else run.extra["number"]
    need(_cmp(op, n, value), f"the scan found {n} ({run.extra['scan_kind']}), expected {op} {value}: {run.extra['matches'][:3]}", f"make the count {op} {value}")


def then_junit(ctx, tests_min=None, failures=None, errors=None, skipped=None):
    run = last(ctx)
    p = run.extra.get("junit_path") or (repo(ctx) / P["junit"])
    if not Path(p).is_file():
        missing(f"the run wrote no JUnit XML at {Path(p).name}", "write the run's JUnit XML")
    root = ET.parse(p).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tot = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    if tests_min is not None:
        need(tot["tests"] >= tests_min, f"JUnit has {tot['tests']} tests, under {tests_min}", "run the tests")
    for k, v in (("failures", failures), ("errors", errors), ("skipped", skipped)):
        if v is not None:
            need(tot[k] == v, f"JUnit has {tot[k]} {k}, not {v}", f"make {k} {v}")


def metric_value(ctx, metric):
    run = last(ctx)
    if metric == "measure_overhead_s":
        return run.wall_s
    if metric == "longest_message_chars":
        return max([len(s) for f in facts(ctx) for s in fact_texts(f)] or [0])
    if metric in ("skill_description_chars", "skill_chars", "skill_md_chars"):
        return run.extra["number"]
    if metric == "round_spend_usd":
        return sum(get_path_or_missing(result(ctx), "jobs[*].cost_usd"))
    if metric == "planner_fields_tokens":
        pk = source(ctx, "packet")
        mine = [get_path_or_missing(pk, p) for p in ("goal", "applies[*].id", "constraints.decisions[*].id", "constraints.declared_paths[*]")]
        return len(json.dumps(mine, ensure_ascii=False).encode()) / 4
    if metric == "concurrent_agents":
        from datetime import datetime
        agent_jobs = [j for j in _jobs_list(ctx) if j.get("kind") == "agent"]
        ev = []
        for j in agent_jobs:
            for k in ("started_at", "ended_at"):
                if k not in j:
                    missing(f"a job has no {k}", f"record {k} on every job")
            ev += [(datetime.fromisoformat(j["started_at"].replace("Z", "+00:00")), 1), (datetime.fromisoformat(j["ended_at"].replace("Z", "+00:00")), -1)]
        cur = top = 0
        for _, d in sorted(ev, key=lambda e: (e[0], e[1])):
            cur += d
            top = max(top, cur)
        return top
    raise KeywordError(f"metric {metric} is not defined")


def get_path_or_missing(obj, path):
    try:
        return get_path(obj, path)
    except KeyError:
        missing(f"no field {path}", f"add {path} to the result")


def _config_limit(ctx, key, default):
    f = repo(ctx) / P["config_file"]
    if f.is_file():
        try:
            return get_path(json.loads(f.read_text()), key)[0]
        except KeyError:
            pass
    need(default is not None, f"no value or default for {key}", "state the default")
    return default


def then_threshold(ctx, metric, op, bound, default=None):
    value = metric_value(ctx, metric)
    if bound.startswith("ref:"):
        state = bound[4:]
        run = last(ctx)
        dest = ctx.work / f"ref-{state}"
        dest.mkdir(exist_ok=True)
        p = subprocess.run(f"git -C {ctx.tree} archive {state} | tar -x -C {dest}", shell=True, capture_output=True)
        if p.returncode:
            raise FixtureError(say("ATDD-FIXTURE", f"the tree has no git ref {state}", "use a tree with that release tag", REF))
        saved = ctx.state["repo"]
        ctx.state["repo"] = dest
        try:
            ref_run = when_scan(ctx, **run.extra["scan_params"])
        finally:
            ctx.state["repo"] = saved
        limit = ref_run.extra["number"]
    else:
        limit = _config_limit(ctx, bound, default)
    need(_cmp(op, value, limit), f"{metric} is {value}, not {op} {limit} ({bound})", f"bring {metric} {op} {limit}")


def then_snapshot(ctx, name):
    f = ctx.fixtures / "snapshots" / f"{name}.txt"
    need(f.is_file(), f"approved snapshot {name} is missing (it is never recorded automatically)", f"review the output and commit fixtures/snapshots/{name}.txt")
    need(last(ctx).primary.encode() == f.read_bytes(), f"the output differs from snapshot {name}", "fix the output or approve a new snapshot by hand")


def then_schema_valid(ctx, valid, error_path=None, instance=None, schema=None):
    if instance is not None:
        names = {"result_json", "sarif", "manifest", "packet", "job_record", "config_effective", "register"}
        inst = source(ctx, instance) if instance in names else load_instance(ctx, instance)
        errs = run_validation(inst, load_schema(ctx, schema))
    else:
        errs = last(ctx).extra["errors"]
    need((not errs) == valid, f"validation {'failed' if errs else 'passed'}: {errs[0]['message'] if errs else ''}", f"make the instance {'valid' if valid else 'invalid'}")
    if not valid and error_path:
        ep = error_path.lstrip("$.")
        need(any(e["dotted"] == ep or e["dotted"].startswith(ep) or e["path"].endswith(error_path) for e in errs), f"no error points at {error_path}", "report the error at that path")


def _named_result(ctx, name):
    spec = catalog_entry("then", "same_result")["results"][name]
    if "source" in spec:
        obj = source(ctx, spec["source"])
        if spec["source"] == "manifest":
            vals = list(obj) if spec["read"] == "keys" else list(obj.values())
        else:
            vals = get_path_or_missing(obj, spec["read"])
    else:
        r, run = spec["run"], last(ctx)
        if r == "first":
            run = run.first or missing("there is no first run: the row has no rerun", "run the step twice")
        elif r.startswith("parallel_") if isinstance(r, str) else False:
            n = int(r.split("_")[1])
            run = run.runs[n - 1] if len(run.runs) >= n else missing(f"the step ran {len(run.runs)} time(s), not {n}", "run it with parallel: 2")
        elif isinstance(r, dict):
            run = execute(ctx, sut_argv(ctx, CONTRACT["argv"]["bh"]) + [r["bh"]])
        j = run.json
        if j is None:
            missing(f"{' '.join(run.argv[-2:])} printed no result JSON on stdout (exit {run.exit_code})", "print the result JSON on stdout")
        vals = get_path_or_missing(j, spec["read"])
    return list(dict.fromkeys(json.dumps(v, sort_keys=True) for v in vals)) if spec.get("distinct") else [json.dumps(v, sort_keys=True) for v in vals]


def then_same_result(ctx, a, b, compare):
    x, y = _named_result(ctx, a), _named_result(ctx, b)
    if compare == "equal":
        need(x == y, f"{a} is {x}, {b} is {y}", f"make {a} and {b} equal")
    else:
        need(x and y, f"{a} or {b} holds no entry to compare", f"record entries in {a} and {b}")
        need(not set(x) & set(y), f"{a} and {b} share {sorted(set(x) & set(y))}", f"keep {a} and {b} separate")


def then_git(ctx, **kw):
    a = kw["assert"]
    r = repo(ctx)
    if a == "candidate_not_in_head":
        need(git(ctx, "merge-base", "--is-ancestor", R["candidate_branch"], "HEAD", check=False).returncode != 0, "the candidate commit is reachable from HEAD", "merge only after measuring")
    elif a == "merge_is_one_commit":
        n = int(git(ctx, "rev-list", "--count", f"{ctx.state['head_before']}..HEAD").stdout)
        need(n == 1, f"the merge added {n} commits", "add exactly one")
    elif a == "source_refs_unchanged":
        need(git(ctx, "for-each-ref", "--format=%(refname) %(objectname)").stdout == ctx.state["refs_before"], "the source repository's refs changed", "never move the source's refs")
    elif a == "no_git_hook_installed":
        hooks = [h for h in (r / ".git" / "hooks").glob("*") if not h.name.endswith(".sample")] if (r / ".git" / "hooks").is_dir() else []
        for c in globs(r, [P["clones_dir"] + "/*"]):
            hooks += [h for h in (c / ".git" / "hooks").glob("*") if not h.name.endswith(".sample")] if (c / ".git" / "hooks").is_dir() else []
        need(not hooks, f"git hooks are installed: {[h.name for h in hooks]}", "install none")
    elif a in ("clone_is_shared_from_base", "no_remote_fetch"):
        clones = [c for c in globs(r, [P["clones_dir"] + "/*"]) if c.is_dir()]
        if not clones:
            missing(f"no clone under {P['clones_dir']}", "make the measured clone there")
        c = clones[0]
        if a == "clone_is_shared_from_base":
            alt = c / ".git" / "objects" / "info" / "alternates"
            need(alt.is_file(), "the clone has no objects/info/alternates (it was not made with --shared)", "use `git clone --shared`")
            base = git(ctx, "rev-parse", R["base_tag"]).stdout.strip()
            need(subprocess.run(["git", "-C", str(c), "cat-file", "-e", base], capture_output=True).returncode == 0, "the base commit is not in the clone", "clone from the base commit")
        else:
            need(not (c / ".git" / "FETCH_HEAD").exists(), "the clone fetched from a remote", "clone locally only")
    elif a == "conflict_names_item":
        item = ctx.last.argv[-1] if ctx.last.argv else ""
        txt = ctx.last.stdout + ctx.last.stderr + json.dumps(ctx.last.json or {})
        need(item and item in txt, "the conflict message does not name the item", "name the item in the message")
    elif a == "unmerged_empty":
        need(not git(ctx, "ls-files", "-u").stdout.strip(), "unmerged paths remain", "leave none")
    elif a == "committed_by_program":
        who = git(ctx, "log", "-1", "--format=%an|%cn").stdout.strip()
        need(CONTRACT["program_identity"] in who.lower().split("|")[0], f"the commit was made by {who}, not the program", "commit as the program")
    elif a == "path_in_plan_commit":
        pats = _expand_placeholder(ctx, kw["path"]) or [kw["path"]]
        files = git(ctx, "show", "--name-only", "--format=", R["plan_ref"]).stdout.split()
        from fnmatch import fnmatch

        need(any(fnmatch(f, p) for f in files for p in pats), f"the plan commit holds no file matching {pats}", "add it to the plan commit")


def then_api_call(ctx, service, operation, count, **kw):
    log = [e for e in ctx.state.get("api_log", []) if e["service"] == service and e["operation"] == operation]
    w = kw.get("with")
    if w:
        log = [e for e in log if w in e["body"] or w in e["path"]]
    need(len(log) == count, f"{len(log)} {service} {operation} requests, not {count}", f"make exactly {count}")


def then_file_contains(ctx, path, text, regex=False, negate=False):
    f = repo(ctx) / path
    if not f.is_file():
        missing(f"{path} does not exist", f"write {path}")
    body = f.read_text()
    has = re.search(text, body) is not None if regex else text in body
    need(has != negate, f"{path} {'contains' if negate else 'lacks'} {text!r}", "fix the file")


def then_questions_asked(ctx, count):
    f = Path(ctx.state["env"][CONTRACT["env"]["prompt_log"]])
    n = len([ln for ln in f.read_text().splitlines() if ln.strip()]) if f.is_file() else 0
    need(n == count, f"{n} questions were put to the owner, not {count}", f"ask exactly {count}")


def then_needs_keyword(ctx, reason):
    raise KeywordError(say("ATDD-NEEDS", "this row has no catalog keyword for part of its criterion", "add the keyword to the catalog", "docs/atdd/catalog.yaml"))


THEN = {"lines": then_lines, "exit_code": then_exit_code, "met": then_met, "fact": then_fact, "no_fact": then_no_fact, "refused": then_refused, "teaching": then_teaching, "output_contains": then_output_contains, "field": then_field, "jobs": then_jobs, "file_unchanged": then_file_unchanged, "paths": then_paths, "scan_count": then_scan_count, "junit": then_junit, "threshold": then_threshold, "snapshot": then_snapshot, "schema_valid": then_schema_valid, "same_result": then_same_result, "git": then_git, "api_call": then_api_call, "file_contains": then_file_contains, "questions_asked": then_questions_asked, "needs_keyword": then_needs_keyword}
