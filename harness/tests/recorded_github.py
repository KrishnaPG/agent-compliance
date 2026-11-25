"""Test helper: GitHub API answers recorded as mitmproxy flows, replayed offline (fixtures README, recorded_api)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from mitmproxy import http, io
from mitmproxy.test import tflow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from given import given_recorded_api  # noqa: E402
from support import api_log  # noqa: E402

API = "https://api.github.com/repos/o/r"


def flow(method, path, answer, body=""):
    """One recorded exchange: the request the program makes and the JSON GitHub answers."""
    f = tflow.tflow(req=http.Request.make(method, API + path, body))
    f.response = http.Response.make(200, json.dumps(answer), {"Content-Type": "application/json", "X-Recorded-Operation": f"{method} {path}"})
    return f


def replay(tmp_path, monkeypatch, flows):
    """Start the replay proxy over ``flows``; the program's env reaches it. Returns (ctx, stop)."""
    fx = tmp_path / "fx" / "recorded_api" / "github"
    fx.mkdir(parents=True)
    with (fx / "h.flows").open("wb") as out:
        w = io.FlowWriter(out)
        for f in flows:
            w.add(f)
    work = tmp_path / "work"
    work.mkdir()
    ctx = SimpleNamespace(state={"env": {}}, work=work, fixtures=tmp_path / "fx", finalizers=[])
    given_recorded_api(ctx, "github", "h")
    for k, v in ctx.state["env"].items():
        if k.endswith("_proxy") or k.endswith("PROXY") or "CERT" in k or "CA_" in k or k.endswith("BUNDLE"):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("GH_TOKEN", "recorded")
    monkeypatch.setenv("NO_PROXY", "")
    return ctx, lambda: [f() for f in ctx.finalizers]


def calls(ctx):
    return [(e["operation"], e["method"], e["path"]) for e in api_log(ctx)]
