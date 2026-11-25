"""bh decide RECORD (R9, P6, QBC-69): a fresh ``claude -p`` judge scores the options of a decision
record it did not write.

The proposer (the session that wrote the MADR 4.0 record) never judges: the judge is a separate
job with no session of the proposer's, and it reads a copy of the record cut before its
"Decision Outcome" heading, so the proposer's pick never reaches it. The judge's options,
recommendation, objections and falsifying calls are the result; the approver reads both.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import bhrules
from bhcore import RESULT_VERSION, HarnessError

OUTCOME = re.compile(r"^(#+)\s*Decision Outcome\b.*$", re.M | re.I)  # MADR 4.0's outcome section


def without_outcome(text: str) -> str:
    """The record with its Decision Outcome section (to the next heading of its level or higher) cut out;
    the sections after it, such as "Pros and Cons of the Options", stay."""
    m = OUTCOME.search(text)
    if not m:
        return text
    level = len(m.group(1))
    nxt = re.compile(rf"^#{{1,{level}}}\s", re.M).search(text, m.end())
    return text[: m.start()] + (text[nxt.start() :] if nxt else "")


async def decide(orch: Any, record: Path) -> dict[str, Any]:
    if not record.is_file():
        raise HarnessError(f"{record}: no decision record (MADR 4.0 markdown) at that path")
    text = record.read_text()
    blind = orch.jobs_dir / f"decide-{record.stem}.md"
    orch.jobs_dir.mkdir(parents=True, exist_ok=True)
    blind.write_text(without_outcome(text))
    # the record's own lines (its outcome among them, QBC-112) never reach the judge of that record
    own = {k for k, v in bhrules.project_rule_rows(orch.cfg).items() if (orch.cfg.dir / v["source"].rsplit(":", 1)[0]).resolve() == record.resolve()}
    core = {
        "record": str(blind),
        "record_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "rules": [r for r in bhrules.project_rules(orch.cfg) if r["id"] not in own],  # the selection, never the whole catalog (QBC-106)
    }
    j = await orch.job("judge", f"decide:{record.stem}", core, {}, "Judge the options of the record named in the input file.")
    out = j.get("output") or {}
    jobs = orch.job_table()
    for row in jobs:
        if row.get("role") == "judge":
            row["objections"] = out.get("objections", [])
            row["falsifying_calls"] = out.get("falsifying_calls", [])
    res = {
        "schema_version": RESULT_VERSION,
        "command": "decide",
        "options": out.get("options", []),
        "recommended": out.get("recommended", ""),
        "jobs": jobs,
    }
    if orch.errors:
        res["facts"] = [{"kind": "job_error", "detail": e} for e in orch.errors]
    return res


def print_result(res: dict[str, Any]) -> int:
    print(json.dumps(res, indent=2))
    return 1 if res.get("facts") else 0
