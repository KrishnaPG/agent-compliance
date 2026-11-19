"""The tracker interface (SG-15, mechanisms M5 to M10): one runner for nine operations.

The tracker is the project's own system. An adapter (adapters/<name>.json, or a file the
config names) maps each operation (ready, show, create, link, claim, close, reopen, defer,
list) to a shell command and says where each entry field is in the JSON that command prints;
the runner quotes the values, runs the command with a timeout, reads the output into the
entry shape of schema/tracker.schema.json and checks it. Nothing is hard-coded to one tracker.

Measure, build and merge never call the tracker. Only bh-admit (ready, claim, create), bh-file
(list, create, link), bh-gaps (show) and bh-reconcile (show, close, reopen) do. `close_entry`
and `reopen_entry` are called from `reconcile` alone (tests/test_tracker.py enforces it).

OSS checked before writing this module (pinned versions, what each lacks):
  Beads 1.3.4 (bd): the tracker itself: hierarchy, atomic claim, typed dependencies, defer,
    metadata; it has no JSON shape of ours, so its output is mapped by data (adapters/beads.json).
  gh 2.94.0 or later: GitHub Issues; no atomic claim, no defer, no ready filter, no metadata
    field; the create-only claim ref, labels and a body marker stand in (adapters/github.json).
  git 2.53.0: the create-only ref update (--force-with-lease=<ref>:) is the claim where the
    tracker has none; the only native lock available across clones.
  jq and JSONPath libraries (jq, jsonpath-ng): not used; one path per field with [] and
    [key=value] is all the adapters need, and adds no dependency to a stdlib-only plugin.
  Issue-tracker clients (PyGithub, beads' Go SDK): rejected, they bind one tracker.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bhcore
from bhcore import (
    HARNESS_DIR,
    HDIR,
    PLUGIN_ROOT,
    Config,
    HarnessError,
    _git_ok,
    git_top,
    harness_lock,
    load_json,
    load_schema,
    loads,
    validate,
)

OPS = ("ready", "show", "create", "link", "claim", "close", "reopen", "defer", "list")
STATES = ("open", "in_progress", "closed", "deferred")
ADAPTER_DIR = HARNESS_DIR / "adapters"
BIN_DIR = PLUGIN_ROOT / "bin"
HORIZON_DEFAULT = 20
CLAIM_PREFIX = "bh-claim"
DEFAULT_ADAPTER = "files"


class TrackerError(HarnessError):
    """A tracker command failed (exit code and the tail of its error text)."""

    def __init__(self, msg: str, code: int | None = None, text: str = "") -> None:
        super().__init__(msg)
        self.code, self.text = code, text


class TrackerTimeout(TrackerError):
    """A command outlived its timeout: its effect is unknown (look it up before any retry)."""


# ---------------------------------------------------------------- command templates


def _quote(v: Any) -> str:
    if isinstance(v, list | tuple):
        v = ",".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = json.dumps(v, sort_keys=True, separators=(",", ":"))
    return shlex.quote(str(v))


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
        return _quote(vals[n])

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


def _pick(doc: Any, path: str) -> Any:
    """The value at ``path``: a.b, a[] (map over a list), a[k=v] (keep list items whose k is
    v), a[0]. A path that maps a list gives a list, else one value or None."""
    cur: list[Any] = [doc]
    many = False
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)(?:\[(?:(\w+)=([^\]]*)|(\d+))?\])?", part)
        if not m:
            raise HarnessError(f"bad field path {path!r}")
        key, fk, fv, idx = m.group(1), m.group(2), m.group(3), m.group(4)
        bracket = part != key
        nxt: list[Any] = []
        for c in cur:
            v = c.get(key) if isinstance(c, dict) else None
            if v is None:
                continue
            if bracket:
                if not isinstance(v, list):
                    continue
                if idx is not None:
                    if int(idx) < len(v):
                        nxt.append(v[int(idx)])
                    continue
                many = True
                nxt += [
                    x for x in v if fk is None or (isinstance(x, dict) and str(x.get(fk)) == fv)
                ]
            else:
                nxt.append(v)
        cur = nxt
    if many:
        return cur
    return cur[0] if cur else None


def _field(raw: dict[str, Any], spec: Any) -> Any:
    if isinstance(spec, str):
        spec = {"path": spec}
    v = _pick(raw, spec["path"])
    if v is None:
        return None

    def one(x: Any) -> Any:
        x = f"{spec.get('prefix', '')}{x}" if "prefix" in spec else x
        return spec["map"].get(x, x) if "map" in spec and isinstance(x, str) else x

    return [one(x) for x in v] if isinstance(v, list) else one(v)


META_MARK = re.compile(r"\n*<!-- bh-meta: (\{.*?\}) -->\s*$", re.S)


def _with_marker(body: str, meta: dict[str, Any]) -> str:
    return f"{body}\n\n<!-- bh-meta: {json.dumps(meta, sort_keys=True, separators=(',', ':'))} -->"


def entry_of(ad: dict[str, Any], op: str, raw: dict[str, Any]) -> dict[str, Any]:
    """One entry in the schema's shape from what the tracker printed."""
    spec = {
        **{
            k: k
            for k in (
                "ref",
                "title",
                "body",
                "state",
                "type",
                "assignee",
                "parent",
                "deps",
                "labels",
                "metadata",
                "url",
            )
        },
        **ad.get("fields", {}),
        **ad.get("by_op", {}).get(op, {}),
    }
    e: dict[str, Any] = {k: _field(raw, s) for k, s in spec.items()}
    if isinstance(e.get("assignee"), list):
        e["assignee"] = e["assignee"][0] if e["assignee"] else None
    st = e.get("state")
    states = ad.get("states", {})
    e["state"] = states.get(st, st) if isinstance(st, str) else st
    labels = [str(x) for x in (e.get("labels") or [])]
    e["labels"] = labels
    lab = ad.get("labels", {})
    if lab.get("deferred") in labels and e["state"] == "open":
        e["state"] = "deferred"
    if lab.get("parent") and not e.get("parent"):
        pre = lab["parent"]
        e["parent"] = next((x[len(pre) :] for x in labels if x.startswith(pre)), None)
    native = {v: k for k, v in ad.get("types", {}).items()}
    t = e.get("type")
    if t is None and lab.get("type"):
        t = next((x[len(lab["type"]) :] for x in labels if x.startswith(lab["type"])), None)
    e["type"] = native.get(t, "other") if t is not None else "other"
    e["deps"] = [str(x) for x in (e.get("deps") or [])]
    meta = e.get("metadata")
    body = e.get("body")
    if ad.get("metadata_in_body") and isinstance(body, str):
        m = META_MARK.search(body)
        if m:
            with contextlib.suppress(ValueError):
                meta = {**(meta or {}), **loads(m.group(1))}
            e["body"] = body[: m.start()]
    e["metadata"] = meta if isinstance(meta, dict) else {}
    if e.get("ref") is not None:
        e["ref"] = str(e["ref"])
    return {k: v for k, v in e.items() if v is not None or k in ("assignee", "parent")}


# ---------------------------------------------------------------- adapters and the pin


def platform_key() -> str:
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    m = platform.machine().lower()
    return f"{platform.system().lower()}_{arch.get(m, m)}"


def _load_adapter_file(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = load_json(path)
    schema = load_schema("tracker")
    errs = validate(doc, schema["$defs"]["adapter"], schema, "$")
    if errs:
        raise HarnessError(f"{path} fails the adapter schema: " + "; ".join(errs[:5]))
    return doc


def load_adapter(cfg: Config, name: str | None = None) -> dict[str, Any]:
    """The configured adapter with the config's overrides (commands, capabilities)."""
    conf = cfg.data.get("tracker") or {}
    name = name or conf.get("adapter") or DEFAULT_ADAPTER
    path = ADAPTER_DIR / f"{name}.json"
    if "/" in name or name.endswith(".json"):
        path = (cfg.dir / name).resolve()
    if not path.is_file():
        raise HarnessError(f"tracker adapter {name!r} not found ({path})")
    ad = _load_adapter_file(path)
    if name == (conf.get("adapter") or DEFAULT_ADAPTER):
        ad["commands"] = {**ad["commands"], **conf.get("commands", {})}
        ad["capabilities"] = {**ad["capabilities"], **conf.get("capabilities", {})}
    return ad


_HASHES: dict[tuple[str, float, int], str] = {}


def file_sha256(path: str) -> str:
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in _HASHES:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASHES[key] = h.hexdigest()
    return _HASHES[key]


def slug(ref: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-")


def item_id(ad: dict[str, Any], ref: str) -> str:
    """The item id derived from a tracker ref, so taking an entry twice does nothing."""
    return f"{ad.get('id_prefix') or slug(ad['name'])}-{slug(ref)}"


def work_dir(cfg: Config) -> Path:
    return cfg.dir / HDIR / "work"


def actor_of(cfg: Config) -> str:
    """The name the harness acts as: config tracker.actor, else a hash of host and clone path
    (a stable clone identity, never a person)."""
    given = (cfg.data.get("tracker") or {}).get("actor")
    if given:
        return str(given)
    return "bh-" + hashlib.sha256(f"{socket.gethostname()}\0{cfg.dir}".encode()).hexdigest()[:10]


# ---------------------------------------------------------------- the runner


class Tracker:
    """One configured tracker: the nine operations, their fallbacks and the facts seen.

    ``facts`` collects what a caller reports (pin-mismatch, claimed-elsewhere, ...); nothing
    here changes an item's status."""

    def __init__(self, cfg: Config, adapter: dict[str, Any] | None = None) -> None:
        self.cfg = cfg
        self.conf: dict[str, Any] = cfg.data.get("tracker") or {}
        self.ad = adapter or load_adapter(cfg)
        self.actor = actor_of(cfg)
        self.timeout = float(self.conf.get("timeout_s", 60))
        self.read_limit = cfg.limit("tracker_read")
        self.facts: list[dict[str, Any]] = []
        self.env = dict(os.environ)
        self._path_extra: list[str] = [str(BIN_DIR)]
        self.pinned_binary: str | None = None
        self._check_pin()
        self.env["PATH"] = os.pathsep.join([*self._path_extra, self.env.get("PATH", "")])
        self.env["BH_WORK_DIR"] = str(work_dir(cfg))
        self.env["BH_ACTOR"] = self.actor

    # -- the pin: a binary that does not match is not run ----------------------------

    def _check_pin(self) -> None:
        pin = self.ad.get("pin")
        if not pin:
            return
        found = shutil.which(pin["binary"], path=self.env.get("PATH", ""))
        if found is None:
            return  # no binary: every operation fails as unreachable
        found = os.path.realpath(found)
        want = (self.conf.get("pin") or {}).get("sha256") or pin["sha256"].get(platform_key())
        got = file_sha256(found)
        if want is not None and got == want:
            self.pinned_binary = found
            self._path_extra.insert(0, str(Path(found).parent))
            return
        self.facts.append(
            {
                "kind": "pin-mismatch",
                "binary": pin["binary"],
                "path": found,
                "version": pin.get("version"),
                "expected": want,
                "actual": got,
                "note": "not run; this run's tracker operations use the files adapter"
                if want is not None
                else f"no pin for {platform_key()}; not run, the files adapter is used "
                "(config tracker.pin.sha256 names one)",
            }
        )
        self.ad = _load_adapter_file(ADAPTER_DIR / "files.json")
        self.fallback = True

    fallback = False

    @property
    def name(self) -> str:
        return str(self.ad["name"])

    @property
    def caps(self) -> dict[str, bool]:
        return dict(self.ad["capabilities"])

    def native(self, kind: str) -> str:
        return str(self.ad.get("types", {}).get(kind, kind))

    # -- one operation --------------------------------------------------------------

    def _run(self, op: str, vals: dict[str, Any], variant: str | None = None) -> Any:
        tpl = self.ad["commands"].get(op)
        if isinstance(tpl, dict):
            tpl = tpl.get(variant or "default") or tpl.get("default")
        if not tpl:
            raise TrackerError(f"tracker {self.name} has no command for {op}")
        cmd = render(tpl, {"actor": self.actor, **vals})
        code, out, err = _exec(cmd, self.cfg.dir, self.timeout, self.env)
        if code != 0:
            raise TrackerError(
                f"tracker.{op} exited {code}: {(err or out).strip()[-300:]}", code, err or out
            )
        mode = self.ad.get("output", {}).get(op, "json")
        if mode == "none":
            return None
        if mode == "url-ref":
            seg = re.findall(r"[^/\s]+", out.strip().splitlines()[-1] if out.strip() else "")
            if not seg:
                raise TrackerError(f"tracker.{op} printed no URL")
            return {"ref": f"{self.ad.get('ref_prefix', '')}{seg[-1]}"}
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

    # -- reads ----------------------------------------------------------------------

    def show(self, ref: str) -> dict[str, Any]:
        es = self._entries("show", self._run("show", {"ref": ref}))
        if not es:
            raise TrackerError(f"tracker.show: no entry {ref}")
        return es[0]

    def missing(self, e: TrackerError) -> bool:
        pat = self.ad.get("missing")
        return bool(pat and re.search(pat, e.text or str(e)))

    def list(
        self,
        limit: int | None = None,
        state: str = "live",
        parent: str | None = None,
        type: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Entries in the tracker's own order, at most ``limit`` (default limits.tracker_read);
        one more is asked for, so a cut is reported as ``more``. With ``key`` only entries
        whose metadata bh_key is exactly it."""
        limit = limit or self.read_limit
        vals = {
            "limit": limit + 1,
            "state": self.ad.get("list_states", {}).get(state, state),
            "parent": parent,
            "type": self.native(type) if type else None,
            "key": key,
            "metadata_field": f"bh_key={key}" if key else None,
        }
        es = self._entries("list", self._run("list", vals))
        more = len(es) > limit
        es = es[:limit]
        if key:
            es = [e for e in es if (e.get("metadata") or {}).get("bh_key") == key]
        if parent and not self.caps["hierarchy"]:
            es = [e for e in es if e.get("parent") == parent]
        return {"entries": es, "more": more}

    def ready(
        self, limit: int | None = None, parent: str | None = None, type: str = "item"
    ) -> dict[str, Any]:
        """Entries ready to take, in the tracker's own order. The tracker filters when it can
        (ready_filter); otherwise the list is filtered here: open, not deferred, of the type,
        no open dependency, no open child, not claimed."""
        limit = limit or self.read_limit
        if self.caps["ready_filter"]:
            vals = {"limit": limit + 1, "parent": parent, "type": self.native(type)}
            es = self._entries("ready", self._run("ready", vals))
            return {"entries": es[:limit], "more": len(es) > limit}
        live = self.list(state="live")
        es = live["entries"]
        by_ref = {e["ref"]: e for e in es}
        parents = {e["parent"] for e in es if e.get("parent")}
        held = self.claimed_ids()

        def under(e: dict[str, Any]) -> bool:
            seen: set[str] = set()
            p = e.get("parent")
            while p and p not in seen:
                if p == parent:
                    return True
                seen.add(p)
                p = (by_ref.get(p) or {}).get("parent")
            return False

        out = [
            e
            for e in es
            if e["state"] == "open"
            and e["type"] == type
            and not e.get("assignee")
            and e["ref"] not in parents
            and not any(d in by_ref and by_ref[d]["state"] != "closed" for d in e["deps"])
            and item_id(self.ad, e["ref"]) not in held
            and (parent is None or under(e))
        ]
        return {"entries": out[:limit], "more": len(out) > limit or live["more"]}

    # -- writes ---------------------------------------------------------------------

    def create(
        self,
        title: str,
        body: str = "",
        type: str = "item",
        parent: str | None = None,
        deps: list[tuple[str, str]] | None = None,
        labels: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """File one entry; ``deps`` are (kind, ref). Returns its ref. Kinds the adapter's
        create cannot carry are linked afterwards."""
        deps = deps or []
        lab = self.ad.get("labels", {})
        labels = list(labels or [])
        if parent and not self.caps["hierarchy"] and lab.get("parent"):
            labels.append(f"{lab['parent']}{parent}")
        if lab.get("type") and not self.ad.get("types", {}).get("item"):
            labels.append(f"{lab['type']}{type}")
        meta = metadata or {}
        if self.ad.get("metadata_in_body") and meta:
            body = _with_marker(body, meta)
            meta = {}
        kinded = self.ad.get("deps_format") == "kinded"
        inline = deps if kinded else [d for d in deps if d[0] == "blocks"]
        vals = {
            "title": title,
            "body": body,
            "type": self.native(type),
            "parent": parent,
            "deps": [r if k == "blocks" or not kinded else f"{k}:{r}" for k, r in inline],
            "labels": labels,
            "metadata": meta,
        }
        doc = self._run("create", vals)
        ref = self._created_ref(doc)
        for kind, to in deps:
            if (kind, to) not in inline:
                self.link(ref, to, kind)
        return ref

    def _created_ref(self, doc: Any) -> str:
        if isinstance(doc, list):
            doc = doc[0] if doc else None
        if not isinstance(doc, dict):
            raise TrackerError("tracker.create printed no entry")
        spec = self.ad.get("created_ref", "ref")
        ref = _field(doc, spec)
        if not ref:
            raise TrackerError("tracker.create printed no ref")
        return str(ref)

    def link(self, ref: str, to: str, kind: str = "blocks") -> None:
        self._run("link", {"ref": ref, "to": to, "kind": kind, "comment": f"{kind} {to}"}, kind)

    def defer_entry(self, ref: str, reason: str) -> None:
        self._run("defer", {"ref": ref, "reason": reason})

    def close_entry(self, ref: str, reason: str, as_actor: str | None = None) -> None:
        """Close an entry acting as ``as_actor`` (the claim holder). Only ``reconcile`` calls it."""
        self._run("close", {"ref": ref, "reason": reason, "actor": as_actor or self.actor})

    def reopen_entry(self, ref: str, reason: str, as_actor: str | None = None) -> None:
        """Reopen an entry acting as ``as_actor``. Only ``reconcile`` calls it."""
        self._run("reopen", {"ref": ref, "reason": reason, "actor": as_actor or self.actor})

    # -- claim ----------------------------------------------------------------------

    def claim(self, ref: str) -> dict[str, Any]:
        """Take an entry: ``{claimed, holder, by}``. The tracker's atomic claim when it has
        one; else a commit of our own pushed create-only to refs/heads/bh/<item> on origin
        (git lets exactly one claimant win); with no origin, one clone and the harness lock."""
        item = item_id(self.ad, ref)
        if self.caps["atomic_claim"] and "claim" in self.ad["commands"]:
            try:
                self._run("claim", {"ref": ref})
            except TrackerError as e:
                if isinstance(e, TrackerTimeout):
                    raise
                holder = self.show(ref).get("assignee")
                if holder and holder != self.actor:
                    self.facts.append({"kind": "claimed-elsewhere", "ref": ref, "holder": holder})
                    return {"claimed": False, "holder": holder, "by": "tracker"}
                raise
            return {"claimed": True, "holder": self.actor, "by": "tracker"}
        r = git_claim(self.cfg, item, ref, self.actor, self.timeout)
        if not r["claimed"]:
            self.facts.append(
                {"kind": "claimed-elsewhere", "ref": ref, "holder": r.get("holder"), "by": "git"}
            )
        return r

    def claimed_ids(self) -> dict[str, str]:
        """Item ids with a claim ref on the remote (holder by id); empty without a remote."""
        try:
            return {i: str(c.get("actor")) for i, c in claim_refs(self.cfg, self.timeout).items()}
        except TrackerError:
            return {}


# ---------------------------------------------------------------- the git claim (M7)


def _gitx(top: Path, args: list[str], timeout: float, env: dict[str, str] | None = None) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(top), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise TrackerTimeout(f"git {args[0]} timed out after {timeout}s") from None
    if p.returncode != 0:
        raise TrackerError(
            f"git {' '.join(args[:2])}: {p.stderr.strip()[-300:]}", p.returncode, p.stderr
        )
    return p.stdout.strip()


def _remote_of(top: Path) -> str | None:
    return "origin" if _git_ok(top, "remote", "get-url", "origin") else None


def claim_message(item: str, ref: str, actor: str) -> str:
    return f"{CLAIM_PREFIX} {item}\n\nref: {ref}\nactor: {actor}\n"


def parse_claim(message: str) -> dict[str, str] | None:
    m = re.match(rf"{CLAIM_PREFIX} (\S+)\n\nref: (.*)\nactor: (.*)\n?", message)
    return {"item": m.group(1), "ref": m.group(2), "actor": m.group(3)} if m else None


def _claim_at(top: Path, remote: str, sha: str, ref: str, timeout: float) -> dict[str, str]:
    """The claim a remote ref holds: fetch it, read the newest claim commit under it."""
    _gitx(top, ["fetch", "-q", remote, ref], timeout)
    msg = _gitx(
        top, ["log", "-1", f"--grep=^{CLAIM_PREFIX} ", "--format=%B", "FETCH_HEAD"], timeout
    )
    c = parse_claim(msg + "\n") or {}
    return {"sha": sha, **c}


def claim_refs(cfg: Config, timeout: float = 60) -> dict[str, dict[str, str]]:
    """Every claim ref on the remote: item -> {sha, ref, actor}. One ls-remote, one fetch each."""
    top = git_top(cfg.dir)
    remote = _remote_of(top) if top else None
    if top is None or remote is None:
        return {}
    out = {}
    for line in _gitx(top, ["ls-remote", remote, "refs/heads/bh/*"], timeout).splitlines():
        sha, _, name = line.partition("\t")
        item = name.removeprefix("refs/heads/bh/")
        out[item] = _claim_at(top, remote, sha, name, timeout)
    return out


def _claim_base(top: Path, remote: str) -> str:
    for cand in (f"refs/remotes/{remote}/HEAD", f"{remote}/main", f"{remote}/master", "HEAD"):
        if _git_ok(top, "rev-parse", "--verify", "-q", cand + "^{commit}"):
            return cand
    return "HEAD"


def git_claim(cfg: Config, item: str, ref: str, actor: str, timeout: float = 60) -> dict[str, Any]:
    """Claim ``item`` for ``actor`` with the create-only ref update. The claim commit is a
    child of the remote's main whose message names item, ref and actor, so two claimants never
    push the same sha and the holder is read from the message; a repeat by the holder is a
    no-op. A rejection is claimed-elsewhere."""
    top = git_top(cfg.dir)
    remote = _remote_of(top) if top else None
    if top is None or remote is None:
        with harness_lock(cfg):  # one clone: the lock and the item's place in the plan
            return {"claimed": True, "holder": actor, "by": "local"}
    name = f"refs/heads/bh/{item}"

    def holder() -> dict[str, str] | None:
        got = _gitx(top, ["ls-remote", remote, name], timeout)
        return _claim_at(top, remote, got.split()[0], name, timeout) if got else None

    held = holder()
    if held is not None:
        return {"claimed": held.get("actor") == actor, "holder": held.get("actor"), "by": "git"}
    base = _claim_base(top, remote)
    ident = {
        **os.environ,
        "GIT_AUTHOR_NAME": "brick-harness",
        "GIT_AUTHOR_EMAIL": "brick-harness@invalid",
        "GIT_COMMITTER_NAME": "brick-harness",
        "GIT_COMMITTER_EMAIL": "brick-harness@invalid",
    }
    commit = _gitx(
        top,
        ["commit-tree", f"{base}^{{tree}}", "-p", base, "-m", claim_message(item, ref, actor)],
        timeout,
        ident,
    )
    try:
        _gitx(
            top, ["push", "-q", f"--force-with-lease={name}:", remote, f"{commit}:{name}"], timeout
        )
    except TrackerTimeout:
        raise
    except TrackerError:
        held = holder()
        if held is None:
            raise
        return {"claimed": held.get("actor") == actor, "holder": held.get("actor"), "by": "git"}
    return {"claimed": True, "holder": actor, "by": "git", "sha": commit}


def release_claims(
    cfg: Config,
    actor: str,
    plan_ids: set[str],
    keep: set[str],
    timeout: float,
) -> list[dict[str, str]]:
    """Delete, with a lease on the observed sha, our own claim refs whose item is no longer in
    the plan and is not in ``keep`` (entries about to be adopted). Never another actor's ref
    and never a ref that is not a claim commit."""
    top = git_top(cfg.dir)
    remote = _remote_of(top) if top else None
    released = []
    if top is None or remote is None:
        return released
    for item, c in sorted(claim_refs(cfg, timeout).items()):
        if item in plan_ids or item in keep or c.get("actor") != actor or "ref" not in c:
            continue
        name = f"refs/heads/bh/{item}"
        try:
            _gitx(
                top,
                ["push", "-q", f"--force-with-lease={name}:{c['sha']}", remote, f":{name}"],
                timeout,
            )
        except TrackerError:
            continue  # already gone or moved: nothing of ours to release
        released.append({"item": item, "ref": c["ref"]})
    return released


# ---------------------------------------------------------------- the files adapter (bh-work)


def _work_path(d: Path, ref: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", ref):
        raise HarnessError(f"no entry {ref!r}")
    return d / f"{ref}.json"


def work_read(d: Path, ref: str) -> dict[str, Any]:
    p = _work_path(d, ref)
    if not p.is_file():
        raise HarnessError(f"no entry {ref}")
    doc: dict[str, Any] = loads(p.read_text())
    return doc


def work_write(d: Path, e: dict[str, Any]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    p = _work_path(d, e["ref"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, indent=2, sort_keys=True) + "\n")
    tmp.replace(p)


def work_view(e: dict[str, Any]) -> dict[str, Any]:
    """An entry as the interface prints it: blockers are the links of kind blocks."""
    out = {k: e.get(k) for k in ("ref", "title", "body", "state", "type", "assignee", "parent")}
    out["deps"] = [lk["to"] for lk in e.get("links", []) if lk["kind"] == "blocks"]
    out["labels"] = e.get("labels", [])
    out["metadata"] = e.get("metadata", {})
    return out


def work_create(
    d: Path,
    title: str,
    body: str = "",
    type_: str = "item",
    parent: str | None = None,
    deps: list[str] | None = None,
    labels: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A new entry; its ref is derived from its content, so the same call twice is one entry."""
    meta = metadata or {}
    ref = (
        "w-"
        + hashlib.sha256(
            json.dumps([title, type_, parent, meta.get("bh_key")]).encode()
        ).hexdigest()[:10]
    )
    with contextlib.suppress(HarnessError):
        return work_read(d, ref)
    links = []
    for x in deps or []:
        kind, _, to = x.rpartition(":")
        links.append({"kind": kind or "blocks", "to": to})
    e = {
        "ref": ref,
        "title": title,
        "body": body,
        "state": "open",
        "type": type_,
        "assignee": None,
        "parent": parent,
        "links": links,
        "labels": labels or [],
        "metadata": meta,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
    }
    work_write(d, e)
    return e


def work_list(
    d: Path,
    limit: int,
    state: str = "live",
    parent: str | None = None,
    type_: str | None = None,
    key: str | None = None,
) -> list[dict[str, Any]]:
    want = {
        "open": {"open"},
        "live": {"open", "in_progress", "deferred"},
        "closed": {"closed"},
        "all": set(STATES),
    }.get(state)
    if want is None:
        raise HarnessError(f"unknown state {state!r}")
    rows = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        e = loads(p.read_text())
        if (
            e["state"] in want
            and (parent is None or e.get("parent") == parent)
            and (type_ is None or e.get("type") == type_)
            and (key is None or e.get("metadata", {}).get("bh_key") == key)
        ):
            rows.append(e)
    rows.sort(key=lambda e: (e.get("created_at", ""), e["ref"]))
    return rows[:limit]


# ---------------------------------------------------------------- admission (M9)


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


def _plan_items(cfg: Config) -> list[dict[str, Any]]:
    p = cfg.file("bricks")
    if p is None or not p.exists():
        return []
    items: list[dict[str, Any]] = load_json(p, "bricks")["bricks"]
    return items


def admit(cfg: Config, write: bool = False, tr: Tracker | None = None) -> dict[str, Any]:
    """Take entries from the tracker into the plan, at most the room the horizon leaves.

    room = horizon.items minus the items not met (blocked ones count: rolling wave, Kanban WIP).
    ready(limit=room, type=item, parent=goal) gives the leaves in admission_order; entries we
    claimed earlier but did not write (a crash between claim and write) are adopted first.
    Each entry is claimed before it is written to bricks.json with an id derived from its ref,
    so a re-admission is a no-op. Without ``write`` nothing is claimed or written. Facts only:
    not_admitted, stalled (with the blocking gap ids), claimed_elsewhere, claim_held, released,
    unreachable and pin-mismatch."""
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
        "released": [],
        "unreachable": None,
        "facts": [],
        "dry_run": not write,
    }
    try:
        tr = tr or Tracker(cfg)
    except HarnessError as e:
        out["unreachable"] = str(e)
        return out
    out["tracker"] = tr.name
    out["facts"] = tr.facts
    items = _plan_items(cfg)
    taken_ids = {b["id"] for b in items}
    taken_refs = {r for b in items for r in b.get("refs", [])}
    goal = (cfg.data.get("tracker") or {}).get("goal")
    try:
        live = tr.list(state="live", type="item")["entries"]
        held = [
            e
            for e in live
            if e.get("assignee") and e["state"] == "in_progress" and e["ref"] not in taken_refs
        ]
        mine = [e for e in held if e["assignee"] == tr.actor]
        others = [e for e in held if e["assignee"] != tr.actor]
        cap = cfg.limit("decision_items")
        rel = tr.ad.get("release")
        out["claim_held"] = [
            {
                "ref": e["ref"],
                "holder": e["assignee"],
                **({"release": render(rel, {"ref": e["ref"]})} if rel else {}),
            }
            for e in others[:cap]
        ]
        ready = (
            tr.ready(limit=cfg.limit("tracker_read"), parent=goal, type="item")
            if room
            else {"entries": [], "more": False}
        )
        orphans = _git_orphans(cfg, tr, taken_ids)
    except TrackerError as e:
        out["unreachable"] = str(e)
        return out
    seen: set[str] = set()
    fresh = []
    for e in [*mine, *orphans, *admission_order(cfg, ready["entries"], st, tr.ad)]:
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
        out["stalled"] = {
            "horizon": horizon,
            "blocked": dict(
                list({b["id"]: b["blocked_by"] for b in not_met if b["blocked_by"]}.items())[
                    : cfg.limit("decision_items")
                ]
            ),
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
        try:
            keep = {item_id(tr.ad, e["ref"]) for e in [*mine, *orphans]}
            out["released"] = release_claims(
                cfg,
                tr.actor,
                taken_ids | {t["id"] for t in taken},
                keep,
                tr.timeout,
            )
        except TrackerError as err:
            out["facts"].append({"kind": "tracker-unreachable", "note": str(err)[:200]})
    out["facts"] = tr.facts
    return out


def _git_orphans(cfg: Config, tr: Tracker, taken_ids: set[str]) -> list[dict[str, Any]]:
    """Open entries whose claim ref on the remote is ours and whose item is not in the plan."""
    if tr.caps["atomic_claim"]:
        return []
    out = []
    for item, c in sorted(claim_refs(cfg, tr.timeout).items()):
        if item in taken_ids or c.get("actor") != tr.actor or not c.get("ref"):
            continue
        try:
            e = tr.show(c["ref"])
        except TrackerError:
            continue
        if e["state"] == "open":
            out.append(e)
    return out


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
    and targets digest as the reason, acting as its claim holder; an entry closed while its item
    is not met at HEAD is reopened. Only entries named by items in the plan are touched;
    nothing is deleted; writes only on a mismatch, so a repeat is a no-op; every mismatch is a
    fact. Without ``write`` it only lists them."""
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
        tr = tr or Tracker(cfg)
    except HarnessError as e:
        out["facts"].append({"kind": "tracker-unreachable", "note": str(e)[:200]})
        return out
    out["tracker"] = tr.name
    st = bhcore.state(cfg)
    bricks, targets, _ = bhcore._load_plan(cfg, [])
    by_id = {b["id"]: b for b in bricks}
    out["checked"] = sum(len(b.get("refs", [])) for b in bricks)
    found, facts = mismatches(cfg, tr, st, bricks)
    out["facts"] = [*tr.facts, *facts]
    head = (st.get("head") or "")[:12]
    for m in found:
        out["mismatches"].append({k: m[k] for k in ("kind", "item", "ref")})
        if not write:
            continue
        e = m["entry"]
        who = e.get("assignee") or tr.actor
        try:
            if m["kind"] == "tracker-open-met":
                dg = bhcore.target_digest(cfg, by_id[m["item"]], targets)[:12]
                tr.close_entry(m["ref"], f"measured met at {head}, targets {dg}", who)
                out["closed"].append(m["ref"])
            else:
                tr.reopen_entry(m["ref"], f"not met at {head}", who)
                out["reopened"].append(m["ref"])
        except TrackerError as err:
            out["facts"].append(
                {"kind": "tracker-write-failed", "ref": m["ref"], "note": str(err)[:200]}
            )
    return out


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


# ---------------------------------------------------------------- target sources through show


def show_resolver(cfg: Config) -> Callable[[str], dict[str, Any]] | None:
    """tracker.show with a per-run cache for bh-gaps (a target source '<ref>: "<quote>"');
    None when the plan names no tracker ref in a target source."""
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


# ---------------------------------------------------------------- filing findings (M10)


def finding_key(g: dict[str, Any]) -> str:
    """The key a filed finding carries in the tracker (metadata bh_key)."""
    return bhcore.digest([g.get("rule"), bhcore._where(g), g.get("summary")])[:16]


def _finding_body(g: dict[str, Any], key: str) -> str:
    rows = [g["summary"], ""]
    for label, v in (
        ("Where", bhcore._where(g)),
        ("Rule", g.get("rule")),
        ("Severity", g.get("severity")),
        ("Evidence", g.get("proof")),
        ("Impact", ", ".join(g.get("impact") or [])),
    ):
        if v:
            rows.append(f"{label}: {v}")
    rows += ["", f"bh-key: {key}", f"bh-id: {g['id']}"]
    return "\n".join(rows)


def _finding_title(g: dict[str, Any]) -> str:
    sev = g.get("severity")
    return (f"[{sev}] " if sev else "") + g["summary"].splitlines()[0][:120]


def file_findings(cfg: Config, write: bool = False, tr: Tracker | None = None) -> dict[str, Any]:
    """File the findings committed in gaps.json (the outbox) to the tracker: highest SG-12
    rank first, serially under the harness lock, at most limits.file_per_run. Before it
    creates, and after a timeout, it looks the key up with list; the returned ref is written
    into the finding (``filed``) before the next one. What is not filed stays ranked in
    gaps.json, with the count; a key found twice is the fact duplicate-filed."""
    out: dict[str, Any] = {
        "tracker": None,
        "filed": [],
        "unfiled": 0,
        "stopped": None,
        "duplicate_filed": [],
        "facts": [],
        "dry_run": not write,
    }
    try:
        tr = tr or Tracker(cfg)
    except HarnessError as e:
        out["stopped"] = str(e)
        return out
    out["tracker"] = tr.name
    cap = cfg.limit("file_per_run")
    with harness_lock(cfg):
        doc = bhcore._gaps_doc(cfg)
        committed = bhcore._committed_finding_ids(cfg)
        open_ = [
            g
            for g in doc["gaps"]
            if g.get("source") == "finding"
            and g.get("state", "open") == "open"
            and not g.get("filed")
        ]
        ready = [g for g in open_ if committed is None or g["id"] in committed]
        todo = sorted(ready, key=bhcore.rank_key)[:cap]
        refs_of = {b["id"]: b["refs"][0] for b in _plan_items(cfg) if b.get("refs")}
        for g in todo:
            src_ref = next((refs_of[i] for i in g.get("impact") or [] if i in refs_of), None)
            key = finding_key(g)
            if not write:
                out["filed"].append({"id": g["id"], "key": key, "ref": None})
                continue
            ref, adopted = None, False
            try:
                found = tr.list(state="all", key=key)["entries"]
                if len(found) > 1:
                    out["duplicate_filed"].append({"key": key, "refs": [e["ref"] for e in found]})
                if found:
                    ref, adopted = found[0]["ref"], True
                else:
                    deps = [("discovered-from", src_ref)] if src_ref else []
                    ref = tr.create(
                        _finding_title(g),
                        _finding_body(g, key),
                        "item",
                        None,
                        deps,
                        [g["severity"]] if g.get("severity") else [],
                        {"bh_key": key},
                    )
            except TrackerTimeout as e:
                out["stopped"] = f"{g['id']}: {e}"
                with contextlib.suppress(TrackerError):  # the effect is unknown: look it up by key
                    found = tr.list(state="all", key=key)["entries"]
                    if found:
                        ref, adopted, out["stopped"] = found[0]["ref"], True, None
            except TrackerError as e:
                out["stopped"] = f"{g['id']}: {e}"
            if ref is None:
                break
            g["filed"] = ref
            out["written"] = bhcore._write_gaps_doc(cfg, doc)
            out["filed"].append({"id": g["id"], "key": key, "ref": ref, "adopted": adopted})
        out["unfiled"] = len(open_) - sum(1 for f in out["filed"] if f["ref"])
        out["not_committed"] = len(open_) - len(ready)
    out["facts"] = tr.facts
    return out
