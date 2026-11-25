"""Given keywords: fixture set-up, one function per catalog key (from each key's passes_when)."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from support import CONTRACT, FixtureError, REF, fixture_data, fixture_path, git, init_env, overlay, repo, say, tree_files, writable_repo

P = CONTRACT["paths"]
R = CONTRACT["refs"]


def _env(ctx):
    if "env" not in ctx.state:
        init_env(ctx)


def given_repo(ctx, name, state):
    _env(ctx)
    if name == "plugin":
        ctx.state.update(repo=ctx.tree, repo_is_tree=True, source_repo=ctx.tree)
        if state != "candidate":  # a named release of the tree: its files at that git ref
            import subprocess

            dest = ctx.work / f"plugin-{state}"
            dest.mkdir()
            p = subprocess.run(f"git -C {ctx.tree} archive {state} | tar -x -C {dest}", shell=True, capture_output=True)
            if p.returncode:
                raise FixtureError(say("ATDD-FIXTURE", f"plugin state {state} is not a git ref of the tree", "use candidate or an existing tag", REF))
            ctx.state.update(repo=dest, repo_is_tree=False)
        return
    base = fixture_path(ctx, "repo", name, "base")
    dest = ctx.work / "repo"
    dest.mkdir()
    overlay(base, dest)
    meta = {}
    if state != "base":
        st = fixture_path(ctx, "repo", name, state)
        overlay(st, dest)
        if (st / "meta.json").exists():
            meta = json.loads((st / "meta.json").read_text())
        (dest / "meta.json").unlink(missing_ok=True)
    ctx.state.update(repo=dest, repo_is_tree=False, source_repo=dest, repo_name=name)
    git(ctx, "init", "-q", "-b", R["main_branch"], cwd=dest)
    git(ctx, "add", "-A", cwd=dest)
    git(ctx, "commit", "-q", "-m", f"base: {name} {state}", cwd=dest)
    git(ctx, "tag", R["base_tag"], cwd=dest)
    if meta.get("remote"):
        bare = ctx.work / "origin.git"
        git(ctx, "init", "-q", "--bare", str(bare), cwd=dest)
        git(ctx, "remote", "add", "origin", str(bare), cwd=dest)


def given_planted(ctx, plant, **kw):
    where = kw.get("where", "candidate_commit")
    _env(ctx)
    r = writable_repo(ctx)
    name = ctx.state.get("repo_name", "plugin")
    src = ctx.fixtures / "planted" / f"{plant}@{name}"
    if not src.is_dir():
        src = ctx.fixtures / "planted" / plant
    if not src.is_dir():
        raise FixtureError(say("ATDD-FIXTURE", f"fixture planted/{plant} does not exist", "author it as described in the fixtures README", REF))
    if where == "working_tree":
        overlay(src, r)
    elif where == "plan_commit":
        cur = git(ctx, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        has_cand = git(ctx, "rev-parse", "--verify", "-q", R["candidate_branch"], check=False).returncode == 0
        git(ctx, "checkout", "-q", R["main_branch"])
        overlay(src, r)
        git(ctx, "add", "-A")
        git(ctx, "commit", "-q", "-m", f"plan: {plant}")
        git(ctx, "tag", "-f", R["base_tag"])
        if has_cand:
            git(ctx, "checkout", "-q", R["candidate_branch"])
            git(ctx, "rebase", "-q", R["main_branch"])
        elif cur != R["main_branch"]:
            git(ctx, "checkout", "-q", cur)
    else:
        has_cand = git(ctx, "rev-parse", "--verify", "-q", R["candidate_branch"], check=False).returncode == 0
        git(ctx, "checkout", "-q", *([R["candidate_branch"]] if has_cand else ["-b", R["candidate_branch"]]))
        overlay(src, r)
        git(ctx, "add", "-A")
        git(ctx, "commit", "-q", "-m", f"candidate: {plant}")
    ctx.state.setdefault("planted", []).append({"plant": plant, "where": where, "class": kw.get("class")})


def given_recorded_model(ctx, fixture):
    _env(ctx)
    p = fixture_path(ctx, "recorded_model", fixture + ".json")
    fixture_data(ctx, "recorded_model", fixture + ".json")
    ctx.state["env"][CONTRACT["env"]["model_fixture"]] = str(p)


class _Api(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _serve(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        srv = self.server
        with srv.lock:
            hit = None
            for i, ex in enumerate(srv.exchanges):
                if i in srv.used:
                    continue
                if ex.get("method", self.command) != self.command:
                    continue
                if not self.path.startswith(ex.get("path", "")):
                    continue
                if ex.get("match_body", "") not in body:
                    continue
                hit = i
                break
            op = "unmatched"
            status, payload = 404, {"message": "no recorded response"}
            if hit is not None:
                srv.used.add(hit)
                ex = srv.exchanges[hit]
                op, status, payload = ex.get("operation", "request"), ex.get("status", 200), ex.get("body", {})
            srv.log.append({"service": srv.service, "operation": op, "method": self.command, "path": self.path, "body": body})
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve


def given_recorded_api(ctx, service, fixture):
    _env(ctx)
    data = fixture_data(ctx, "recorded_api", service, fixture + ".json")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    srv.exchanges, srv.used, srv.lock, srv.service = data["exchanges"], set(), threading.Lock(), service
    srv.log = ctx.state.setdefault("api_log", [])
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    ctx.finalizers.append(lambda: (srv.shutdown(), srv.server_close()))
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    for var in CONTRACT["env"]["api_urls"][service]:
        ctx.state["env"][var] = url


def given_hook_input(ctx, event, tool, agent_type, packet, target, touch="first"):
    _env(ctx)
    name = ".".join([event, tool, agent_type, packet, target, touch]) + ".json"
    fixture_data(ctx, "hook_input", name)
    ctx.state["hook_input"] = {"path": fixture_path(ctx, "hook_input", name), "event": event, "touch": touch, "packet": packet}


def given_packet(ctx, fixture, variant):
    _env(ctx)
    p = fixture_path(ctx, "packet", fixture, variant + ".json")
    raw = p.read_bytes()
    data = fixture_data(ctx, "packet", fixture, variant + ".json")
    pid = data.get("id", fixture)
    orch = ctx.work / "orchestrator" / "packets"
    orch.mkdir(parents=True, exist_ok=True)
    (orch / f"{pid}.json").write_bytes(raw)
    r = writable_repo(ctx)
    inrepo = r / P["packets_dir"] / f"{pid}.json"
    tracked = git(ctx, "ls-files", "--error-unmatch", str(inrepo.relative_to(r)), check=False).returncode == 0
    if not tracked:
        inrepo.parent.mkdir(parents=True, exist_ok=True)
        inrepo.write_bytes(raw)
    ctx.state["packet"] = {"id": pid, "sha256": hashlib.sha256(raw).hexdigest(), "data": data, "variant": variant, "orchestrator": orch / f"{pid}.json", "repo_copy": inrepo}


def given_config(ctx, state, key=None, value=None):
    _env(ctx)
    f = writable_repo(ctx) / P["config_file"]
    if state == "absent":
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    doc: dict = {}
    cur = doc
    parts = key.split(".")
    for seg in parts[:-1]:
        cur = cur.setdefault(seg, {})
    cur[parts[-1]] = value
    f.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def given_host(ctx, condition):
    _env(ctx)
    spec = fixture_data(ctx, "host", condition + ".json")
    ctx.state["env"].update({k: str(v) for k, v in spec.get("env", {}).items()})
    for name, s in spec.get("stubs", {}).items():
        f = ctx.work / "bin" / name
        f.write_text("#!/bin/sh\n" + (f"printf %s {json.dumps(s['stdout'])}\n" if s.get("stdout") else "") + (f"printf %s {json.dumps(s['stderr'])} >&2\n" if s.get("stderr") else "") + f"exit {int(s.get('exit', 0))}\n")
        f.chmod(0o755)
    for name in spec.get("hide", []):
        f = ctx.work / "bin" / name
        f.write_text(f"#!/bin/sh\necho '{name}: command not found' >&2\nexit 127\n")
        f.chmod(0o755)
    files = spec.get("files", {})
    if files:
        r = writable_repo(ctx)
        for rel, text in files.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(text)
    ctx.state.setdefault("hosts", []).append(condition)


def given_recorded_answer(ctx, question, answer):
    _env(ctx)
    data = fixture_data(ctx, "recorded_answer", f"{question}.{answer}.json")
    answers = ctx.state.setdefault("answers", {})
    answers[question] = {"answer": answer, **(data or {})}
    (ctx.work / "answers.json").write_text(json.dumps(answers, indent=2, sort_keys=True))


def given_history(ctx, fixture, period):
    _env(ctx)
    r = writable_repo(ctx)
    for per in (["pre_v2", "v2"] if period == "both" else [period]):
        d = fixture_path(ctx, "history", fixture, per)
        dest = r / ".brick-harness" / "history" / per
        overlay(d, dest)
        cj = dest / "commits.json"
        if cj.exists():
            for c in json.loads(cj.read_text()):
                for rel, text in c.get("files", {}).items():
                    (r / rel).parent.mkdir(parents=True, exist_ok=True)
                    (r / rel).write_text(text)
                env = {"GIT_AUTHOR_DATE": c.get("date", "2026-01-01T00:00:00+00:00"), "GIT_COMMITTER_DATE": c.get("date", "2026-01-01T00:00:00+00:00")}
                import subprocess

                subprocess.run(["git", "add", "-A", "--", ".", ":!.brick-harness"], cwd=r, env={**ctx.state["env"], **env}, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", c["message"]], cwd=r, env={**ctx.state["env"], **env}, check=True, capture_output=True)
            cj.unlink()


GIVEN = {"repo": given_repo, "planted": given_planted, "recorded_model": given_recorded_model, "recorded_api": given_recorded_api, "hook_input": given_hook_input, "packet": given_packet, "config": given_config, "host": given_host, "recorded_answer": given_recorded_answer, "history": given_history}
