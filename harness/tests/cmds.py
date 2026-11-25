"""The harness's library calls the tests drive, with the argument shape the removed ``bh-*`` scripts had.

The scripts were thin wrappers: parse arguments, call one function of ``bhcore`` or ``bhtracker``,
print its result as JSON, exit 2 on a ``HarnessError``. The orchestrator calls the functions
directly, so the scripts are gone and the tests call them here, in process. ``run`` returns
``(exit code, stdout text)`` like a subprocess would.
"""

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import bhcore  # noqa: E402
import bhtracker  # noqa: E402
from bhcore import SUMMARY_CAP, Config, HarnessError  # noqa: E402

ERRORS = (HarnessError, bhtracker.HarnessError, OSError, ValueError, KeyError, TypeError)


def _parser(name):
    ap = argparse.ArgumentParser(prog=name)
    ap.add_argument("--config", default=".brick-harness/config.json")
    return ap


def _read(src, stdin):
    raw = stdin if src == "-" else Path(src).read_text()
    doc = bhcore.loads(raw) if (raw or "").strip() else []
    return doc


def _summary(cfg, s):
    out = cfg.file("measure_out")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "state.json"
    path.write_text(json.dumps(s, sort_keys=True, separators=(",", ":")))
    unmet = [b["id"] for b in s["bricks"] if b["status"] != "met"]
    counts: dict[str, int] = {}
    for b in s["bricks"]:
        counts[b["status"]] = counts.get(b["status"], 0) + 1
    cap = SUMMARY_CAP

    def cut(xs):
        return xs[:cap], max(0, len(xs) - cap)

    ready, ready_more = cut(s["ready"])
    ready_system, ready_system_more = cut(s["ready_system"])
    unmet_cut, unmet_more = cut(unmet)
    problems, problems_more = cut(s["problems"])
    return {
        "file": str(path), "head": s["head"], "plan_head": s["plan_head"], "all_met": s["all_met"], "counts": counts,
        "ready": ready, "ready_more": ready_more, "ready_system": ready_system, "ready_system_more": ready_system_more,
        "unmet": unmet_cut, "unmet_more": unmet_more, "gaps": len(s["gaps"]), "problems": problems, "problems_more": problems_more,
    }  # fmt: skip


def _admit(argv, stdin):
    ap = _parser("admit")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    try:
        return 0, bhtracker.admit(bhtracker.Config(a.config), a.write)
    except ERRORS as e:
        return 2, {"error": str(e)}


def _branch(argv, stdin):
    ap = _parser("branch")
    ap.add_argument("--item", required=True)
    ap.add_argument("--ref", required=True)
    a = ap.parse_args(argv)
    try:
        return 0, bhcore.set_branch(Config(a.config), a.item, a.ref)
    except HarnessError as e:
        return 2, {"ok": False, "item": a.item, "error": str(e)}


def _brief(argv, stdin):
    ap = _parser("brief")
    ap.add_argument("item")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        pk = bhcore.work_packet(Config(a.config), a.item)
    except HarnessError as e:
        return 2, {"error": str(e)}
    return 0, pk


def _commit(argv, stdin):
    ap = _parser("commit")
    ap.add_argument("--message", default="brick-harness: plan")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        return 0, bhcore.commit_harness(Config(a.config), a.message, a.dry_run)
    except HarnessError as e:
        return 2, {"committed": False, "error": str(e)}


def _gaps(argv, stdin):
    ap = _parser("gaps")
    ap.add_argument("--add")
    ap.add_argument("--source", default="review")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--unmet", nargs="*", default=[])
    ap.add_argument("--brief", action="store_true")
    a = ap.parse_args(argv)
    try:
        added = []
        if a.add:
            doc = _read(a.add, stdin)
            added = doc["gaps"] if isinstance(doc, dict) else doc
        cfg = Config(a.config)
        out = bhcore.merge_gaps(cfg, added, a.source, a.write, a.unmet, bhtracker.show_resolver(cfg), lambda st, bricks: bhtracker.gap_facts(cfg, st, bricks), bhtracker.parent_is_feature(cfg))
        if a.brief:
            out = {**{k: v for k, v in out.items() if k != "gaps"}, "gaps_total": len(out["gaps"])}
        return 0, out
    except ERRORS as e:
        return 2, {"error": str(e), "gaps": []}


def _merge(argv, stdin):
    a = _parser("merge").parse_args(argv)
    try:
        return 0, bhcore.merge_unmerged(Config(a.config))
    except HarnessError as e:
        return 2, {"error": str(e), "merged": [], "conflicts": [], "remeasure": []}


def _rank(argv, stdin):
    ap = _parser("rank")
    ap.add_argument("--input")
    ap.add_argument("--add")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--review-input", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    def items(src):
        doc = _read(src, stdin)
        if isinstance(doc, dict):
            doc = doc.get("findings", doc.get("gaps", []))
        if not isinstance(doc, list):
            raise HarnessError("input must be a JSON list")
        return doc

    try:
        if a.input:
            out = {"findings": bhcore.rank_findings(items(a.input)), "key": bhcore.RANK_KEY}
        elif a.add:
            out = bhcore.add_findings(Config(a.config), items(a.add), write=a.write)
        elif a.review_input:
            out = bhcore.review_input(Config(a.config))
        else:
            cfg = Config(a.config)
            out = {"findings": bhcore.open_findings(cfg) if a.open else bhcore.all_findings(cfg), "key": bhcore.RANK_KEY}
        return 0, out
    except ERRORS as e:
        return 2, {"error": str(e), "findings": []}


def _reconcile(argv, stdin):
    ap = _parser("reconcile")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    try:
        return 0, bhtracker.reconcile(Config(a.config), a.write)
    except ERRORS as e:
        return 2, {"error": str(e)}


def _state(argv, stdin):
    ap = _parser("state")
    ap.add_argument("--affected", metavar="REF")
    a = ap.parse_args(argv)
    try:
        cfg = Config(a.config)
        if a.affected:
            return 0, {"affected": bhcore.affected(cfg, a.affected)}
        s = bhcore.state(cfg)
    except HarnessError as e:
        return 2, {"problems": [str(e)], "config": None}
    return (1 if s["problems"] else 0), _summary(cfg, s)


COMMANDS = {
    "bh-admit": _admit, "bh-branch": _branch, "bh-brief": _brief, "bh-commit": _commit, "bh-gaps": _gaps,
    "bh-merge": _merge, "bh-rank": _rank, "bh-reconcile": _reconcile, "bh-state": _state,
}  # fmt: skip


def run(name, argv, cwd=None, env=None, stdin=None):
    """Call the command's function in process (as the removed script did); ``(exit code, stdout text)``."""
    old_cwd, old_env = os.getcwd(), dict(os.environ)
    try:
        if cwd:
            os.chdir(cwd)
        if env:
            os.environ.update(env)
        code, out = COMMANDS[name](list(argv), stdin)
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(out["text"] if name == "bh-brief" and "--json" not in argv and isinstance(out, dict) and "text" in out else json.dumps(out, sort_keys=True), end="")
    return code, buf.getvalue()
