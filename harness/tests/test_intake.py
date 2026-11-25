"""Intake (QBC-87 to QBC-90, R8/G4): issue forms, the parent check and the Known issues cap, on recorded GitHub answers."""

import json
import subprocess
import sys
from pathlib import Path

import bhintake
import yaml
from bhcore import Config
from bhtracker import Tracker
from recorded_github import calls, flow, replay

FORMS = Path(bhintake.FORMS_DIR)


def run_check(schema, *files):
    return subprocess.run([sys.executable, "-m", "check_jsonschema", "--builtin-schema", schema, *map(str, files)], capture_output=True, text=True)


def test_forms_validate_and_require_parent_goal_acceptance():
    forms = [FORMS / f"{n}.yml" for n in ("decision", "slice", "defect")]
    r = run_check("vendor.github-issue-forms", *forms)
    assert r.returncode == 0, r.stdout + r.stderr
    c = run_check("vendor.github-issue-config", FORMS / "config.yml")
    assert c.returncode == 0, c.stdout + c.stderr
    assert yaml.safe_load((FORMS / "config.yml").read_text())["blank_issues_enabled"] is False
    need = {"decision": {"goal", "acceptance"}, "slice": {"parent", "goal", "acceptance"}, "defect": {"parent", "acceptance"}}
    for n, ids in need.items():
        body = yaml.safe_load((FORMS / f"{n}.yml").read_text())["body"]
        required = {f["id"] for f in body if f.get("validations", {}).get("required")}
        assert ids <= required, (n, required)


def test_a_form_without_a_required_field_fails_the_schema(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("name: x\ndescription: y\nbody:\n  - type: input\n    attributes: {}\n")
    assert run_check("vendor.github-issue-forms", bad).returncode != 0


def test_forms_are_written_only_when_approved(tmp_path):
    ask = bhintake.install_forms(tmp_path, False)
    assert ask["written"] == [] and "Ask the owner" in ask["ask"] and not (tmp_path / ".github").exists()
    (tmp_path / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    (tmp_path / ".github" / "ISSUE_TEMPLATE" / "defect.yml").write_text("mine")
    done = bhintake.install_forms(tmp_path, True)
    assert done["skipped"] == ["defect.yml"] and "slice.yml" in done["written"]
    assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "defect.yml").read_text() == "mine"


def cfg_for(tmp_path, **tracker):
    d = tmp_path / "proj"
    (d / ".brick-harness").mkdir(parents=True)
    conf = {"tracker": {"adapter": "github", "repo": "o/r", **tracker}}
    (d / ".brick-harness" / "config.json").write_text(json.dumps(conf))
    return Config(str(d / ".brick-harness" / "config.json"))


Q = "?per_page=100&state=open"
ISSUES = [
    {"id": 901, "number": 5, "labels": [], "body": "no parent here"},
    {"id": 902, "number": 6, "labels": [{"name": "slice"}], "body": "### Parent\n\n#3\n"},
    {"id": 903, "number": 7, "labels": [], "body": "x", "parent_issue_url": "https://api.github.com/repos/o/r/issues/3"},
]


def test_parentless_issue_is_taught_once_and_a_form_parent_is_linked(tmp_path, monkeypatch):
    msg = json.dumps({"body": f"{bhintake.MARKER}\n{bhintake.NO_PARENT}"}, separators=(",", ":"))
    msg = msg.replace("<", "\\u003c").replace(">", "\\u003e")  # gh's Go encoder escapes HTML characters
    first = [
        flow("GET", "/issues" + Q, ISSUES),
        flow("POST", "/issues/3/sub_issues", {}, '{"sub_issue_id":902}'),
        flow("GET", "/issues/5/comments?per_page=100", []),
        flow("POST", "/issues/5/comments", {}, msg),
    ]
    again = [
        flow("GET", "/issues" + Q, [ISSUES[0]]),
        flow("GET", "/issues/5/comments?per_page=100", [{"body": f"{bhintake.MARKER}\n{bhintake.NO_PARENT}"}]),
    ]
    ctx, stop = replay(tmp_path, monkeypatch, first + again)
    try:
        tr = Tracker(cfg_for(tmp_path))
        one = bhintake.check_parents(tr)
        assert one == {"linked": [{"number": 6, "parent": 3}], "taught": [5], "already": [], "failed": []}
        two = bhintake.check_parents(tr)
        assert two["taught"] == [] and two["already"] == [5]  # told once: the comment is the record
    finally:
        stop()
    assert [c[0] for c in calls(ctx)].count("unmatched") == 0, calls(ctx)
    assert bhintake.NO_PARENT.startswith("No parent decision. Every issue sits under a decision's tracking issue")


def known_flows(lines):
    body = "".join(f"- [ ] line {i} (#4)\n" for i in range(lines))
    return body, [flow("GET", "/issues/9", {"body": body})]


def test_known_issues_cap_refuses_the_101st_line_and_the_cap_is_policy(tmp_path, monkeypatch):
    body99, f99 = known_flows(99)
    body100, f100 = known_flows(100)
    add = flow("PATCH", "/issues/9", {}, json.dumps({"body": body99 + "- [ ] new (#4)\n"}, separators=(",", ":")))
    ctx, stop = replay(tmp_path, monkeypatch, f99 + [add] + f100 + f100 + f99)
    try:
        cfg = cfg_for(tmp_path, known_issues="9")
        tr = Tracker(cfg)
        assert bhintake.known_add(cfg, tr, "new (#4)")["count"] == 100  # the 100th line is allowed
        refused = bhintake.known_add(cfg, tr, "one too many (#4)")  # the 101st is refused
        assert not refused["added"] and "fix a line and remove it" in refused["message"] and refused["limit"] == 100
        assert not bhintake.known_add(cfg, tr, "no parent named")["added"]  # at the cap first
        # policy override: a project cap of 99 refuses what the default 100 allows
        d = tmp_path / "proj" / ".brick-harness" / "config.json"
        conf = json.loads(d.read_text())
        conf["limits"] = {"known_issues": 99}
        d.write_text(json.dumps(conf))
        low = Config(str(d))
        assert bhintake.known_add(low, Tracker(low), "x (#4)")["limit"] == 99
    finally:
        stop()
    assert "unmatched" not in [c[0] for c in calls(ctx)], calls(ctx)
