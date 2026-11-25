"""Work intake (QBC-87 to QBC-90): the program's own parent check, the Known issues cap and the
issue forms. The hierarchy is GitHub's own: a sub-issue is linked through the native sub-issue
API (``gh api``, adapter command link_parent), never by a label or a body convention alone.

OSS checked before writing this module: GitHub issue forms (the form's required Parent field is
the only place the parent can be asked for; forms cannot link), GitHub sub-issues REST API (the
link), check-jsonschema's vendor.github-issue-forms schema (validates the forms; the tests run
it). Not used: a GitHub Action (QBC-89, nothing may depend on CI); a local "told" state file (the
teaching comment on the issue is the record that it was told, so it holds across machines).
"""

import re
import shutil
from pathlib import Path
from typing import Any

from bhcore import HARNESS_DIR, Config
from bhtracker import Tracker, TrackerError

FORMS_DIR = HARNESS_DIR.parent / "templates" / ".github" / "ISSUE_TEMPLATE"
MARKER = "<!-- bh:no-parent -->"
NO_PARENT = (
    "No parent decision. Every issue sits under a decision's tracking issue: pick one, "
    "or start a decision if this is a new capability."
)
NO_GOAL = (
    "No goal. A decision sits under a goal: set its milestone, or ask the owner "
    "which goal this capability serves."
)
_LINE = re.compile(r"^\s*- \[[ xX]\] ", re.M)
_RULE_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")


def form_field(body: str | None, label: str) -> str:
    """The value a GitHub issue form renders under its ``### <label>`` heading ("" when absent)."""
    m = re.search(rf"^###\s+{re.escape(label)}\s*\n+(.*?)(?=^###\s|\Z)", body or "", re.M | re.S)
    return m.group(1).strip() if m else ""


def parent_of_body(body: str | None) -> int | None:
    """The #number a form's required Parent field holds."""
    m = re.match(r"#?(\d+)", form_field(body, "Parent"))
    return int(m.group(1)) if m else None


def rules_of_body(body: str | None) -> list[str]:
    """The rule ids a defect form's optional Rule field names (bug-analysis ``Rule:``); none for
    "None: <why>", an empty field or GitHub's "_No response_"."""
    value = form_field(body, "Rule")
    return [] if value.lower().startswith("none") else list(dict.fromkeys(_RULE_ID.findall(value)))


def check_parents(tr: Tracker) -> dict[str, list[Any]]:
    """The parent check for open issues (QBC-88, QBC-89). An issue with a Parent field and no
    native parent is linked as a sub-issue; one with neither gets the teaching comment once (the
    comment carries a marker, so a repeat finds it and says nothing). A decision needs a
    milestone, not a parent. The Known issues list is exempt."""
    out: dict[str, list[Any]] = {"linked": [], "taught": [], "already": [], "failed": []}
    known = str(tr.conf.get("known_issues") or "")
    for i in tr.issues("open"):
        n = i["number"]
        decision = any(lb.get("name") == "decision" for lb in i.get("labels", []))
        if i.get("parent_issue_url") or str(n) == known or (decision and i.get("milestone")):
            continue
        try:
            parent = None if decision else parent_of_body(i.get("body"))
            if parent:
                tr.rest("link_parent", parent=parent, child_id=i["id"])
                out["linked"].append({"number": n, "parent": parent})
            elif any(MARKER in c.get("body", "") for c in tr.comments(n)):
                out["already"].append(n)
            else:
                tr.rest("comment", False, ref=n, body=f"{MARKER}\n{NO_GOAL if decision else NO_PARENT}")
                out["taught"].append(n)
        except TrackerError as e:
            out["failed"].append({"number": n, "error": str(e)[:200]})
    return out


def known_add(cfg: Config, tr: Tracker, line: str) -> dict[str, Any]:
    """Add one line to the single Known issues list (QBC-87, QBC-90), or refuse with the teaching
    message: at the limit (limits.known_issues, default 100) a line is fixed and removed first;
    a line names its parent decision or slice."""
    ref = tr.conf.get("known_issues")
    if not ref:
        raise TrackerError("no Known issues list: set config tracker.known_issues (its issue ref)")
    cap = cfg.limit("known_issues")
    body = (tr.rest("issue", ref=ref).get("body") or "").rstrip("\n")
    count = len(_LINE.findall(body))
    if count >= cap:
        msg = (
            f"Known issues holds {count} of {cap} lines. It is the only backlog and is bounded: "
            f"fix a line and remove it before adding another. The limit is policy "
            f"(config limits.known_issues)."
        )
        return {"added": False, "count": count, "limit": cap, "message": msg}
    if not re.search(r"#\d+", line):
        msg = (
            "A Known issues line names its parent decision or slice as #number, so it "
            "is found again; add the parent and retry."
        )
        return {"added": False, "count": count, "limit": cap, "message": msg}
    tr.rest("set_body", False, ref=ref, body=f"{body}\n- [ ] {line.strip()}\n".lstrip("\n"))
    return {"added": True, "count": count + 1, "limit": cap}


def install_forms(root: Path, approved: bool) -> dict[str, Any]:
    """Write the shipped issue forms into the project's .github/ISSUE_TEMPLATE/ (a standard
    file, QBC-61 D), only when the owner approved; never over a file the project already has."""
    forms = sorted(FORMS_DIR.glob("*.yml"))
    dest = root / ".github" / "ISSUE_TEMPLATE"
    if not approved:
        missing = [f".github/ISSUE_TEMPLATE/{f.name}" for f in forms if not (dest / f.name).exists()]
        ask = (
            f"The plugin ships {len(forms)} issue files (decision, slice, defect forms and "
            "config with blank issues off). Ask the owner once; on yes, run `bh run --approve forms` "
            "to write them to .github/ISSUE_TEMPLATE/."
        )
        return {"written": [], "skipped": [], "pending": missing, "ask": ask}
    dest.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for f in forms:
        (skipped if (dest / f.name).exists() else written).append(f.name)
        if f.name in written:
            shutil.copyfile(f, dest / f.name)
    return {"written": written, "skipped": skipped}
