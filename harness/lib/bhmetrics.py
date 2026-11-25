"""bh metrics (QBC R11): DORA measures from the records the harness already keeps; no new service.

Sources: git (the merge commit ``brick-harness: merge <item> <sha>`` is when a slice was met),
the tracker's issue history (slice opening, defect sub-issues; one REST read through the
adapter), and ``jobs[*]`` of the run results under the measure out dir (tokens, rounds).

  change_failure_rate     met slices that later got a defect sub-issue, as a share (ratio)
  lead_time_for_changes   slice opening to merge, median (hours; DORA reports the median)
  tokens_per_met_slice    tokens of the met slices' jobs, over the met slices (tokens)
  measurer_rounds         rounds summed from the met slices' jobs (count)

The baseline is the pre-v2 history, written once as ``.brick-harness/metrics-baseline.json``
(created exclusively: a second run never rewrites it). Its window ends at the commit time of HEAD
when it was written; a slice merged after that is ``current``.
"""

import json
import re
import statistics
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from bhcore import HDIR, RESULT_VERSION, Config, HarnessError
from bhtracker import Tracker, item_id

BASELINE = f"{HDIR}/metrics-baseline.json"
_MERGE = re.compile(r"^brick-harness: merge (\S+) ")
UNITS = {
    "change_failure_rate": "ratio",
    "lead_time_for_changes": "hours",
    "tokens_per_met_slice": "tokens",
    "measurer_rounds": "count",
}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def merges(top: Path) -> tuple[dict[str, float], float]:
    """Item -> commit time of its first merge commit; and the commit time of HEAD."""
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(top), *a], capture_output=True, text=True, check=True
    ).stdout
    found: dict[str, float] = {}
    for line in run("log", "--reverse", "--format=%ct\t%s", "--grep=^brick-harness: merge").splitlines():
        t, _, subject = line.partition("\t")
        m = _MERGE.match(subject)
        if m:
            found.setdefault(m.group(1), float(t))
    return found, float(run("log", "-1", "--format=%ct").strip() or 0)


def job_totals(out_dir: Path) -> dict[str, dict[str, float]]:
    """Per item: tokens and rounds, summed over the distinct jobs of every run result."""
    seen: set[str] = set()
    totals: dict[str, dict[str, float]] = {}
    for f in sorted(out_dir.glob("*-result.json")):
        for j in json.loads(f.read_text()).get("jobs", []):
            key = str(j.get("key") or j.get("id") or "")
            if not j.get("item") or j.get("skipped") or j.get("cached") or (key and key in seen):
                continue
            seen.add(key)
            tok = j.get("tokens") or 0
            t = totals.setdefault(j["item"], {"tokens": 0, "rounds": 0})
            t["tokens"] += sum(tok.values()) if isinstance(tok, dict) else tok
            t["rounds"] += j.get("rounds") or 0
    return totals


def slices(tr: Tracker, merged: dict[str, float], jobs: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """The met slices: merge time, lead time, whether a defect sub-issue came later, job totals."""
    every = tr.issues("all")
    names = lambda i: {lb.get("name") for lb in i.get("labels", [])}  # noqa: E731
    out = []
    for i in every:
        item = item_id(tr.ad, str(i["number"]))
        if "slice" not in names(i) or item not in merged:
            continue
        at = merged[item]
        later = [
            d for d in every
            if "defect" in names(d)
            and str(d.get("parent_issue_url", "")).endswith(f"/issues/{i['number']}")
            and _ts(d["created_at"]) > at
        ]
        out.append({
            "merged": at,
            "hours": (at - _ts(i["created_at"])) / 3600,
            "failed": bool(later),
            **jobs.get(item, {"tokens": 0, "rounds": 0}),
        })
    return out


def compute(window: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The four metrics over ``rows``; none for an empty window (no sample, no number)."""
    if not rows:
        return []
    n = len(rows)
    value = {
        "change_failure_rate": sum(r["failed"] for r in rows) / n,
        "lead_time_for_changes": statistics.median(r["hours"] for r in rows),
        "tokens_per_met_slice": sum(r["tokens"] for r in rows) / n,
        "measurer_rounds": sum(r["rounds"] for r in rows),
    }
    return [{"id": k, "window": window, "value": v, "unit": UNITS[k]} for k, v in value.items()]


def metrics(cfg: Config, tr: Tracker | None = None) -> dict[str, Any]:
    """The ``bh metrics`` result: the stored baseline (written now, once, when absent) and the
    current metrics over slices merged after it."""
    tr = tr or Tracker(cfg)
    merged, head = merges(cfg.dir)
    out_dir = cfg.file("measure_out")
    rows = slices(tr, merged, job_totals(out_dir) if out_dir and out_dir.is_dir() else {})
    path = cfg.dir / BASELINE
    if not path.exists():
        base = {"as_of": head, "metrics": compute("baseline", [r for r in rows if r["merged"] <= head])}
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x") as f:  # exclusive: the baseline is written once
                f.write(json.dumps(base, indent=2) + "\n")
        except FileExistsError:
            pass
    try:
        base = json.loads(path.read_text())
    except ValueError as e:
        raise HarnessError(f"{path} is not JSON: {e}") from e
    current = compute("current", [r for r in rows if r["merged"] > base["as_of"]])
    return {"schema_version": RESULT_VERSION, "command": "metrics", "metrics": [*base["metrics"], *current]}
