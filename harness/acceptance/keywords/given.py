"""Given keywords: fixture set-up, one function per catalog key (from each key's passes_when)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
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
    elif where == "main_commit":  # main moves on after the candidate branched: base tag and candidate stay where they are
        cur = git(ctx, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        git(ctx, "checkout", "-q", R["main_branch"])
        overlay(src, r)
        git(ctx, "add", "-A")
        git(ctx, "commit", "-q", "-m", f"main: {plant}")
        git(ctx, "checkout", "-q", cur)
    else:
        has_cand = git(ctx, "rev-parse", "--verify", "-q", R["candidate_branch"], check=False).returncode == 0
        git(ctx, "checkout", "-q", *([R["candidate_branch"]] if has_cand else ["-b", R["candidate_branch"]]))
        overlay(src, r)
        git(ctx, "add", "-A")
        pk = ctx.state.get("packet")  # the registered packet is the program's file, not the builder's change
        if pk and not (src / P["packets_dir"] / pk["repo_copy"].name).exists():
            git(ctx, "reset", "-q", "--", str(pk["repo_copy"].relative_to(r)), check=False)
        msg = src / ".atdd-message"  # a plant may carry the commit message trailers it needs
        git(ctx, "commit", "-q", "-m", f"candidate: {plant}" + (f"\n\n{msg.read_text().strip()}" if msg.is_file() else ""))
    ctx.state.setdefault("planted", []).append({"plant": plant, "where": where, "class": kw.get("class")})


def given_recorded_model(ctx, fixture):
    _env(ctx)
    p = fixture_path(ctx, "recorded_model", fixture + ".json")
    fixture_data(ctx, "recorded_model", fixture + ".json")
    ctx.state["env"][CONTRACT["env"]["model_fixture"]] = str(p)


def _start_replay(ctx, flows):
    """Serve every recorded flow offline through mitmproxy's server replay; returns the function that stops it."""
    from mitmproxy import io

    hosts = {}
    for service, path in flows:
        try:
            with path.open("rb") as f:
                for flow in io.FlowReader(f).stream():
                    hosts[flow.request.host] = service
        except Exception as e:  # malformed fixture
            raise FixtureError(say("ATDD-FIXTURE", f"fixture {path.relative_to(ctx.fixtures)} is not a mitmproxy flow file: {e}", "record it as the fixtures README describes", REF)) from e
    confdir = ctx.work / "mitm"
    cmd = [sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()", "-q", "--listen-host", "127.0.0.1", "--listen-port", "0",
           "--set", f"confdir={confdir}", "--set", "connection_strategy=lazy", "--set", "upstream_cert=false", "--set", "keepserving=true",
           "-s", str(Path(__file__).with_name("mitm_addon.py"))]
    for _, path in flows:
        cmd += ["--server-replay", str(path)]
    env = {**os.environ, "ATDD_API_LOG": str(ctx.work / "api.log.jsonl"), "ATDD_API_HOSTS": json.dumps(hosts)}
    err = (ctx.work / "mitm.err").open("w")
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, text=True)
    ready = proc.stdout.readline().split()  # the addon prints its port once the proxy listens: an event, no polling
    if ready[:1] != ["ATDD-PROXY-READY"]:
        proc.kill()
        proc.wait()
        raise FixtureError(say("ATDD-FIXTURE", f"the replay proxy did not start (it said {ready}): " + (ctx.work / "mitm.err").read_text()[-500:], "run the rows through harness/run_tests.py, which pins the tools", REF))
    url = f"http://127.0.0.1:{ready[1]}"
    ca = str(confdir / "mitmproxy-ca-cert.pem")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        ctx.state["env"][var] = url
    for var in CONTRACT["env"]["ca_bundles"]:
        ctx.state["env"][var] = ca

    def stop():
        proc.terminate()
        proc.wait()
        proc.stdout.close()
        err.close()

    return stop


def given_recorded_api(ctx, service, fixture):
    _env(ctx)
    flows = ctx.state.setdefault("api_flows", [])
    if not flows:
        ctx.finalizers.append(lambda: ctx.state.pop("api_stop", lambda: None)())
    path = fixture_path(ctx, "recorded_api", service, fixture + ".flows")
    ctx.state.pop("api_stop", lambda: None)()  # one proxy serves every service of the row: restart it with all flows
    flows.append((service, path))
    ctx.state["api_stop"] = _start_replay(ctx, flows)


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
    digest = hashlib.sha256(raw).hexdigest()
    orch = ctx.work / "orchestrator" / P["custody_dir"]  # the orchestrator keeps the packet by digest
    orch.mkdir(parents=True, exist_ok=True)
    (orch / f"{digest}.json").write_bytes(raw)
    r = writable_repo(ctx)
    inrepo = r / P["packets_dir"] / f"{pid}.json"
    tracked = git(ctx, "ls-files", "--error-unmatch", str(inrepo.relative_to(r)), check=False).returncode == 0
    if not tracked:
        inrepo.parent.mkdir(parents=True, exist_ok=True)
        inrepo.write_bytes(raw)
    ctx.state["packet"] = {"id": pid, "sha256": hashlib.sha256(raw).hexdigest(), "data": data, "variant": variant, "orchestrator": orch / f"{digest}.json", "repo_copy": inrepo}


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
