"""Per-row outcome of a run: JUnit XML joined to the criteria rows by the criterion property.

Outcomes: green (passed), red (an assertion failed), error (the test could not run), skipped, absent (no result).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


def outcomes(junit: Path, criteria: Path) -> dict[str, dict]:
    ids = [r["id"] for f in sorted(Path(criteria).glob("*.yaml")) for r in yaml.safe_load(f.read_text())["acceptance"]]
    out = {i: {"outcome": "absent", "message": ""} for i in ids}
    for tc in ET.parse(junit).getroot().iter("testcase"):
        crit = next((p.get("value") for p in tc.iter("property") if p.get("name") == "criterion"), None)
        if crit not in out:
            continue
        kids = {c.tag: c for c in tc}
        o, m = "green", ""
        for tag, name in (("failure", "red"), ("error", "error"), ("skipped", "skipped")):
            if tag in kids:
                o, m = name, (kids[tag].get("message") or "").replace("\n", " ")[:300]
                break
        out[crit] = {"outcome": o, "message": m}
    return out


def render(res: dict[str, dict]) -> str:
    return json.dumps(res, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="python -m atdd_engine.report", description="print each row's outcome from a JUnit XML run")
    ap.add_argument("--junit", required=True)
    ap.add_argument("--criteria", required=True)
    a = ap.parse_args()
    print(render(outcomes(Path(a.junit), Path(a.criteria))), end="")
