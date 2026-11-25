"""The tracker interface (SG-15, M5 to M9): the project's own tracker, run by data.

An adapter (adapters/<name>.json, or a file the config names) maps the operations the harness
calls to shell commands and says where each entry field is in the JSON a command prints:

  ready   entries ready to take (the tracker's own filter: bd ready, a gh search query)
  show    one entry                          (merge_gaps, reconcile)
  list    live entries, to find claims held  (admit)
  claim   take an entry                      (admit; absent: no tracker-side claim)
  close   close an entry                     (reconcile only)
  reopen  reopen an entry                    (reconcile only)

Nothing is hard-coded to one tracker. With no ``tracker.adapter`` in the config there is no
tracker: the work list is bricks.json in build/value order (bhcore.state), admission and
reconciliation do nothing. Done and undone in the tracker come only from the measured status:
``close_entry`` and ``reopen_entry`` are called from ``reconcile`` alone (a test enforces it).
Measure, build and merge never call the tracker. Builders take no claim of their own: each
works on its own worktree branch ``bh/<item>``, which git refuses to check out twice.

OSS checked before writing this module (versions pinned, what each lacks):
  Beads 1.3.4 (bd): the tracker itself: ``bd ready``, ``bd update --claim`` (atomic),
    ``bd close``/``bd reopen``; prints JSON of its own shape, mapped by data (adapters/beads.json).
  gh 2.94.0 or later: GitHub Issues; ``gh issue list --search 'no:assignee -is:blocked'`` is the
    ready filter; no atomic claim (an assignee is a soft claim); JSON of its own shape.
  git 2.53.0: worktree branches stop two builders on one item inside a run; no lock across
    machines (a tracker without atomic claim has none either; recorded in decision 0001).
  jq, jsonpath-ng: not used; one path per field with [] and [key=value] is all the adapters
    need and adds no dependency to a stdlib-only plugin.
  Issue-tracker clients (PyGithub, beads' Go SDK): rejected, they bind one tracker.
  hashlib.file_digest (stdlib): the binary pin; subprocess.run cannot kill a shell's children
    on timeout, so the runner keeps its own process group.
"""

import contextlib
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import bhcore
from bhcore import (
    HARNESS_DIR,
    SUMMARY_CAP,
    Config,
    HarnessError,
    harness_lock,
    load_json,
    load_schema,
    loads,
    validate,
)

ADAPTER_DIR = HARNESS_DIR / "adapters"
HORIZON_DEFAULT = 20


class TrackerError(HarnessError):
    """A tracker command failed (exit code and the tail of its error text)."""

    def __init__(self, msg: str, code: int | None = None, text: str = "") -> None:
        super().__init__(msg)
        self.code, self.text = code, text


class TrackerTimeout(TrackerError):
    """A command outlived its timeout: its effect is unknown (look it up before any retry)."""


# ---------------------------------------------------------------- command templates


def render(tpl: str, vals: dict[str, Any]) -> str:
    """Fill {name} placeholders, each shell-quoted. A part in [square brackets] that holds a
    placeholder is left out when any value in it is empty; a bare placeholder with no value
    is an error."""

    def empty(n: str) -> bool:
        return vals.get(n) in (None, "", [], {})

    def group(m: re.Match[str]) -> str:
        inner = m.group(1)
        return "" if any(empty(n) for n in re.findall(r"\{(\w+)\}", inner)) else inner

    tpl = re.sub(r"\[([^\[\]]*\{\w+\}[^\[\]]*)\]", group, tpl)

    def sub(m: re.Match[str]) -> str:
        n = m.group(1)
        if n not in vals or vals[n] is None:
            raise HarnessError(f"placeholder {{{n}}} has no value in: {tpl}")
        return shlex.quote(str(vals[n]))

    return re.sub(r"\{(\w+)\}", sub, tpl)


def _exec(cmd: str, cwd: Path, timeout: float, env: dict[str, str]) -> tuple[int, str, str]:
    """Run one command in its own process group; (exit, stdout, stderr)."""
    p = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise TrackerTimeout(f"timeout after {timeout}s", None) from None
    return p.returncode, out, err


# ---------------------------------------------------------------- reading the tracker's JSON

_PATH = re.compile(r"(\w+)(\[(?:(\w+)=([^\]]*))?\])?")


def _pick(doc: Any, path: str) -> Any:
    """The value at ``path``: a.b, a[] (map over a list), a[k=v] (keep list items whose k is
    v). A path that maps a list gives a list, else one value or None."""
    cur: list[Any] = [doc]
    many = False
    for part in path.split("."):
        m = _PATH.fullmatch(part)
        if not m:
            raise HarnessError(f"bad field path {path!r}")
        key, bracket, fk, fv = m.groups()
        nxt: list[Any] = []
        for c in cur:
            v = c.get(key) if isinstance(c, dict) else None
            if v is None or (bracket and not isinstance(v, list)):
                continue
            if bracket:
                many = True
                nxt += [
                    x for x in v if fk is None or (isinstance(x, dict) and str(x.get(fk)) == fv)
                ]
            else:
                nxt.append(v)
        cur = nxt
    return cur if many else (cur[0] if cur else None)


def entry_of(ad: dict[str, Any], op: str, raw: dict[str, Any]) -> dict[str, Any]:
    """One entry in the schema's shape from what the tracker printed."""
    spec = {
        **{k: k for k in ("ref", "title", "body", "state", "type", "assignee", "parent", "deps")},
        **ad.get("fields", {}),
        **ad.get("by_op", {}).get(op, {}),
    }
    e: dict[str, Any] = {k: _pick(raw, p) for k, p in spec.items()}
    if isinstance(e["assignee"], list):
        e["assignee"] = e["assignee"][0] if e["assignee"] else None
    st = e["state"]
    e["state"] = ad.get("states", {}).get(st, st) if isinstance(st, str) else st
    native = {v: k for k, v in ad.get("types", {}).items()}
    e["type"] = native.get(e["type"], "other") if e["type"] is not None else "other"
    e["deps"] = [str(x) for x in (e["deps"] or [])]
    for k in ("ref", "parent"):
        e[k] = str(e[k]) if e[k] is not None else None
    return {k: v for k, v in e.items() if v is not None or k in ("assignee", "parent")}


# ---------------------------------------------------------------- adapters and the pin


def platform_key() -> str:
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    m = platform.machine().lower()
    return f"{platform.system().lower()}_{arch.get(m, m)}"


def configured(cfg: Config) -> bool:
    """A tracker is configured when the config's tracker object names an adapter."""
    return bool((cfg.data.get("tracker") or {}).get("adapter"))


def load_adapter(cfg: Config) -> dict[str, Any]:
    """The configured adapter with the config's command overrides."""
    conf = cfg.data.get("tracker") or {}
    name = conf.get("adapter")
    if not name:
        raise HarnessError("no tracker configured (config tracker.adapter)")
    path = ADAPTER_DIR / f"{name}.json"
    if "/" in name or name.endswith(".json"):
        path = (cfg.dir / name).resolve()
    if not path.is_file():
        raise HarnessError(f"tracker adapter {name!r} not found ({path})")
    doc: dict[str, Any] = load_json(path)
    schema = load_schema("tracker")
    errs = validate(doc, schema["$defs"]["adapter"], schema, "$")
    if errs:
        raise HarnessError(f"{path} fails the adapter schema: " + "; ".join(errs[:5]))
    doc["commands"] = {**doc["commands"], **conf.get("commands", {})}
    return doc


def slug(ref: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-")


def item_id(ad: dict[str, Any], ref: str) -> str:
    """The item id derived from a tracker ref, so taking an entry twice does nothing."""
    return f"{ad.get('id_prefix') or slug(ad['name'])}-{slug(ref)}"


def actor_of(cfg: Config) -> str:
    """The name the harness acts as: config tracker.actor, else a hash of host and clone path
    (a stable clone identity, never a person)."""
    given = (cfg.data.get("tracker") or {}).get("actor")
    if given:
        return str(given)
    return "bh-" + hashlib.sha256(f"{socket.gethostname()}\0{cfg.dir}".encode()).hexdigest()[:10]


# ---------------------------------------------------------------- the runner


class Tracker:
    """One configured tracker. ``facts`` collects what a caller reports (claimed-elsewhere);
    nothing here changes an item's status."""

    def __init__(self, cfg: Config, adapter: dict[str, Any] | None = None) -> None:
        self.cfg = cfg
        self.conf: dict[str, Any] = cfg.data.get("tracker") or {}
        self.ad = adapter or load_adapter(cfg)
        self.actor = actor_of(cfg)
        self.timeout = float(self.conf.get("timeout_s", 60))
        self.read_limit = cfg.limit("tracker_read")
        self.facts: list[dict[str, Any]] = []
        self.env = dict(os.environ)
        self._check_pin()
        self.env["BH_ACTOR"] = self.actor

    def _check_pin(self) -> None:
        """A binary whose sha256 is not the pinned one is not run (a supply-chain check, not
        a gate on work): the tracker is then unreachable for this run, with the fact."""
        pin = self.ad.get("pin")
        found = shutil.which(pin["binary"], path=self.env.get("PATH", "")) if pin else None
        if not pin or found is None:  # no binary: every operation fails as unreachable
            return
        found = os.path.realpath(found)
        want = (self.conf.get("pin") or {}).get("sha256") or pin["sha256"].get(platform_key())
        with open(found, "rb") as f:
            got = hashlib.file_digest(f, "sha256").hexdigest()
        if want is not None and got == want:
            self.env["PATH"] = os.pathsep.join([str(Path(found).parent), self.env["PATH"]])
            return
        note = (
            f"no pin for {platform_key()}"
            if want is None
            else f"sha256 {got} is not the pin {want}"
        )
        raise TrackerError(
            f"{pin['binary']} at {found}: {note}; not run (config tracker.pin.sha256)"
        )

    @property
    def name(self) -> str:
        return str(self.ad["name"])

    def has(self, op: str) -> bool:
        return op in self.ad["commands"]

    def _run(self, op: str, vals: dict[str, Any], parse: bool = True) -> Any:
        tpl = self.ad["commands"].get(op)
        if not tpl:
            raise TrackerError(f"tracker {self.name} has no command for {op}")
        cmd = render(tpl, {"actor": self.actor, **vals})
        code, out, err = _exec(cmd, self.cfg.dir, self.timeout, self.env)
        if code != 0:
            raise TrackerError(
                f"tracker.{op} exited {code}: {(err or out).strip()[-300:]}", code, err or out
            )
        if not parse:
            return None
        try:
            return loads(out)
        except ValueError as e:
            raise TrackerError(f"tracker.{op} printed no JSON: {e}") from e

    def _entries(self, op: str, doc: Any) -> list[dict[str, Any]]:
        if isinstance(doc, dict):
            doc = [doc]
        if not isinstance(doc, list):
            raise TrackerError(f"tracker.{op} printed neither a list nor an entry")
        out = [entry_of(self.ad, op, r) for r in doc if isinstance(r, dict)]
        schema = load_schema("tracker")
        errs = validate(out, schema["$defs"]["entries"], schema, "$")
        if errs:
            raise TrackerError(
                f"tracker.{op} output fails the entry schema: " + "; ".join(errs[:5])
            )
        return out

    def native(self, kind: str) -> str:
        return str(self.ad.get("types", {}).get(kind, kind))

    def missing(self, e: TrackerError) -> bool:
        pat = self.ad.get("missing")
        return bool(pat and re.search(pat, e.text or str(e)))

    # -- reads ----------------------------------------------------------------------

    def show(self, ref: str) -> dict[str, Any]:
        es = self._entries("show", self._run("show", {"ref": ref}))
        if not es:
            raise TrackerError(f"tracker.show: no entry {ref}")
        return es[0]

    def list(self, limit: int | None = None, type: str | None = None) -> dict[str, Any]:
        """Live entries (open, in progress, deferred), at most ``limit`` (default
        limits.tracker_read); one more is asked for, so a cut is reported as ``more``."""
        limit = limit or self.read_limit
        es = self._entries("list", self._run("list", {"limit": limit + 1}))
        more = len(es) > limit
        return {"entries": [e for e in es[:limit] if not type or e["type"] == type], "more": more}

    def ready(
        self, limit: int | None = None, parent: str | None = None, type: str = "item"
    ) -> dict[str, Any]:
        """Entries ready to take, in the tracker's own order: the tracker's own filter."""
        limit = limit or self.read_limit
        vals = {"limit": limit + 1, "parent": parent, "type": self.native(type)}
        es = self._entries("ready", self._run("ready", vals))
        return {"entries": es[:limit], "more": len(es) > limit}

    # -- writes ---------------------------------------------------------------------

    def close_entry(self, ref: str, reason: str, as_actor: str | None = None) -> None:
        """Close an entry acting as ``as_actor`` (the claim holder). Only ``reconcile`` calls it."""
        self._run("close", {"ref": ref, "reason": reason, "actor": as_actor or self.actor}, False)

    def reopen_entry(self, ref: str, reason: str, as_actor: str | None = None) -> None:
        """Reopen an entry acting as ``as_actor``. Only ``reconcile`` calls it."""
        self._run("reopen", {"ref": ref, "reason": reason, "actor": as_actor or self.actor}, False)

    def claim(self, ref: str) -> dict[str, Any]:
        """Take an entry: ``{claimed, holder, by}``. The adapter's claim command when it has
        one (bd update --claim is atomic; a gh assignee is soft); without one the entry is
        taken, and builders are kept apart by their worktree branches ``bh/<item>``."""
        if not self.has("claim"):
            return {"claimed": True, "holder": self.actor, "by": "branch"}
        try:
            self._run("claim", {"ref": ref}, False)
        except TrackerError as e:
            if isinstance(e, TrackerTimeout):
                raise
            holder = self.show(ref).get("assignee")
            if holder and holder != self.actor:
                self.facts.append({"kind": "claimed-elsewhere", "ref": ref, "holder": holder})
                return {"claimed": False, "holder": holder, "by": "tracker"}
            raise
        return {"claimed": True, "holder": self.actor, "by": "tracker"}


# ---------------------------------------------------------------- admission (M9)


def _plan_items(cfg: Config) -> list[dict[str, Any]]:
    p = cfg.file("bricks")
    if p is None or not p.exists():
        return []
    items: list[dict[str, Any]] = load_json(p, "bricks")["bricks"]
    return items


def admission_order(
    cfg: Config, entries: list[dict[str, Any]], st: dict[str, Any], ad: dict[str, Any]
) -> list[dict[str, Any]]:
    """The order candidates are taken in, one call: the value order of work (bhcore.value_queue,
    most valuable first). An entry that is already an item (by its derived id or a ref the
    item names) takes that item's place in the queue; an entry that is not yet an item cannot
    be ranked and follows the queued ones in the tracker's own order."""
    queue = {i: n for n, i in enumerate(bhcore.value_queue(cfg, st))}
    by_ref = {r: b["id"] for b in _plan_items(cfg) for r in b.get("refs", [])}

    def rank(e: dict[str, Any]) -> int:
        i = by_ref.get(e["ref"]) or item_id(ad, e["ref"])
        return queue.get(i, len(queue))

    return sorted(entries, key=rank)  # stable: equal ranks keep the tracker's order


def _append_items(cfg: Config, new: list[dict[str, Any]]) -> None:
    p = cfg.file("bricks")
    assert p is not None
    doc = load_json(p, "bricks") if p.exists() else {"bricks": []}
    ids = {b["id"] for b in doc["bricks"]}
    doc["bricks"] += [n for n in new if n["id"] not in ids]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(p)


def admit(cfg: Config, write: bool = False, tr: Tracker | None = None) -> dict[str, Any]:
    """Take entries from the tracker into the plan, at most the room the horizon leaves.

    room = horizon.items minus the items not met (blocked ones count: rolling wave, Kanban WIP).
    ready(limit=room, type=item, parent=goal) gives the leaves in admission_order; entries we
    claimed earlier but did not write (a crash between claim and write) are adopted first.
    Each entry is claimed before it is written to bricks.json with an id derived from its ref,
    so a re-admission is a no-op. Without ``write`` nothing is claimed or written. With no
    tracker configured it does nothing: bricks.json is the work list. Facts only: not_admitted,
    stalled (with the blocking gap ids), claimed_elsewhere, claim_held, unreachable."""
    st = bhcore.state(cfg)
    horizon = int(cfg.data.get("horizon", {}).get("items", HORIZON_DEFAULT))
    not_met = [b for b in st["bricks"] if b["status"] != "met"]
    room = max(0, horizon - len(not_met))
    out: dict[str, Any] = {
        "tracker": None,
        "horizon": horizon,
        "not_met": len(not_met),
        "room": room,
        "admit": [],
        "admitted": [],
        "not_admitted": 0,
        "not_admitted_at_least": False,
        "stalled": None,
        "claimed_elsewhere": [],
        "claim_held": [],
        "unreachable": None,
        "facts": [],
        "dry_run": not write,
    }
    try:
        if tr is None:
            if not configured(cfg):
                return out
            tr = Tracker(cfg)
    except HarnessError as e:
        out["unreachable"] = str(e)
        out["facts"] = []
        return out
    out["tracker"] = tr.name
    out["facts"] = tr.facts
    items = _plan_items(cfg)
    taken_ids = {b["id"] for b in items}
    taken_refs = {r for b in items for r in b.get("refs", [])}
    goal = (cfg.data.get("tracker") or {}).get("goal")
    mine: list[dict[str, Any]] = []
    try:
        if tr.has("list"):
            held = [
                e
                for e in tr.list(type="item")["entries"]
                if e.get("assignee") and e["ref"] not in taken_refs
            ]
            mine = [e for e in held if e["assignee"] == tr.actor]
            rel = tr.ad.get("release")
            out["claim_held"] = [
                {
                    "ref": e["ref"],
                    "holder": e["assignee"],
                    **({"release": render(rel, {"ref": e["ref"]})} if rel else {}),
                }
                for e in held
                if e["assignee"] != tr.actor
            ][:SUMMARY_CAP]
        ready = (
            tr.ready(limit=cfg.limit("tracker_read"), parent=goal, type="item")
            if room
            else {"entries": [], "more": False}
        )
    except TrackerError as e:
        out["unreachable"] = str(e)
        return out
    seen: set[str] = set()
    fresh = []
    for e in [*mine, *admission_order(cfg, ready["entries"], st, tr.ad)]:
        if e["ref"] in taken_refs or e["ref"] in seen or item_id(tr.ad, e["ref"]) in taken_ids:
            continue
        seen.add(e["ref"])
        fresh.append(e)
    picked = fresh[:room]
    out["not_admitted"] = len(fresh) - len(picked)
    out["not_admitted_at_least"] = bool(ready["more"])
    out["admit"] = [
        {"ref": e["ref"], "id": item_id(tr.ad, e["ref"]), "title": e["title"]} for e in picked
    ]
    if room == 0:
        blocked = {b["id"]: b["blocked_by"] for b in not_met if b["blocked_by"]}
        out["stalled"] = {
            "horizon": horizon,
            "blocked": dict(list(blocked.items())[:SUMMARY_CAP]),
        }
    if not write:
        return out
    taken: list[dict[str, Any]] = []
    with harness_lock(cfg):
        for e, a in zip(picked, out["admit"], strict=True):
            try:
                c = tr.claim(e["ref"])
            except TrackerError as err:
                out["unreachable"] = str(err)
                break
            if not c["claimed"]:
                out["claimed_elsewhere"].append({"ref": e["ref"], "holder": c.get("holder")})
                continue
            taken.append({"id": a["id"], "job": e["title"], "kind": "change", "refs": [e["ref"]]})
            out["admitted"].append(a["id"])
        if taken:
            _append_items(cfg, taken)
    out["facts"] = tr.facts
    return out


# ---------------------------------------------------------------- reconciliation (M8)


def mismatches(
    cfg: Config, tr: Tracker, st: dict[str, Any], bricks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(mismatches, facts) for every item that names tracker refs: an entry open while its
    item is measured met at HEAD, an entry closed while it is not met; ref-missing and
    tracker-unreachable are facts. Reads one entry at a time (a bounded loop, never a cursor)."""
    status = {b["id"]: b["status"] for b in st["bricks"]}
    found: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for b in bricks:
        if b["id"] not in status:
            continue
        for ref in b.get("refs", []):
            try:
                e = tr.show(ref)
            except TrackerTimeout as err:
                facts.append({"kind": "tracker-unreachable", "ref": ref, "note": str(err)[:200]})
                return found, facts
            except TrackerError as err:
                if tr.missing(err):
                    facts.append({"kind": "ref-missing", "item": b["id"], "ref": ref})
                    continue
                facts.append({"kind": "tracker-unreachable", "ref": ref, "note": str(err)[:200]})
                return found, facts
            met = status[b["id"]] == "met"
            if met and e["state"] != "closed":
                found.append({"kind": "tracker-open-met", "item": b["id"], "ref": ref, "entry": e})
            elif not met and e["state"] == "closed":
                found.append(
                    {"kind": "tracker-closed-unmet", "item": b["id"], "ref": ref, "entry": e}
                )
    return found, facts


def reconcile(cfg: Config, write: bool = False, tr: Tracker | None = None) -> dict[str, Any]:
    """The only caller of close and reopen. After the scoreboard commit at HEAD and before
    admission: an entry whose item is measured met at HEAD and is open is closed, with the sha
    as the reason (the scoreboard and targets at that sha are in git), acting as its claim
    holder; an entry closed while its item is not met at HEAD is reopened. Only entries named
    by items in the plan are touched; nothing is deleted; writes only on a mismatch, so a
    repeat is a no-op; every mismatch is a fact. Without ``write`` it only lists them. With no
    tracker configured it does nothing."""
    out: dict[str, Any] = {
        "tracker": None,
        "checked": 0,
        "closed": [],
        "reopened": [],
        "mismatches": [],
        "facts": [],
        "dry_run": not write,
    }
    try:
        if tr is None:
            if not configured(cfg):
                return out
            tr = Tracker(cfg)
    except HarnessError as e:
        out["facts"].append({"kind": "tracker-unreachable", "note": str(e)[:200]})
        return out
    out["tracker"] = tr.name
    st = bhcore.state(cfg)
    bricks = _plan_items(cfg)
    out["checked"] = sum(len(b.get("refs", [])) for b in bricks)
    found, facts = mismatches(cfg, tr, st, bricks)
    out["facts"] = [*tr.facts, *facts]
    head = (st.get("head") or "")[:12]
    for m in found:
        out["mismatches"].append({k: m[k] for k in ("kind", "item", "ref")})
        if not write:
            continue
        who = m["entry"].get("assignee") or tr.actor
        try:
            if m["kind"] == "tracker-open-met":
                tr.close_entry(m["ref"], f"measured met at {head}", who)
                out["closed"].append(m["ref"])
            else:
                tr.reopen_entry(m["ref"], f"not met at {head}", who)
                out["reopened"].append(m["ref"])
        except TrackerError as err:
            out["facts"].append(
                {"kind": "tracker-write-failed", "ref": m["ref"], "note": str(err)[:200]}
            )
    return out


# ---------------------------------------------------------------- facts for merge_gaps


def gap_facts(
    cfg: Config, st: dict[str, Any], bricks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mismatches between the tracker and the measured status, as facts of the gaps report
    (never scored). Nothing when no item names a ref."""
    if not any(b.get("refs") for b in bricks):
        return []
    try:
        tr = Tracker(cfg)
    except HarnessError as e:
        return [{"kind": "tracker-unreachable", "note": str(e)[:200]}]
    found, facts = mismatches(cfg, tr, st, bricks)
    return [*tr.facts, *facts, *[{k: m[k] for k in ("kind", "item", "ref")} for m in found]]


def show_resolver(cfg: Config) -> Callable[[str], dict[str, Any]] | None:
    """tracker.show with a per-run cache for merge_gaps (a target source '<ref>: "<quote>"')."""
    tr: list[Tracker] = []
    cache: dict[str, dict[str, Any]] = {}

    def show(ref: str) -> dict[str, Any]:
        if ref not in cache:
            if not tr:
                tr.append(Tracker(cfg))
            cache[ref] = tr[0].show(ref)
        return cache[ref]

    return show


def parent_is_feature(cfg: Config) -> Callable[[dict[str, Any]], bool]:
    """For the INVEST fact valuable: an item whose tracker entry has a parent of type feature.
    False when the tracker cannot be read (a fact elsewhere says so)."""
    tr: list[Tracker] = []

    def check(b: dict[str, Any]) -> bool:
        if not b.get("refs"):
            return False
        try:
            if not tr:
                tr.append(Tracker(cfg))
            for ref in b["refs"]:
                parent = tr[0].show(ref).get("parent")
                if parent and tr[0].show(parent)["type"] == "feature":
                    return True
        except HarnessError:
            return False
        return False

    return check
