"""mitmproxy addon for recorded_api: logs each request for api_call, announces its port, redacts credentials when recording.

Replay: mitmdump --server-replay <flows> -s mitm_addon.py (see given_recorded_api).
Record: add `-w <fixture>.flows` and set ATDD_REDACT=1; Authorization and cookies are replaced before the flow is saved.
"""

import json
import os

from mitmproxy import ctx

OPERATION_HEADER = "X-Recorded-Operation"
REDACTED = ("authorization", "proxy-authorization", "cookie", "set-cookie")


class Recorded:
    def __init__(self):
        self.log = os.environ.get("ATDD_API_LOG")
        self.hosts = json.loads(os.environ.get("ATDD_API_HOSTS", "{}"))

    def running(self):
        port = ctx.master.addons.get("proxyserver").listen_addrs()[0][1]
        print(f"ATDD-PROXY-READY {port}", flush=True)

    def _write(self, entry):
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def request(self, flow):
        r = flow.request
        self._write({"id": flow.id, "service": self.hosts.get(r.host, r.host), "operation": "unmatched", "method": r.method, "path": r.path, "body": r.get_text(strict=False) or ""})

    def server_connect(self, data):
        if not os.environ.get("ATDD_REDACT"):  # replay never connects upstream, whatever the order of the addons or how many recordings are left
            data.server.error = "no recording answered this request"

    def response(self, flow):
        op = flow.response.headers.pop(OPERATION_HEADER, None)
        if op:
            self._write({"id": flow.id, "operation": op})
        if os.environ.get("ATDD_REDACT"):
            for h in (flow.request.headers, flow.response.headers):
                for k in [k for k in h if k.lower() in REDACTED]:
                    h[k] = "redacted"


addons = [Recorded()]
