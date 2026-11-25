"""When keywords: run the system under test once and capture what it did."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from support import (CONTRACT, FixtureError, REF, Run, base_env, digest_files, execute, fixture_data, git, globs, missing, need, parallel, repo, say, sut_argv, tree_files, writable_repo)

P = CONTRACT["paths"]
R = CONTRACT["refs"]
UNKNOWN_SUB = re.compile(r"invalid choice|unrecognized|unknown (sub)?command|no such command|usage:", re.I)


# ---------- digests of the things file_unchanged compares ----------

def packet_acceptance_files(ctx) -> list:
    r = repo(ctx)
    pk = ctx.state.get("packet")
    pats = (pk or {}).get("data", {}).get("verifier", {}).get("acceptance_paths") or ["tests/**/*.py"]
    return globs(r, pats)


def digests(ctx) -> dict:
    r = repo(ctx)
    out = {}
    pk = ctx.state.get("packet")
    out["orchestrator_packet"] = digest_files([pk["orchestrator"]] if pk else tree_files(ctx.work / "orchestrator"))
    out["source_refs"] = git(ctx, "for-each-ref", "--format=%(refname) %(objectname)", cwd=ctx.state.get("source_repo", r), check=False).stdout if (r / ".git").exists() or ctx.state.get("source_repo") else ""
    out["outside_checkout"] = digest_files(tree_files(ctx.work / "outside"))
    out["acceptance_tests"] = digest_files(packet_acceptance_files(ctx))
    out["project_config"] = digest_files([r / f for f in CONTRACT["project_config_files"]])
    out["plugin_files"] = digest_files(tree_files(ctx.tree))
    recipes = []
    if (r / ".git").exists():
        for f in CONTRACT["recipes"]:
            s = git(ctx, "show", f"{R['base_tag']}:{f}", check=False)
            if s.returncode == 0:
                recipes.append(f + s.stdout)
    out["base_recipe"] = "\n".join(recipes)
    out["baseline_file"] = digest_files(tree_files(r / P["baselines_dir"]))
    return out


def BEFORE_WHEN(ctx):
    if ctx.state.get("repo") is None:
        return
    ctx.state["before"] = digests(ctx)
    if (repo(ctx) / ".git").exists():
        ctx.state["head_before"] = git(ctx, "rev-parse", "HEAD", check=False).stdout.strip()
        ctx.state["refs_before"] = git(ctx, "for-each-ref", "--format=%(refname) %(objectname)", check=False).stdout


# ---------- bh and program steps ----------

def _finish(ctx, runs, kind, what, sub=None):
    last = runs[0]
    last.kind, last.runs = kind, runs
    last.extra["what"] = what
    if sub is not None and last.exit_code == 2 and UNKNOWN_SUB.search(last.stderr) and sub in last.stderr + " ".join(last.argv):
        missing(f"the tree under test has no `bh {sub}` (it exits 2 and refuses the subcommand)", f"add the {sub} subcommand to bin/bh")
    return last


def _run_many(ctx, argv, n, rerun, stdin=""):
    def once(_):
        return execute(ctx, argv, stdin=stdin)

    runs = parallel(once, n) if n > 1 else [once(0)]
    if rerun:
        ctx.state["after_first"] = digests(ctx)
        second = [once(0)]
        second[0].first = runs[0]
        return second
    return runs


def when_bh(ctx, sub, args=None, parallel=1, rerun=False):
    argv = sut_argv(ctx, CONTRACT["argv"]["bh"]) + [sub, *(args or [])]
    runs = _run_many(ctx, argv, parallel, rerun)
    return _finish(ctx, runs, "bh", f"bh {sub}", sub)


def when_program_step(ctx, step, item=None, rerun=False):
    argv = []
    for part in CONTRACT["argv"]["program_step"]:
        argv.append(part.format(step=step))
    argv = sut_argv(ctx, argv) + (["--item", item] if item else [])
    runs = _run_many(ctx, argv, 1, rerun)
    return _finish(ctx, runs, "program_step", f"step {step}", "step")


def when_entry_point(ctx, entry, mode=None):
    env = {"UV_OFFLINE": "1"} if mode == "uv_script_offline" else {}
    env["HOME"] = os.environ["HOME"]  # the host's python tooling (pyenv, mise shims) is found through HOME
    if entry == "plugin_pytest":
        junit = ctx.work / "junit-plugin-pytest.xml"
        argv = ["uv", "run", "--script", "--managed-python", str(ctx.tree / "harness" / "run_tests.py"), "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
        run = execute(ctx, argv, cwd=ctx.tree / "harness", env_extra=env, timeout=1200)
        run.extra["junit_path"] = junit
    else:
        r = repo(ctx)
        if (r / "justfile").exists() and shutil.which("just"):
            run = execute(ctx, ["just", "test"], cwd=r, env_extra=env, timeout=600)
            run.extra["junit_path"] = r / P["junit"]
        else:
            junit = ctx.work / "junit-project.xml"
            run = execute(ctx, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"], cwd=r, env_extra=env, timeout=600)
            run.extra["junit_path"] = junit
    run.kind = "entry_point"
    run.runs = [run]
    return run


# ---------- hooks ----------

def when_hook(ctx, hook):
    hj = ctx.tree / P["hooks_json"]
    if not hj.exists():
        missing(f"{P['hooks_json']} is not in the tree under test", "register the hook commands in hooks/hooks.json")
    want = CONTRACT["hooks"][hook]
    cmd = None
    for ev, groups in json.loads(hj.read_text()).get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                if ev == want["event"] and want["command_contains"] in h.get("command", "").lower():
                    cmd = h["command"]
    if cmd is None:
        missing(f"hooks.json registers no {hook} command under {want['event']}", f"register the {hook} hook in hooks/hooks.json")
    hi = ctx.state.get("hook_input")
    if hi is None:
        raise FixtureError(say("ATDD-ORDER", "the hook step has no hook_input given", "add a hook_input given to the row", REF))
    text = hi["path"].read_text()
    cmd = cmd.replace("${" + CONTRACT["argv"]["hook_command_env"] + "}", str(ctx.tree))
    env = {CONTRACT["argv"]["hook_command_env"]: str(ctx.tree)}
    run = execute(ctx, ["sh", "-c", cmd], stdin=text, env_extra=env)
    if hi["touch"] == "repeat":
        run = execute(ctx, ["sh", "-c", cmd], stdin=text, env_extra=env)
    run.kind, run.runs = "hook", [run]
    run.extra["hook_json"] = run.json
    return run


# ---------- builder actions ----------

def _pattern_match(entry: str, tool: str, path: str, clone: Path) -> bool:
    m = re.fullmatch(r"(\w+)(?:\((.*)\))?", entry.strip())
    if not m or m.group(1) != tool:
        return False
    if m.group(2) is None:
        return True
    from fnmatch import fnmatch

    pat = m.group(2)
    rel = os.path.relpath(path, clone)
    return fnmatch(rel, pat) or fnmatch(path, pat) or fnmatch(rel, pat.rstrip("/") + "/*")


def when_builder_action(ctx, tool, action, target):
    r = repo(ctx)
    settings_src = r / P["builder_settings"]
    if not settings_src.exists():
        missing(f"the generated builder settings {P['builder_settings']} do not exist", "generate the builder settings before a launch")
    settings = json.loads(settings_src.read_text())
    clone = ctx.state.get("clone")
    if clone is None:
        clone = ctx.work / "clone"
        subprocess.run(["git", "clone", "-q", "--shared", str(r), str(clone)], check=True, capture_output=True, env=base_env(ctx))
        (clone / P["builder_settings"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings_src, clone / P["builder_settings"])
        ctx.state["clone"] = clone
    pk = ctx.state.get("packet")
    if target == "acceptance_test":
        files = [f for f in (clone.glob("tests/**/*.py"))]
        path = sorted(files)[0] if files else clone / "tests" / "test_acceptance.py"
    elif target == "clone_packet":
        path = clone / P["packets_dir"] / f"{(pk or {'id': 'item'})['id']}.json"
    elif target == "orchestrator_packet":
        path = pk["orchestrator"] if pk else ctx.work / "orchestrator" / "packets" / "item.json"
    elif target == "outside_clone":
        path = ctx.work / "outside" / "target.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("outside\n")
    else:  # source_repo
        path = r
    before = digest_files([path]) if Path(path).is_file() else ""
    perms = settings.get("permissions", {})
    deny, allow = perms.get("deny", []), perms.get("allow", [])
    refused, by = False, None
    msg = ""
    if tool in ("Edit", "Write"):
        if any(_pattern_match(e, tool, str(path), clone) for e in deny) or (allow and not any(_pattern_match(e, tool, str(path), clone) for e in allow if e.startswith(tool))):
            refused, by = True, "file_tools"
            msg = settings.get("messages", {}).get(tool) or f"Permission to use {tool} on {path} has been denied."
        else:
            _apply_python(action, Path(path))
    else:
        sb = settings.get("sandbox", {}).get("filesystem", {})
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise FixtureError(say("ATDD-HOST", "bwrap is not installed on this host", "install bubblewrap (the Bash sandbox of the builder)", REF))
        cmd = _bash_command(action, str(path), str(r), settings)
        argv = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--bind", str(clone), str(clone)]
        for w in sb.get("allowWrite", []):
            p = w if os.path.isabs(w) else str(clone / w)
            if os.path.exists(p):
                argv += ["--bind", p, p]
        for d in sb.get("denyWrite", []):
            p = d if os.path.isabs(d) else str(clone / d)
            if os.path.exists(p):
                argv += ["--ro-bind", p, p]
        argv += ["--chdir", str(clone), "--", "sh", "-c", cmd]
        p = subprocess.run(argv, capture_output=True, text=True, env=base_env(ctx))
        if p.returncode:
            refused, by, msg = True, "sandbox", (p.stderr or p.stdout).strip()
    after = digest_files([path]) if Path(path).is_file() else ""
    run = Run(["builder_action", tool, action, target], 1 if refused else 0, msg, msg, 0.0, "builder_action")
    run.runs = [run]
    run.extra.update(refused=refused, by=by, message=msg, tool_result=msg, changed=before != after, target_path=str(path), primary=msg)
    return run


def _apply_python(action: str, path: Path):
    if action == "delete":
        path.unlink(missing_ok=True)
    elif action == "append":
        with open(path, "a") as f:
            f.write("# appended by the builder\n")
    elif action == "edit":
        text = path.read_text() if path.exists() else ""
        path.write_text(text + "# edited by the builder\n")
    elif action == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# written by the builder\n")


def _bash_command(action: str, path: str, source_repo: str, settings) -> str:
    q = json.dumps(path)
    py = sys.executable
    return {
        "delete": f"{py} -c 'import os,sys;os.remove(sys.argv[1])' {q}",
        "append": f"printf '# appended by the builder\\n' >> {q}",
        "edit": f"printf '# edited by the builder\\n' >> {q}",
        "write": f"printf '# written by the builder\\n' > {q}",
        "delete_ref": f"git -C {json.dumps(source_repo)} update-ref -d refs/heads/{R['main_branch']}",
    }[action]


# ---------- scan ----------

TEXT_SKIP = (".git", "__pycache__", ".pytest_cache")
BIN_EXT = {".png", ".jpg", ".gif", ".pyc", ".zip", ".gz", ".ico", ".pdf"}


def _expand(root: Path, paths) -> list:
    out = []
    for pat in paths:
        hits = globs(root, [pat]) if any(c in pat for c in "*?[") else ([root / pat] if (root / pat).exists() else [])
        for h in hits:
            if h.is_dir():
                out += [Path(f) for f in tree_files(h, skip=TEXT_SKIP)]
            else:
                out.append(h)
    return sorted({p for p in out if p.suffix not in BIN_EXT})


def _front(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:  # a plain `key: value` front matter whose value holds a colon
        out, key = {}, None
        for ln in m.group(1).splitlines():
            kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
            if kv:
                key = kv.group(1)
                out[key] = kv.group(2).strip().strip("\"'")
            elif key and ln.strip():
                out[key] = (str(out[key]) + " " + ln.strip()).strip()
        return out


REF_RE = re.compile(r"(?<![\w:/@.-])((?:\.{0,2}/)?[\w.-]+(?:/[\w.*<>{}-]+)*\.(?:md|py|json|yaml|yml|sh|toml|txt|js|ts|jsonl)|(?:[\w-]+/)+[\w.-]+/?)(?![\w:/@-])")


def _python_defs(path: Path):
    tree = ast.parse(path.read_text())
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(n):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    names.add(t.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def when_scan(ctx, paths, kind, pattern=None):
    root = repo(ctx)
    files = _expand(root, paths)
    rel = lambda p: str(p.relative_to(root))  # noqa: E731
    matches, values = [], {}
    if kind in ("text", "symbol"):
        rx = re.compile(pattern if kind == "text" else rf"\b(?:{pattern})\b")
        for f in files:
            try:
                lines = f.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            matches += [f"{rel(f)}:{i}:{ln.strip()[:100]}" for i, ln in enumerate(lines, 1) if rx.search(ln)]
    elif kind == "path":
        for pat in paths:
            hits = globs(root, [pat])
            matches += [rel(h) for h in hits]
        matches = sorted(set(matches))
    elif kind == "frontmatter":
        for f in files:
            fm = _front(f.read_text())
            values[rel(f)] = fm
            own = re.compile(rf"\b{re.escape(str(fm.get('name') or f.parent.name))}\b")  # a skill may name itself
            matches += [f"{rel(f)}:{k}" for k, v in fm.items() if not pattern or re.search(pattern, own.sub("", f"{k}: {v}"))]
    elif kind == "description_chars":
        for f in files:
            values[rel(f)] = len(str(_front(f.read_text()).get("description", "")))
        matches = [f"{k}:{v}" for k, v in values.items()]
    elif kind == "file_chars":
        for f in files:
            values[rel(f)] = len(f.read_text())
        matches = [f"{k}:{v}" for k, v in values.items()]
    elif kind in ("references", "dangling_references"):
        for f in files:
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for m in REF_RE.finditer(text):
                ref = m.group(1)
                if "://" in ref or any(c in ref for c in "*<>{}"):
                    continue
                if kind == "dangling_references" and ((f.parent / ref).exists() or (root / ref.lstrip("./")).exists() or (root / ref).exists()):
                    continue
                matches.append(f"{rel(f)} -> {ref}")
    elif kind == "version_strings":
        rx = re.compile(r"\b\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?\b")
        for f in files:
            try:
                matches += [f"{rel(f)}:{m.group(0)}" for m in rx.finditer(f.read_text())]
            except (UnicodeDecodeError, OSError):
                continue
    elif kind == "untaught_exits":
        # a site is taught when `teach(` appears on its line or in the 6 lines before it (the message is built there)
        rx = re.compile(r"\bsys\.exit\(\s*[^)\s]|\braise SystemExit\(\s*[^)\s]|(?<![\w.])exit\(\s*[^)\s]|\.error\(|^\s*exit\s+[1-9]|\"decision\"\s*:\s*\"block\"|permissionDecision.{0,8}deny", re.M)
        zero = re.compile(r"(sys\.exit|exit|SystemExit)\(\s*(0|None)?\s*\)")
        for f in files:
            try:
                lines = f.read_text().splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, ln in enumerate(lines):
                if rx.search(ln) and not zero.search(ln) and not any("teach(" in x for x in lines[max(0, i - 6): i + 1]):
                    matches.append(f"{rel(f)}:{i + 1}")
    elif kind == "undefined_names":
        mods = {}
        for f in files:
            if f.suffix == ".py" or (f.suffix == "" and f.read_bytes()[:2] == b"#!" and b"python" in f.read_bytes().split(b"\n", 1)[0]):
                mods[f.stem if f.suffix else f.name] = f
        defs = {}
        for name, f in mods.items():
            try:
                defs[name] = _python_defs(f)
            except SyntaxError:
                pass
        for name, f in mods.items():
            if name not in defs:
                continue
            tree = ast.parse(f.read_text())
            alias = {}
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name in defs:
                            alias[a.asname or a.name] = a.name
                elif isinstance(n, ast.ImportFrom) and n.module in defs:
                    for a in n.names:
                        if a.name != "*" and a.name not in defs[n.module]:
                            matches.append(f"{rel(f)}:{n.lineno}: {n.module}.{a.name}")
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias and n.attr not in defs[alias[n.value.id]]:
                    matches.append(f"{rel(f)}:{n.lineno}: {alias[n.value.id]}.{n.attr}")
    elif kind == "lint_rule":
        exe = shutil.which("ruff", path=base_env(ctx)["PATH"])
        if not exe:
            raise FixtureError(say("ATDD-HOST", "ruff is not installed on this host", "install the pinned ruff", REF))
        p = subprocess.run([exe, "check", "--isolated", "--no-cache", "--select", pattern, "--output-format", "json", *map(str, files)], capture_output=True, text=True, cwd=root)
        matches = [f"{rel(Path(x['filename']))}:{x['location']['row']}:{x['code']}" for x in json.loads(p.stdout or "[]")]
    number = max(values.values()) if kind in ("description_chars", "file_chars") and values else len(matches)
    run = Run(["scan", kind], 0, "\n".join(matches), "", 0.0, "scan")
    run.runs = [run]
    run.extra.update(scan_params={"paths": paths, "kind": kind, "pattern": pattern}, matches=matches, values=values, number=number, scan_kind=kind, files=[rel(f) for f in files], primary="\n".join(matches), distinct_count=len(set(m.split(":")[-1] if kind == "version_strings" else m for m in matches)))
    return run


# ---------- validate, plugin_eval ----------

def load_schema(ctx, name: str):
    r = repo(ctx)
    for base in (r, ctx.tree):
        for rel_dir in (".", "harness/schema"):  # a bare file name is one of the plugin's own schemas
            if (base / rel_dir / name).is_file():
                return yaml.safe_load((base / rel_dir / name).read_text())
    return fixture_data(ctx, "schemas", name + ".json")


def load_instance(ctx, name: str):
    r = repo(ctx)
    for base in (r, ctx.tree):
        if (base / name).is_file():
            return yaml.safe_load((base / name).read_text())
    pk = ctx.state.get("packet")  # the contract names how a row refers to the packet it was given
    if pk and name in [n.format(id=pk["id"]) for n in CONTRACT["instance_names"]["packet"]] and pk["repo_copy"].is_file():
        return json.loads(pk["repo_copy"].read_text())
    missing(f"the instance file {name} does not exist", "produce the file before it is validated")


def run_validation(instance, schema, ctx=None):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    # a schema may $ref the tree's other schemas by their $id (the packet schema reuses the criteria row)
    reg = Registry()
    tree = ctx.tree if ctx is not None else None
    for f in ([tree / "docs/atdd/criteria.schema.json", *sorted((tree / "harness/schema").glob("*.json"))] if tree else []):
        if not f.is_file():
            continue
        doc = json.loads(f.read_text())
        if "$id" in doc:
            reg = reg.with_resource(doc["$id"], Resource.from_contents(doc))
    errs = sorted(Draft202012Validator(schema, registry=reg).iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
    return [{"path": "$" + "".join(f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in e.absolute_path), "dotted": ".".join(map(str, e.absolute_path)), "message": e.message} for e in errs]


def when_validate(ctx, instance, schema):
    inst, sch = load_instance(ctx, instance), load_schema(ctx, schema)
    errs = run_validation(inst, sch, ctx)
    run = Run(["validate", instance, schema], 0 if not errs else 1, json.dumps(errs), "", 0.0, "validate")
    run.runs = [run]
    run.extra.update(valid=not errs, errors=errs, instance_obj=inst, primary="\n".join(f"{e['path']}: {e['message']}" for e in errs))
    return run


def when_plugin_eval(ctx, args):
    run = execute(ctx, ["claude", "plugin", "eval", *args], cwd=repo(ctx))
    run.kind, run.runs = "plugin_eval", [run]
    return run


WHEN = {"bh": when_bh, "entry_point": when_entry_point, "program_step": when_program_step, "hook": when_hook, "builder_action": when_builder_action, "scan": when_scan, "validate": when_validate, "plugin_eval": when_plugin_eval}
