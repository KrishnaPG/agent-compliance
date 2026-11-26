"""The review judges against the builder's rules (QBC-36, §0 G3): a design-affecting item gets one
review job whose input is its packet's rule lines, a mechanical item none; a critical or major
finding requests changes for one more builder round (Google engineering practices, code review),
never more, and then keeps the build out of main with its rework planned as a defect item under it
(QBC-91, QBC-118); a defect packet carries rule NO-12 and its review
judges it (ISTQB root cause analysis)."""

import json
import tomllib

import bhcore
import bhmetrics
import bhorch
import bhpacket
import bhrules
from bhcore import Config
from test_bhorch import fake, orch, run  # noqa: F401, F811  (fake is a fixture)
from test_review_step import STRICT, spec_for  # noqa: F401
from test_toy import JSON_WRITER, commit_all, git
from test_work_tracking import cfg_edit

RULES = ["ID-15", "RL-08"]
RULE_TAGS = {
    k: v.get("applies", [])
    for k, v in tomllib.loads((bhcore.PLUGIN_ROOT / "catalog" / "rules.toml").read_text())["house"].items()
}


def review_input(call):
    path = call["stdin"].split("Input file (read it first; it names every other path): ")[1].split()[0]
    return json.loads(open(path).read())


def plan(toy, **extra):
    """The toy, on the plugin's own rules file, with rules on json-writer, plus ``extra`` items."""
    c = toy / ".brick-harness" / "config.json"
    data = json.loads(c.read_text())
    data.get("standards", {}).pop("catalog", None)
    c.write_text(json.dumps(data, indent=2) + "\n")
    p = toy / ".brick-harness" / "bricks.json"
    doc = json.loads(p.read_text())
    for b in doc["bricks"]:
        if b["id"] == "json-writer":
            b["rules"] = [{"id": r, "reason": "the documents call for it"} for r in RULES]
    doc["bricks"] += list(extra.values())
    p.write_text(json.dumps(doc, indent=2) + "\n")
    commit_all(toy, "rules")


def reviews(fk):
    return [c for c in fk.calls() if c["agent"] == "harness-reviewer"]


def test_a_design_affecting_item_gets_one_review_of_its_packet_rules(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[]], [JSON_WRITER])
    run(orch(toy).run())
    (call,) = reviews(fake)
    inp = review_input(call)
    packet = json.loads(bhpacket.packet_path(toy, "json-writer").read_text())
    assert inp["rules"] == packet["verifier"]["rules"]  # exactly the builder's lines
    assert set(RULES) <= {r["id"] for r in inp["rules"]}


def test_a_mechanical_item_gets_no_review(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[]], [JSON_WRITER])
    o = orch(toy)
    (toy / "README.md").write_text("docs only\n")
    sha = commit_all(toy, "docs")
    packet = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    facts = []
    assert run(o.review_item(packet, "ab" * 32, sha, "mechanical", facts)) == []
    assert reviews(fake) == [] and facts == []


MAJOR = {
    "summary": "json_writer re-checks the token the gateway verified -> take the verified principal as a value; verify once at the boundary",
    "rule": "ID-15",
    "severity": "S2",
    "evidence": "reproduced",
    "where": "src/json_writer.py:3",
}


def test_a_major_finding_gets_one_more_round_with_its_teaching_and_no_further(toy, fake):  # noqa: F811
    plan(toy)
    spec_for(fake, [[MAJOR]], [JSON_WRITER, JSON_WRITER + "\n# second round\n", JSON_WRITER + "\n# third\n"])
    o = orch(toy)
    res = run(o.run())
    builders = [c for c in fake.calls() if c["agent"] == "harness-builder"]
    assert "[ID-15] json_writer re-checks the token" in builders[1]["stdin"]  # json-writer's second round
    item_jobs = [j.get("job") or j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == "json-writer"]
    assert item_jobs.count("builder") == 2  # one requested-changes round, never a third
    assert item_jobs.count("review") == 2  # the build that merges is reviewed too
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["json-writer"] == "met"
    # the finding still open after the round stays on its slice and keeps the build out of main (QBC-91, QBC-118)
    items = json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"]
    (defect,) = [b for b in items if b.get("kind") == "defect"]  # its rework, one item under it (QBC-36)
    assert defect["parent"] == "json-writer" and defect["breaks"] == ["ID-15"]
    (fact,) = [f for r in res["phases"]["rounds"] for f in r["facts"] if f["kind"] == "not_admitted"]
    assert fact["item"] == "json-writer" and "[ID-15]" in fact["detail"] and fact["message"].startswith("[main-entry] ")


def test_a_defect_packet_carries_the_root_cause_rule_and_its_special_case_fix_gets_a_major_finding(toy, fake):  # noqa: F811
    item = {
        "id": "json-writer-defect-1",
        "job": "Rows with a null name crash the writer.",
        "kind": "defect",
        "parent": "json-writer",
        "found_by": "person",
        "evidence": ["#12 a null name raises TypeError"],
        "path": "src/json_writer.py",
    }
    plan(toy, defect=item)
    cfg = Config(toy / ".brick-harness" / "config.json")
    packet = bhpacket.plan_packet(cfg, item["id"])
    assert packet["kind"] == "defect" and packet["parent"] == "json-writer"
    (no12,) = [r for r in packet["verifier"]["rules"] if r["id"] == "NO-12"]  # selected by the defect tag
    assert "contract, schema, data model or owner" in no12["message"]
    assert "Evidence: #12 a null name raises TypeError" in packet["goal"]
    special = {
        "summary": "the fix adds `if name is None: return '[]'` where the crash showed -> make name required in the row contract; prevent: fix the element that allowed it",
        "rule": "NO-12",
        "severity": "S2",
        "evidence": "reproduced",
        "where": "src/json_writer.py:4",
    }
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [special]}]})
    base = git(toy, "rev-parse", "HEAD").strip()
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER + "\n# if name is None: return '[]'\n")
    sha = commit_all(toy, "special case")
    facts = []
    o = orch(toy)
    log = run(o.review_diff(packet, "cd" * 32, base, sha, "mechanical", facts))
    inp = review_input(reviews(fake)[0])
    assert {"domain": "root cause", "detail": "the item is a defect fix"} in inp["triggers"]  # reviewed at any tier
    assert "NO-12" in [r["id"] for r in inp["rules"]]
    (res,) = log["runs"][0]["results"]
    assert res["ruleId"] == "NO-12" and res["level"] == "error" and res["properties"]["severity"] == "S2"


NETWORK = JSON_WRITER.replace("import json", "import json\nimport urllib.request  # an unplanned network call", 1)


def network_build(toy):
    """json-writer's packet, then a build that adds an unplanned network call: (packet, base, sha)."""
    plan(toy)
    packet = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    base = git(toy, "rev-parse", "HEAD").strip()
    git(toy, "checkout", "-q", "-b", "build")  # the build commit sits beside main, as the builder's ref does
    (toy / "src" / "json_writer.py").write_text(NETWORK)
    sha = commit_all(toy, "unplanned network call").strip()
    git(toy, "checkout", "-q", "main")
    return packet, base, sha


def added_by_diff(toy, base, sha):
    cfg = Config(toy / ".brick-harness" / "config.json")
    ctx = bhcore.packet_context(cfg)
    diff = bhrules.diff_tags(cfg, base, sha)
    assert "network-client" in diff
    sel = bhrules.select_rules(cfg, ctx["bricks"]["json-writer"], list(ctx["bricks"].values()), diff=diff, base=base)
    return sel["added_by_diff"]


def judged(rules, packet, added):
    """The review input holds the packet's lines, then every rule the diff's facts add."""
    ids = [r["id"] for r in rules]
    return bool(added) and ids == [r["id"] for r in packet["verifier"]["rules"]] + [r for r in added if r not in ids[: len(packet["verifier"]["rules"])]]


def test_qbc_105_ii_review_judges_the_packet_rules_plus_the_diff_rules(toy, fake):  # noqa: F811
    packet, base, sha = network_build(toy)
    added = added_by_diff(toy, base, sha)
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": []}]})
    run(orch(toy).review_diff(packet, "ab" * 32, base, sha, "design-affecting", []))
    inp = review_input(reviews(fake)[0])
    assert judged(inp["rules"], packet, added)
    assert any("network-client" in RULE_TAGS[r] for r in added)  # the network rules the packet lacked
    assert not judged(packet["verifier"]["rules"], packet, added)  # negative control: no diff rules


def test_qbc_108_a_finding_whose_rule_was_not_selected_is_a_selector_miss(toy, fake):  # noqa: F811
    packet, base, sha = network_build(toy)
    net = next(r for r in added_by_diff(toy, base, sha) if "network-client" in RULE_TAGS[r])
    unplanned = {**MAJOR, "rule": net, "summary": "urlopen has no timeout -> set a timeout and a circuit breaker"}
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [unplanned, MAJOR]}]})
    o, facts = orch(toy), []
    run(o.review_diff(packet, "ab" * 32, base, sha, "design-affecting", facts))
    (miss,) = [f for f in facts if f["kind"] == "selector_miss"]
    assert miss["rule"] == net and "network-client" in miss["missing_tag"]
    assert miss["message"].startswith(f"[selector_miss] rule {net} judged a finding but was not in json-writer's packet ->")
    fix = miss["message"].split(" -> ", 1)[1]  # teach form: the entry that would have selected it
    assert "network-client" in fix and "capability table" in fix and f"{net}'s applies" in fix
    (rec,) = [j for j in o.recorded("json-writer") if j.get("job") == "review"]
    assert "selector_misses" not in rec  # one source: bh metrics counts the run result's facts
    selected = [r["id"] for r in packet["verifier"]["rules"]]
    assert o.selector_misses("json-writer", selected, [MAJOR]) == []  # negative control: a selected rule's finding


def test_qbc_108_bh_run_reports_each_miss_in_teach_form(toy, fake):  # noqa: F811
    plan(toy)
    packet = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    planned = {r["id"] for r in packet["verifier"]["rules"]}
    net = next(r for r, tags in RULE_TAGS.items() if "network-client" in tags and r not in planned)
    unplanned = {**MAJOR, "rule": net, "summary": "urlopen has no timeout -> set a timeout and a circuit breaker"}
    spec_for(fake, [[unplanned]], [NETWORK])
    cfg = str(toy / ".brick-harness" / "config.json")
    bhorch.main(["run", "--config", cfg])  # the run result is the file bh run writes
    kept = toy / ".brick-harness" / "out" / "run-result.json"
    res = json.loads(kept.read_text())
    misses = [f for r in res["phases"]["rounds"] if r["item"] == "json-writer" for f in r["facts"] if f["kind"] == "selector_miss"]
    assert misses and {m["rule"] for m in misses} == {net}
    assert bhmetrics.run_misses(kept.parent) == len(misses)  # bh metrics counts this run's misses
    clean = [{**r, "facts": [f for f in r["facts"] if f["kind"] != "selector_miss"]} for r in res["phases"]["rounds"]]
    kept.write_text(json.dumps({**res, "phases": {**res["phases"], "rounds": clean}}))
    assert bhmetrics.run_misses(kept.parent) == 0  # negative control: the same run result without its misses
    text = bhorch.summary_text(res, None)
    assert "SELECTOR MISSES" in text and f"[selector_miss] rule {net} judged a finding" in text
    assert "SELECTOR MISSES" not in bhorch.summary_text({**res, "phases": {**res["phases"], "rounds": []}}, None)  # negative control


def test_qbc_108_a_later_defect_whose_rule_was_not_selected_is_a_selector_miss(toy, fake):  # noqa: F811
    """A defect found after the review (here by a person) names the rules it breaks; when it is
    planned, each one its parent's packet lacked is a selector_miss on the parent, recorded once."""
    plan(toy)
    cfg = Config(toy / ".brick-harness" / "config.json")
    planned = {r["id"] for r in bhpacket.plan_packet(cfg, "json-writer")["verifier"]["rules"]}
    net = next(r for r, tags in RULE_TAGS.items() if "network-client" in tags and r not in planned)
    later = {"id": "json-writer-defect-2", "job": "urlopen hangs the writer.", "kind": "defect", "parent": 34, "found_by": "person",
             "evidence": ["#35 the writer hangs on a slow host"], "breaks": [net, "ID-15"], "path": "src/json_writer.py"}
    p = toy / ".brick-harness" / "bricks.json"
    doc = json.loads(p.read_text())
    doc["bricks"] = [{**b, "refs": ["34"]} if b["id"] == "json-writer" else b for b in doc["bricks"]] + [later]
    p.write_text(json.dumps(doc, indent=2) + "\n")
    commit_all(toy, "a later defect under the slice's issue")
    spec_for(fake, [[]], [JSON_WRITER])
    o, facts = orch(toy), []
    run(o.packet_flow(later["id"], facts))
    (miss,) = [f for f in facts if f["kind"] == "selector_miss"]  # ID-15 was in the packet: no miss (negative control)
    assert miss["item"] == "json-writer" and miss["rule"] == net and "network-client" in miss["missing_tag"]
    assert miss["message"].startswith(f"[selector_miss] rule {net} ") and "capability table" in miss["message"]
    again = []
    run(o.packet_flow(later["id"], again))
    assert not [f for f in again if f["kind"] == "selector_miss"]  # negative control: its packet exists, measured once
    doc["bricks"][-1] = {**later, "found_by": "reviewer"}
    p.write_text(json.dumps(doc, indent=2) + "\n")
    assert o.defect_misses(later["id"]) == []  # negative control: a reviewer's finding was measured at its review


def test_qbc_107_review_any_author(toy, fake, capsys):  # noqa: F811
    """One entry point, `bh review BASE..HEAD [--item X]`, judges any author's diff: with --item
    against the item's selection at BASE plus the diff's rules, without against the core, the
    stack's and the diff's rules. It commits nothing, so a pre-push hook leaves the branch as is."""
    # a database stack, and a packet cap of 1 so the item's selection has rules past the cap (QBC-105 iv)
    cfg_edit(toy, limits={"packet_rules": 1}, standards={"stack": ["psycopg==3.2.0"]})
    packet, base, sha = network_build(toy)
    assert len(packet["verifier"]["rules"]) > 1
    added = added_by_diff(toy, base, sha)
    net = next(r for r in added if "network-client" in RULE_TAGS[r])
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [MAJOR, {**MAJOR, "rule": net}]}]})
    git(toy, "checkout", "-q", "build")  # a human's push: the diff is checked out
    gaps = toy / ".brick-harness" / "gaps.json"
    before = gaps.read_text() if gaps.exists() else None
    cfg = str(toy / ".brick-harness" / "config.json")
    assert bhorch.main(["review", f"{base}..HEAD", "--item", "json-writer", "--config", cfg]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["command"] == "review"
    with_item = review_input(reviews(fake)[-1])["rules"]
    assert judged(with_item, packet, added) and {"ID-15", "RL-08"} <= {r["id"] for r in with_item}
    assert git(toy, "rev-parse", "HEAD").strip() == sha and (gaps.read_text() if gaps.exists() else None) == before
    res = run(orch(toy).phase_review(f"{base}..HEAD", "json-writer"))
    (miss,) = [m for m in res["facts"] if m["kind"] == "selector_miss"]  # planned at BASE, missed
    assert miss["rule"] == net and "network-client" in miss["missing_tag"]  # named though HEAD holds the import
    res = run(orch(toy).phase_review(f"{base}..HEAD", None))
    project = [r["id"] for r in bhrules.project_rules(Config(cfg))]
    assert res["reviewed"] and set(project) <= set(res["rules"])
    stack = {r for r, tags in RULE_TAGS.items() if "database" in tags and not {"always", "network-client"} & set(tags)}
    assert stack & set(res["rules"]) and net in res["rules"]  # without --item: core + (a) the stack + (c) the diff
    assert res["findings"][0].startswith("[ID-15] json_writer re-checks the token")
    assert not {"ID-15", "RL-08"} <= set(res["rules"])  # negative control: the item's own picks need --item


def test_a_red_measure_on_merged_head_becomes_a_defect_item_and_a_minor_finding_a_known_issue(toy, monkeypatch):
    import bhcore
    import bhreview

    plan(toy)
    o = orch(toy)
    packet = bhpacket.plan_packet(Config(toy / ".brick-harness" / "config.json"), "json-writer")
    sha = git(toy, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(bhcore, "merge_refs", lambda *a: ([], []))

    async def red(pairs):
        return [{"item": i, "ref": r, "status": "unmet", "errors": ["[red] test_rows failed"]} for i, r in pairs]

    monkeypatch.setattr(o, "measure_all", red)
    facts = []
    assert run(o.merge_item(toy, packet, sha, facts)) == "met"
    items = json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"]
    (d,) = [b for b in items if b.get("kind") == "defect"]
    assert d["found_by"] == "measurer" and d["parent"] == "json-writer" and d["evidence"] == ["[red] test_rows failed"]
    assert "breaks" not in d  # a red check cites no house rule: none is invented
    minor = {"summary": "a long name -> rename it", "rule": "ID-15", "severity": "S3", "where": "src/json_writer.py"}
    o.settle_findings(packet, bhreview.sarif([minor], "json-writer", "ab" * 32, 300), sha, facts)
    assert [f["kind"] for f in facts if f["kind"] == "known_issue"] == ["known_issue"]


def test_a_defect_intake_issue_is_admitted_as_a_defect_item_under_its_slice(toy, tmp_path):
    from test_tracker import admit_setup, cli

    s, goal, (slice_ref,) = admit_setup(toy, tmp_path, n=1, horizon=10)
    ad = json.loads(s.adapter.read_text())
    ad["types"]["defect"] = "bug"  # the tracker's own defect type (GitHub Bug, beads bug)
    ad["commands"]["ready"] += " --type {type}"
    s.adapter.write_text(json.dumps(ad))
    bug = s.add("a null name crashes the writer", type="bug", parent=slice_ref)
    out = cli("bh-admit", toy, "--write")[1]
    assert "defect_intake_unreachable" not in out, out
    items = json.loads((toy / ".brick-harness" / "bricks.json").read_text())["bricks"]
    (d,) = [b for b in items if b.get("refs") == [bug]]
    assert d["kind"] == "defect" and d["parent"] == slice_ref and d["found_by"] == "person"
    assert all(b["kind"] == "change" for b in items if b.get("refs") and b["refs"] != [bug])


def test_qbc_108_an_intake_defect_names_its_rule_in_the_form_and_its_miss_is_recorded(toy, tmp_path):
    """A person's defect (the intake form's optional Rule field) is a later defect too: intake
    copies the field into ``breaks``, and a rule its slice's packet lacked is a selector_miss."""
    from test_tracker import admit_setup, cli

    plan(toy)  # the plugin's own rules file
    s, goal, (slice_ref,) = admit_setup(toy, tmp_path, n=1, horizon=10)
    ad = json.loads(s.adapter.read_text())
    ad["types"]["defect"] = "bug"
    ad["commands"]["ready"] += " --type {type}"
    s.adapter.write_text(json.dumps(ad))
    p = toy / ".brick-harness" / "bricks.json"  # the slice's plan item names its tracker issue
    doc = json.loads(p.read_text())
    doc["bricks"] = [{**b, "refs": [slice_ref]} if b["id"] == "json-writer" else b for b in doc["bricks"]]
    p.write_text(json.dumps(doc, indent=2) + "\n")
    cfg = Config(toy / ".brick-harness" / "config.json")
    net = next(r for r, tags in RULE_TAGS.items() if "network-client" in tags and r not in {x["id"] for x in bhpacket.item_rules(cfg, "json-writer")})
    form = "### Parent\n\n#1\n\n### Rule\n\n{r}\n\n### Severity\n\nMajor\n"
    named = s.add("the writer hangs on a slow host", type="bug", parent=slice_ref, body=form.format(r=f"{net}, XX-999"))
    none = s.add("a typo in a message", type="bug", parent=slice_ref, body=form.format(r="None: a wording slip"))
    bare = s.add("a null name crashes the writer", type="bug", parent=slice_ref)  # no Rule field
    cli("bh-admit", toy, "--write")
    items = {b["refs"][0]: b for b in json.loads(p.read_text())["bricks"] if b.get("refs")}
    parent = items[slice_ref]["id"]
    assert items[named]["breaks"] == [net]  # an id the catalog lacks (XX-999) is no rule
    assert "breaks" not in items[none] and "breaks" not in items[bare]  # "None: <why>" and no field name none
    o = orch(toy)
    (miss,) = o.defect_misses(items[named]["id"])
    assert miss["item"] == parent and miss["rule"] == net and miss["message"].startswith(f"[selector_miss] rule {net} ")
    assert o.defect_misses(items[bare]["id"]) == [] and o.defect_misses(items[none]["id"]) == []  # negative controls


def test_qbc_36_requested_changes_follow_limits_review_rounds(toy, fake):  # noqa: F811
    """QBC-36: at most ``limits.review_rounds`` requested-change rounds per packet; the default 1 is
    the negative control in test_a_major_finding_gets_one_more_round_with_its_teaching_and_no_further."""
    cfg_edit(toy, limits={"review_rounds": 2})
    plan(toy)
    spec_for(fake, [[MAJOR]], [JSON_WRITER + f"\n# round {n}\n" for n in range(4)])
    res = run(orch(toy).run())
    item_jobs = [j.get("job") or j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == "json-writer"]
    assert item_jobs.count("builder") == 3  # two requested-change rounds, never a third
