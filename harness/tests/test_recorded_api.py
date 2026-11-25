"""recorded_api: an unchanged program reaches recorded responses through the replay proxy, and a request with no recording never leaves."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from mitmproxy import http, io
from mitmproxy.test import tflow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from given import given_recorded_api  # noqa: E402
from support import api_log  # noqa: E402

CLIENT = "import sys, urllib.request as u\nr = u.Request(sys.argv[1], data=sys.argv[2].encode() if sys.argv[2] else None)\nprint(u.urlopen(r).read().decode())"


def flow(method, url, body, answer, operation):
    req = http.Request.make(method, url, body)
    f = tflow.tflow(req=req)
    f.response = http.Response.make(201, answer, {"X-Recorded-Operation": operation, "Authorization": "Bearer secret"})
    return f


def test_replay_answers_recorded_requests_and_kills_the_rest(tmp_path):
    fx = tmp_path / "fx" / "recorded_api" / "github"
    fx.mkdir(parents=True)
    with (fx / "create.flows").open("wb") as out:
        io.FlowWriter(out).add(flow("POST", "https://api.github.com/repos/o/r/issues", "make", '{"number": 7}', "createIssue"))
    work = tmp_path / "work"
    work.mkdir()
    ctx = SimpleNamespace(state={"env": {}}, work=work, fixtures=tmp_path / "fx", finalizers=[])
    given_recorded_api(ctx, "github", "create")
    try:
        def call(url, body):
            return subprocess.run([sys.executable, "-c", CLIENT, url, body], env=ctx.state["env"], capture_output=True, text=True)

        ok = call("https://api.github.com/repos/o/r/issues", "make")
        assert ok.returncode == 0 and '"number": 7' in ok.stdout
        assert call("https://api.github.com/repos/o/r/issues", "make").returncode != 0  # the recording is spent
        assert call("https://api.github.com/repos/o/other", "").returncode != 0  # no recording: killed, not forwarded
    finally:
        for f in ctx.finalizers:
            f()
    log = [(e["service"], e["operation"], e["method"], e["path"]) for e in api_log(ctx)]
    assert log == [("github", "createIssue", "POST", "/repos/o/r/issues"), ("github", "unmatched", "POST", "/repos/o/r/issues"), ("github", "unmatched", "GET", "/repos/o/other")]
