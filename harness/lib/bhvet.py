"""bh vet (R9, QBC-84): a third-party package's public supply-chain facts, from the services that keep them.

  deps.dev API v3   the version: licenses, publish date, advisories, source repository
  OpenSSF Scorecard the source repository's published Scorecard result (api.securityscorecards.dev)
  OSV API v1        known vulnerabilities of the version (the database osv-scanner queries)

No account and no key. Each response is kept as ``api_results[*]`` {id, body}, unchanged; the
facts are lines read from those bodies. Nothing here scores or judges: the reader compares
candidates on the facts (P4). A service that answers with an error is a fact too.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from bhcore import RESULT_VERSION

DEPS_DEV = "https://api.deps.dev/v3"
SCORECARD = "https://api.securityscorecards.dev/projects/"
OSV = "https://api.osv.dev/v1/query"
# deps.dev system -> OSV ecosystem (https://ossf.github.io/osv-schema/#affectedpackage-field)
ECOSYSTEM = {"pypi": "PyPI", "npm": "npm", "go": "Go", "maven": "Maven", "cargo": "crates.io", "nuget": "NuGet"}
TIMEOUT_S = 30


def _call(url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """One request; the parsed JSON answer, or ``{"error": ...}`` when the service gives none."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read() or b"{}")  # type: ignore[no-any-return]
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def source_repo(version_body: dict[str, Any]) -> str | None:
    """The source repository deps.dev links the version to (``github.com/o/r``), if any."""
    for p in version_body.get("relatedProjects", []):
        if p.get("relationType") == "SOURCE_REPO":
            return str(p["projectKey"]["id"])
    return None


def vet(system: str, name: str, version: str | None = None) -> dict[str, Any]:
    system = system.lower()
    if system not in ECOSYSTEM:
        raise ValueError(f"system {system!r}: one of {', '.join(ECOSYSTEM)} (the deps.dev systems)")
    pkg = f"{DEPS_DEV}/systems/{system}/packages/{_q(name)}"
    if not version:  # the package's default version, as deps.dev marks it
        versions = _call(pkg).get("versions", [])
        version = next((v["versionKey"]["version"] for v in versions if v.get("isDefault")), None)
    dd = _call(f"{pkg}/versions/{_q(version)}") if version else {"error": f"no default version of {name}"}
    repo = source_repo(dd)
    sc = _call(SCORECARD + repo) if repo else {"error": "deps.dev names no source repository"}
    osv = (
        _call(OSV, {"package": {"name": name, "ecosystem": ECOSYSTEM[system]}, "version": version})
        if version
        else {"error": "no version to query"}
    )
    results = [{"id": "deps.dev", "body": dd}, {"id": "scorecard", "body": sc}, {"id": "osv", "body": osv}]
    return {
        "schema_version": RESULT_VERSION,
        "command": "vet",
        "api_results": results,
        "facts": facts(f"{system}/{name}@{version}", repo, results),
    }


def facts(subject: str, repo: str | None, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Lines read from the bodies, one per fact; no score of our own."""
    out = [{"kind": "subject", "detail": f"{subject}; source {repo or 'unknown'}"}]
    body = {r["id"]: r["body"] for r in results}
    for sid, b in body.items():
        if "error" in b:
            out.append({"kind": f"{sid}.error", "detail": b["error"]})
    dd, sc, osv = body["deps.dev"], body["scorecard"], body["osv"]
    if "error" not in dd:
        out.append({"kind": "deps.dev.licenses", "detail": ", ".join(dd.get("licenses", [])) or "none declared"})
        out.append({"kind": "deps.dev.published", "detail": dd.get("publishedAt", "unknown")})
        out.append({"kind": "deps.dev.advisories", "detail": str(len(dd.get("advisoryKeys", [])))})
    if "error" not in sc:
        out.append({"kind": "scorecard.score", "detail": f"{sc.get('score')} of 10 on {sc.get('date')}"})
        for c in sorted(sc.get("checks", []), key=lambda c: c.get("score", -1)):
            out.append({"kind": "scorecard.check", "detail": f"{c.get('name')}: {c.get('score')}"})
    if "error" not in osv:
        vulns = osv.get("vulns", [])
        out.append({"kind": "osv.vulns", "detail": f"{len(vulns)}" + (": " + ", ".join(v["id"] for v in vulns) if vulns else "")})
    return out


def main(system: str, name: str, version: str | None) -> int:
    try:
        res = vet(system, name, version)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    for f in res["facts"]:  # the facts first, the result JSON last (as bh measure prints)
        print(f"{f['kind']}: {f['detail']}")
    print(json.dumps(res))
    return 0
