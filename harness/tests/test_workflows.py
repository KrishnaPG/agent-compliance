"""Static checks of workflows/*.js: they are not executed here (that needs Claude Code)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLOWS = sorted((ROOT / "workflows").glob("*.js"))
PRELUDE = (ROOT / "lib" / "prelude.js").read_text()
PHASES = {"harness-" + n for n in ("gaps", "plan", "build", "measure", "harvest")}
NODE = shutil.which("node")


def split(p):
    text = p.read_text()
    assert text.startswith("export const meta = {"), "meta must be the first statement"
    end = text.index("\n}\n") + 2
    return text[len("export const meta = ") : end], text[end:]


def test_one_workflow_per_phase_plus_harness():
    assert {p.stem for p in FLOWS} == PHASES | {"harness-run"}


@pytest.mark.parametrize("p", FLOWS, ids=[p.stem for p in FLOWS])
def test_static_rules(p):
    meta, body = split(p)
    assert not re.search(r"`|\.\.\.|\$\{", meta), "meta must be a pure literal"
    assert PRELUDE in body, "prelude differs from lib/prelude.js"
    for bad in (
        r"Date\.now",
        r"Math\.random",
        r"new Date\(\s*\)",
        r"\brequire\(",
        r"^\s*import\b",
        r"\bprocess\.",
        r"\bfs\.",
    ):
        assert not re.search(bad, body, re.M), bad
    assert "model: '" not in body, "model names come from config"
    used = set(re.findall(r"phase\('([^']+)'\)", body)) | set(re.findall(r"phase: '([^']+)'", body))
    titles = set(re.findall(r"title: '([^']+)'", meta))
    assert used <= titles, used - titles
    if p.stem != "harness-run":
        assert "workflow(" not in body, "phase workflows must not nest (one level only)"
    assert re.search(r"^const NEED = ", body.split(PRELUDE)[0], re.M), "NEED precedes the prelude"


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("p", FLOWS, ids=[p.stem for p in FLOWS])
def test_parses_and_meta_is_literal(p):
    meta, body = split(p)
    js = (
        "const AsyncFunction = (async () => {}).constructor;\n"
        f"const meta = (new Function('return ' + {json.dumps(meta)}))();\n"
        "if (!meta.name || !meta.description) throw new Error('meta');\n"
        f"new AsyncFunction('agent','parallel','pipeline','phase','log','args','budget','workflow', {json.dumps(body)});\n"
        "console.log(meta.name);\n"
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == p.stem


def test_part_schema_carries_every_state_key_and_needs_are_known():
    import bhcore

    keys = bhcore.state(
        bhcore.Config(ROOT / "examples" / "toy" / ".brick-harness" / "config.json")
    ).keys()
    block = PRELUDE[PRELUDE.index("const PART_SCHEMA") : PRELUDE.index("const ALL_PARTS")]
    missing = [k for k in keys if not re.search(rf"\b{k}: ", block)]
    assert missing == []
    for p in FLOWS:
        need = re.search(r"^const NEED = (.*)$", p.read_text(), re.M).group(1)
        for k in re.findall(r"'([a-z_]+)'", need):
            assert k in keys, (p.stem, k)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_checksum_matches_python_under_node():
    import bhcore

    fns = PRELUDE[PRELUDE.index("function canon(") : PRELUDE.index("let state = ")]
    samples = [
        {"a": 1.0, "b": [20000.5, -0.5, 3], "é": "x\U0001f600y", "z": None, "t": True, "f": False},
        bhcore.state(bhcore.Config(ROOT / "examples" / "toy" / ".brick-harness" / "config.json")),
        [1e20, -1e16, 0.000001, "\u2028"],
    ]
    js = (
        fns + f"\nconst S = {json.dumps(samples)};\nconsole.log(JSON.stringify(S.map(checksum)));\n"
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [bhcore.checksum(x) for x in samples]


def _run_load_state(replies):
    body = "const NEED = null;\n" + PRELUDE + "\nreturn 'ok'"
    js = (
        "const AsyncFunction = (async () => {}).constructor;\n"
        f"const replies = {json.dumps(replies)}; let n = 0; const prompts = [];\n"
        "const agent = async (p) => { prompts.push(p); return replies[n++] };\n"
        f"const f = new AsyncFunction('agent', 'log', 'args', {json.dumps(body)});\n"
        "const logs = []; f(agent, m => logs.push(m), {configPath: 'c.json'}).then(r => console.log(JSON.stringify([r && r.error ? 'none' : r, n, logs.join('|'), prompts])));\n"
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _toy_good():
    import bhcore

    st = bhcore.state(bhcore.Config(ROOT / "examples" / "toy" / ".brick-harness" / "config.json"))
    return st, {"checksums": {k: bhcore.checksum(v) for k, v in st.items()}, **st}


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_prelude_unwraps_a_part_returned_in_its_part_wrapper():
    """Bug: --part prints {key: value}; sliced re-reads returned the wrapper as the value."""
    st, good = _toy_good()
    short = {**good, "counts": {k: v for k, v in list(st["counts"].items())[1:]}}
    wrapped = {**good, "counts": {"counts": st["counts"]}}
    got = _run_load_state([short, wrapped])
    assert got[:2] == ["ok", 2], got  # the re-read is accepted: unwrapped, checksum matches
    got = _run_load_state([wrapped])  # also on a first read
    assert got[:2] == ["ok", 1], got


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_prelude_rejects_a_wrapped_value_with_a_wrong_checksum():
    st, good = _toy_good()
    bad_inner = {k: v for k, v in list(st["counts"].items())[1:]}
    wrong = {**good, "counts": {"counts": bad_inner}}
    got = _run_load_state([wrong, wrong, wrong, wrong])
    assert got[:2] == ["none", 4] and "counts" in got[2], got


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_sliced_reread_prompt_names_value_and_says_the_joined_text_is_the_value():
    st, good = _toy_good()
    short = {**good, "counts": {}}
    got = _run_load_state([short, good])
    sliced = got[3][1]
    assert "--value <key>" in sliced and not re.search(r"--part(?!s)", sliced)
    assert "joined text is that key's value" in sliced


def body(name):
    return split(ROOT / "workflows" / f"{name}.js")[1].replace(PRELUDE, "")


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize(
    "seq,want,calls",
    [("g", "ok", 1), ("sg", "ok", 2), ("sssg", "ok", 4), ("ssss", "none", 4), ("m", "ok", 1)],
)
def test_prelude_rereads_a_part_that_fails_its_checksum_up_to_three_times(seq, want, calls):
    """H6: a shortened part is re-read (in slices) up to 3 times, then the workflow gives up."""
    import bhcore

    st = bhcore.state(bhcore.Config(ROOT / "examples" / "toy" / ".brick-harness" / "config.json"))
    good = {"checksums": {k: bhcore.checksum(v) for k, v in st.items()}, **st}
    short = {**good, "bricks": good["bricks"][:-1]}
    many = {**good, "extra": 1}
    replies = [{"g": good, "s": short, "m": many}[c] for c in seq]
    body = "const NEED = null;\n" + PRELUDE + "\nreturn 'ok'"
    js = (
        "const AsyncFunction = (async () => {}).constructor;\n"
        f"const replies = {json.dumps(replies)}; let n = 0;\n"
        "const agent = async () => replies[n++];\n"
        f"const f = new AsyncFunction('agent', 'log', 'args', {json.dumps(body)});\n"
        "const logs = []; f(agent, m => logs.push(m), {configPath: 'c.json'}).then(r => console.log(JSON.stringify([r && r.error ? 'none' : r, n, logs.join('|')])));\n"
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got[:2] == [want, calls]
    if want == "none":  # the failure names the part that mismatched
        assert "bricks" in got[2] and "3 re-reads" in got[2]


def test_prelude_dry_run_guards_every_write():
    assert "const DRY = !!A.dryRun" in PRELUDE
    commit = PRELUDE[
        PRELUDE.index("async function commitPlan") : PRELUDE.index("async function writeGaps")
    ]
    assert "(DRY ? ' --dry-run'" in commit
    gaps = PRELUDE[
        PRELUDE.index("async function writeGaps") : PRELUDE.index("async function runMeasurer")
    ]
    assert "(DRY ? '' : ' --write')" in gaps
    assert "DRY RUN: write no file" in PRELUDE[PRELUDE.index("const RULES") :]


@pytest.mark.parametrize(
    "name,first_write",
    [
        ("harness-build", "isolation: 'worktree'"),
        ("harness-harvest", "writeGaps("),
        ("harness-measure", "measureAll("),
    ],
)
def test_dry_run_returns_before_the_first_write(name, first_write):
    b = body(name)
    assert "if (DRY) return" in b
    assert b.index("if (DRY) return") < b.index(first_write)


@pytest.mark.parametrize("name", ["harness-gaps", "harness-plan"])
def test_writing_phases_write_only_through_guarded_helpers(name):
    b = body(name)
    assert "writeGaps(" in b and "commitPlan(" in b and "RULES" in b
    if (
        "async function trackerTool" in b
    ):  # the one deterministic helper that applies the tracker tools
        t0 = b.index("async function trackerTool")
        b = b[:t0] + b[b.index("\n}\n", t0) + 3 :]
    assert "--write" not in b and "bh-commit" not in b
    assert "ok(report)" in b and "ok(commit)" in b  # results are checked (S5, W8)


def test_harness_passes_dry_run_and_calls_renamed_phases():
    b = body("harness-run")
    assert "dryRun: DRY" in b
    assert "for (const name of ['gaps', 'plan'])" in b and "sub('harness-' + name)" in b
    for n in ("harness-build", "harness-measure", "harness-harvest"):
        assert f"sub('{n}'" in b
    assert "if (!/unknown|not found" in b  # W1: bare name only on a name-lookup error


def test_build_uses_branch_and_feedback_without_defect_analysis():
    b = body("harness-build")
    assert "l.ref" in b and "git merge --no-edit" in b
    assert "actual" in b and "required" in b and "feedback(id)" in b
    assert "bug-analysis" not in b and "useSkill" not in b  # D2: numbers only
    assert "update-ref" not in b and "bh-branch" in b and "toBuild.forEach((id, k)" in b  # S7, H4
    assert "r === state.head || r === state.plan_head" in b
    # no new commit means "measure the item at HEAD", never a failure
    assert "nochange: true, ref: 'HEAD'" in b and "refs.push({ ref: s.ref, items: [id] })" in b
    assert "nochange: true }" not in b.replace("ok: true, nochange: true", "")
    assert "isolation: 'worktree'" in b and "'branch ' + id" in b
    assert "state.commands[id]" in b and "state.head" in b  # W2, S6
    assert "d.uncommitted.length" in b  # S5: re-checked before forking builders


def test_build_measures_unmeasured_stale_conflict_and_uncommitted_items_at_head_before_builders():
    b = body("harness-build")
    assert (
        "['unmeasured', 'stale', 'conflict', 'met-uncommitted']" in b
        and "REMEASURE.indexOf(bStatus(id)) >= 0" in b
    )
    first = b.index("measureAll(preHead.map(id => ({ item: id, ref: 'HEAD' })))")
    assert first < b.index("isolation: 'worktree'") and first < b.index("pool(toBuild")
    assert b.index("if (DRY) return") < first  # a dry run only reports it
    assert "would_measure_head_first: preHead" in b
    # only what is still ready (unmet or not measurable) and not met at HEAD is built
    assert "metAtHead.indexOf(id) < 0 && stillReady.indexOf(id) >= 0" in b
    assert "no builder spawned" in b


def test_stuck_is_derived_by_the_tool_and_the_run_passes_only_what_it_attempted():
    """SG-15 M2: the run never reads every item; bh-gaps --source cycle lists every item not
    met (see test_every_item_not_met_is_stuck_in_gaps_json_with_reason_and_errors)."""
    b = body("harness-run")
    for reason in ("'build-failed'", "'no-change'", "'unmet'", "'budget'"):
        assert reason in b
    assert "state.bricks.filter(b => b.status" not in b
    assert "writeGaps([], 'cycle', Object.keys(reason).map(i => i + ':' + reason[i]))" in b
    assert "report.stuck = g.stuck || []" in b and "report.stuck_more" in b
    assert "(b.measuredHead || []).length" in b  # measuring at HEAD is progress


def test_measure_merges_from_the_scoreboard_and_remeasures_at_head():
    b = body("harness-measure")
    assert "bh-merge" in b and "git merge" not in b  # S1: deterministic merges only
    assert "fresh.unmerged" in b  # H5: from the reloaded state
    assert "m.remeasure.map(i => ({ item: i, ref: 'HEAD' }))" in b  # H1
    assert "--affected" in b  # H4: harvest refs score the items they touch
    assert "runMeasurer(p.item, p.ref, slot)" in PRELUDE  # S3, W6: one item per call, with its slot


def test_gaps_reviewer_judges_read_only_with_explicit_overlay():
    b = body("harness-gaps")
    assert "state.checklist" in b and "state.overlay" in b
    assert "Do not write its verdict record" in b and "quote" in b  # D1, D5


def test_harvest_verifies_settled_and_always_writes_gaps():
    b = body("harness-harvest")
    assert "function settledPick" in b and "state.catalogue.entries" in b
    assert "const report = await writeGaps(open, 'harvest')" in b and "ok(report)" in b


def test_default_checklist_is_small_and_generic():
    import bhcore

    ids = {a["id"] for a in bhcore.load_checklist()}
    assert ids == {"language-runtime", "build-order", "test-bench-commands"}
    assert bhcore.DEFAULT_JOBS == ["testing"]


def test_catalog_skills_are_referenced_not_copied():
    assert "catSkill('vet-oss')" in PRELUDE
    assert "catSkill('compliance-review')" in body(
        "harness-gaps"
    ) and "catSkill('vetted-decision')" in body("harness-gaps")
    skills = {p.parent.name for p in (ROOT.parent / "skills").glob("*/SKILL.md")}
    assert {"harness", "compliance-review", "vet-oss", "vetted-decision", "bug-analysis"} <= skills
    own = (ROOT.parent / "skills" / "harness" / "SKILL.md").read_text()
    for name in skills - {"harness"}:  # referenced by name, never copied
        other = (ROOT.parent / "skills" / name / "SKILL.md").read_text().split("---", 2)[2]
        assert not set(own.splitlines()) & {x for x in other.splitlines() if len(x) > 40}, name
    # RULES uses state, so it must come after the state is loaded
    assert PRELUDE.index("const RULES") > PRELUDE.index("if (!state) state = await loadState()")


def test_harness_keeps_rebuilding_unmet_items_until_max_rounds_then_reports_them():
    b = body("harness-run")
    assert "if (!merged.length && !(b.refs || []).length && !(b.measuredHead || []).length)" in b
    assert (
        "writeGaps([], 'cycle'" in b and "if (!DRY) await commitPlan('unmet items reported')" in b
    )


SMALL = {
    "decision",
    "uncommitted",
    "head",
    "plan_head",
    "branches",
    "unmerged",
    "problems",
    "merged",
}


def test_round_reloads_ask_only_for_small_parts():
    """Bug: a ~9.5 KB reload was retyped by an agent and failed its checksum in round 2."""
    for p in FLOWS:
        for lst in re.findall(r"loadState\((\[[^\]]*\])\)", split(p)[1].replace(PRELUDE, "")):
            assert set(re.findall(r"'([a-z_]+)'", lst)) <= SMALL | {"catalogue"}, (p.stem, lst)
    h = body("harness-run")
    assert "refresh(['decision'])" in h and "refresh(['decision', 'catalogue', 'merged'])" in h
    assert "state = await loadState()" in h  # the full read happens only after gaps and plan
    assert h.count("state = await loadState()") == 1
    for n in ("harness-build", "harness-measure"):
        assert "loadState(['decision'])" in body(n)


def test_harness_reloads_only_parts_it_or_its_phases_read():
    need = re.search(
        r"^const NEED = (\[.*?\])", (ROOT / "workflows" / "harness-run.js").read_text(), re.M
    )
    parts = set(re.findall(r"'([a-z_]+)'", need.group(1)))
    assert not parts & {"counts", "waves", "branches", "config_path", "root", "bricks", "commands"}
    assert "decision" in parts  # capped by limits.decision_items: the one part about the items
    for n in (
        "gaps",
        "plan",
        "build",
        "measure",
        "harvest",
    ):  # state handed to a phase must satisfy its NEED
        pn = re.search(
            r"^const NEED = (.*)$", (ROOT / "workflows" / f"harness-{n}.js").read_text(), re.M
        )
        assert set(re.findall(r"'([a-z_]+)'", pn.group(1))) <= parts, n


def test_need_lists_hold_no_part_a_workflow_does_not_read():
    needs = {
        p.stem: set(
            re.findall(
                r"'([a-z_]+)'", re.search(r"^const NEED = (.*)$", p.read_text(), re.M).group(1)
            )
        )
        for p in FLOWS
    }
    assert needs["harness-build"] == {"config", "files", "problems", "decision"}
    assert needs["harness-measure"] == {"config", "files", "problems", "decision"}
    for (
        n,
        need,
    ) in needs.items():  # SG-15 M2: no workflow loads the bricks or commands of every item
        assert not need & {"bricks", "commands", "ready", "ready_system", "head", "plan_head"}, n
    assert needs["harness-plan"] == {
        "config",
        "files",
        "problems",
        "decision",
        "learning",
        "features",
        "gaps",
    }
    assert needs["harness-harvest"] == {
        "config",
        "files",
        "problems",
        "decision",
        "catalogue",
        "merged",
    }
    for n in ("harness-build", "harness-measure"):
        assert not needs[n] & {"gaps", "checklist", "overlay", "catalogue", "waves"}
    for n, need in needs.items():  # every workflow reads what it lists
        for k in need - {"config", "files", "problems"}:
            assert re.search(rf"state\.{k}\b|\b{k}\b", body(n)) or n == "harness-run", (n, k)


def test_branch_command_flows_through_the_harness():
    assert "branchCommand" in PRELUDE and "branchCommand: A.branchCommand" in body("harness-run")
    assert "bh-branch" in (ROOT / "README.md").read_text()


BUILD_JS = r"""
const AsyncFunction = (async () => {}).constructor;
const { checksum } = new Function(PRE_FNS + '\nreturn { checksum }')();
const S = %(state)s, calls = [];
const agent = async (prompt, o) => {
  calls.push(o.label)
  if (o.schema && o.schema.required && o.schema.required.includes('checksums')) {
    const out = { checksums: {} }
    for (const p of o.schema.required.filter(k => k !== 'checksums')) { out[p] = JSON.parse(JSON.stringify(S[p])); out.checksums[p] = checksum(S[p]) }
    return out
  }
  if (o.label.startsWith('measure ')) return { ok: true, items: { [o.label.slice(8)]: { status: '%(measured)s', errors: [] } } }
  if (o.label === 'commit plan') return { committed: true }
  if (o.label.startsWith('branch ')) return { ok: true, ref: 'HEAD' }
  return { item: o.label, ref: 'a'.repeat(40), catalogue_added: [] } // a builder
}
const f = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', BODY)
f(agent, undefined, undefined, () => {}, () => {}, { configPath: 'c.json' }, {}, undefined)
  .then(r => console.log(JSON.stringify({ calls, built: r.built ? r.built.length : 0 })), e => { console.error(e); process.exit(1) })
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("status,builders", [("met", 0), ("met-uncommitted", 0), ("unmet", 1)])
def test_a_stale_item_is_measured_at_head_and_only_an_unmet_one_gets_a_builder(status, builders):
    pending = {
        "id": "x",
        "kind": "brick",
        "status": "stale",
        "ready": True,
        "depends_on": [],
        "blocked_by": [],
    }
    decision = {
        "pending": [pending],
        "last": {},
        "ready": ["x"],
        "ready_system": [],
        "unmerged": [],
        "uncommitted": [],
        "branches": {},
        "commands": {"x": {}},
        "head": "h" * 40,
        "plan_head": "h" * 40,
        "all_met": False,
    }
    s = {"config": {"concurrency": 1}, "files": {}, "problems": [], "decision": decision}
    parts = PRELUDE[PRELUDE.index("function canon(") : PRELUDE.index("let state = ")]
    js = (
        f"const PRE_FNS = {json.dumps(parts)};\nconst BODY = {json.dumps(split(ROOT / 'workflows' / 'harness-build.js')[1])};\n"
        + BUILD_JS % {"state": json.dumps(s), "measured": status}
    )
    out = subprocess.run([NODE, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout)
    assert "measure x" in r["calls"]  # measured at HEAD before any builder
    assert r["built"] == builders
    assert ("x" in r["calls"]) == bool(builders)
