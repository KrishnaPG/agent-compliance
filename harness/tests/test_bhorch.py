"""The orchestrator (lib/bhorch.py, bin/bh), driven with a fake ``claude`` on PATH.

The fake (tests/fake_bin/claude) answers each agent job from a spec file, writes and commits
what a builder would, and can fail authentication or overrun its budget. Nothing here calls a
model. What the fake cannot show (the host accepting ``--agents`` under ``--bare``, the real result JSON,
real cost) is listed in the README and proven by a paid toy run.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import bhcore
import bhorch
import pytest
from bhcore import Config
from test_toy import JSON_WRITER, commit_all, git  # the toy fixture comes from conftest.py

ROOT = Path(__file__).resolve().parent.parent
FAKE_BIN = ROOT / "tests" / "fake_bin"
BH = ROOT.parent / "bin" / "bh"

PLAN_OUT = {"added_items": [], "added_targets": 0, "added_contracts": [], "not_derivable": []}
OUTPUTS = {
    "harness-gaps-reader": {"gaps": []},
    "harness-planner": PLAN_OUT,
    "harness-harvester": {"candidates": []},
    "harness-reviewer": {"findings": []},
}
BUILD = {"json-writer": {"src/json_writer.py": JSON_WRITER}}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """Put the fake claude on PATH; ``fake.spec(**kw)`` sets its behaviour, ``fake.calls()``
    returns what it was called with."""
    spec, log = tmp_path / "spec.json", tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{FAKE_BIN}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_SPEC", str(spec))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k, v in (("NAME", "t"), ("EMAIL", "t@example.invalid")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)

    class Fake:
        def spec(self, **kw):
            spec.write_text(json.dumps({"outputs": OUTPUTS, "build_files": BUILD, **kw}))

        def calls(self):
            return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    f = Fake()
    f.spec()
    return f


def orch(repo, dry=False):
    return bhorch.Orchestrator(Config(repo / ".brick-harness" / "config.json"), dry)


def run(coro):
    return asyncio.run(coro)


def arg(call, flag):
    return call["argv"][call["argv"].index(flag) + 1]


# ---------------------------------------------------------------- auth mode


def test_auth_mode_is_chosen_from_the_key_or_a_helper_never_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert bhorch.auth_mode(tmp_path) == ("login", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert bhorch.auth_mode(tmp_path) == ("bare", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"apiKeyHelper": "get-key"}')
    assert bhorch.auth_mode(tmp_path) == ("bare", "get-key")


def test_mode_flags_bare_and_login():
    bare = bhorch.mode_flags("bare", None, "harness-harvester")
    assert bare[0] == "--bare" and "--plugin-dir" not in bare and "--setting-sources" not in bare
    assert bare[bare.index("--agent") + 1] == "harness-harvester"  # unprefixed under --bare
    login = bhorch.mode_flags("login", None, "harness-harvester")
    assert login[:2] == ["--setting-sources", ""] and "--bare" not in login
    assert {"--strict-mcp-config", "--disable-slash-commands", "--plugin-dir"} <= set(login)
    assert login[login.index("--agent") + 1] == "agent-compliance:harness-harvester"
    assert "--agents" not in login
    helper = bhorch.mode_flags("bare", "get-key")  # only that one key reaches a bare job
    assert json.loads(helper[helper.index("--settings") + 1]) == {"apiKeyHelper": "get-key"}


# ---------------------------------------------------------------- one job


def gaps_job(o):
    return run(o.phase_gaps())


def test_a_job_is_the_host_cli_with_schema_agent_tools_and_budget(toy, fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    o = orch(toy)
    gaps_job(o)
    (c,) = fake.calls()
    assert c["mode"] == "bare" and c["agent"] == "harness-gaps-reader"
    a = c["argv"]
    assert a[0] == "-p" and arg(c, "--agent") == "harness-gaps-reader"
    assert arg(c, "--output-format") == "json" and "--no-session-persistence" in a
    assert arg(c, "--permission-mode") == "dontAsk" and arg(c, "--max-budget-usd") == "2.0"
    assert (
        arg(c, "--allowedTools") == "Read,Grep,Glob,StructuredOutput"
    )  # the agent file's tools, nothing more
    assert "--bare" in a and "--plugin-dir" not in a
    defs = json.loads(arg(c, "--agents"))
    assert list(defs) == ["harness-gaps-reader"]
    d = defs["harness-gaps-reader"]
    ad = bhorch.agent_def("harness-gaps-reader")
    assert d["tools"] == ["Read", "Grep", "Glob", "StructuredOutput"]
    assert d["prompt"] == ad["prompt"] and d["prompt"].startswith("You are a job")
    assert d["description"] and d["model"] == ad["model"] and d["effort"] == ad["effort"]
    schema = json.loads(arg(c, "--json-schema"))
    assert "$ref" not in json.dumps(schema) and schema["required"] == ["gaps"]
    # the prompt is on stdin and holds a short instruction plus the path of the input file
    inp = Path(
        c["stdin"]
        .split("Input file (read it first; it names every other path): ")[1]
        .split("\n")[0]
    )
    assert inp.is_file() and len(c["stdin"]) < 600
    doc = json.loads(inp.read_text())
    assert doc["task"] == "gaps" and "documents" in doc and "review_input" in doc


def test_every_agent_file_allows_the_structured_output_tool():
    # a tools allowlist without it hides the tool: --json-schema is then silently ignored
    files = sorted(bhorch.AGENTS_DIR.glob("harness-*.md"))
    assert len(files) == 6
    for f in files:
        assert "StructuredOutput" in bhorch.agent_def(f.stem)["tools"], f.name


def test_login_mode_uses_the_prefixed_plugin_agent_and_no_agents_json(toy, fake):
    gaps_job(orch(toy))
    (c,) = fake.calls()
    assert arg(c, "--agent") == "agent-compliance:harness-gaps-reader"
    assert "--agents" not in c["argv"] and arg(c, "--plugin-dir") == str(bhorch.PLUGIN_ROOT)


def test_fake_claude_rejects_a_prefixed_agent_under_bare(toy, fake):
    p = subprocess.run(
        ["claude", "-p", "--bare", "--agent", "agent-compliance:harness-gaps-reader"],
        input="x",
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1 and "not found. Available agents" in p.stderr


def test_bare_agent_not_found_reruns_once_in_login_mode(toy, fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    fake.spec(hide_agents_bare=True)  # a host change: bare no longer takes --agents
    o = orch(toy)
    gaps_job(o)
    assert [c["mode"] for c in fake.calls()] == ["bare", "login"]
    rec = o.records[0]
    assert rec["ok"] and rec["mode"] == "login" and rec["fallback_reason"] == "agent_not_found"
    assert "not found" in rec["first_attempt_error"] and o.mode == "login" and o.fallbacks == 1


def test_judge_appends_the_result_errors_to_the_error(toy, fake):
    o = orch(toy)
    r = {
        "subtype": "error_max_budget_usd",
        "is_error": True,
        "errors": ["Reached maximum budget ($0.0001)"],
    }
    ok, err, _ = o._judge(1, "", "", r, {})
    assert not ok and "error_max_budget_usd" in err and "Reached maximum budget ($0.0001)" in err


def test_a_skipped_job_shows_zero_cost_with_the_cached_one_noted(toy, fake):
    gaps_job(orch(toy))
    o2 = orch(toy)
    gaps_job(o2)
    (row,) = o2.job_table()
    assert row["skipped"] and row["cost_usd"] == 0 and row["cached_cost_usd"] == 0.01
    r = {
        "product": {
            "sellable_at_head": [],
            "became_sellable_this_run": [],
            "current_slice": 0,
            "next": None,
            "unvalued_features": [],
        },
        "status": {"items": 0, "all_met": True, "stuck": [], "gaps": 0},
        "owner_questions": [],
        "auth": {"mode_at_start": "login", "mode_at_end": "login", "fallbacks_to_login": 0},
        "totals": {"jobs": 1, "skipped": 1, "cost_usd": 0.0, "tokens": 0},
        "jobs": [row],
        "errors": [],
    }
    text = bhorch.summary_text(r, None)
    assert "$0.0000" in text and "earlier $0.0100" in text and "$0.0100 15" not in text


def test_login_mode_flags_and_review_job_is_read_only(toy, fake):
    o = orch(toy)
    gaps_job(o)
    (c,) = fake.calls()
    assert c["mode"] == "login" and "--bare" not in c["argv"]
    assert arg(c, "--setting-sources") == "" and "--disable-slash-commands" in c["argv"]
    argv = o.argv("review", bhorch.job_schema("review"), "login")
    tools = argv[argv.index("--allowedTools") + 1]
    assert "Bash(git diff:*)" in tools and tools.split(",").count("Bash") == 0


def test_a_restart_skips_jobs_whose_result_file_exists(toy, fake):
    o1 = orch(toy)
    gaps_job(o1)
    assert len(fake.calls()) == 1 and not o1.records[0].get("skipped")
    saved = list((toy / ".brick-harness" / "out" / "jobs").glob("*.json"))
    assert any(not p.name.endswith((".input.json", ".error.json")) for p in saved)
    o2 = orch(toy)  # a new process, the same documents
    gaps_job(o2)
    assert len(fake.calls()) == 1  # not called again
    assert o2.records[0]["skipped"] is True and o2.records[0]["key"] == o1.records[0]["key"]


def test_a_changed_document_changes_the_key_and_runs_the_job_again(toy, fake):
    gaps_job(orch(toy))
    (toy / "features.md").write_text((toy / "features.md").read_text() + "\nA new line.\n")
    gaps_job(orch(toy))
    assert len(fake.calls()) == 2


def test_bare_auth_failure_reruns_once_in_login_mode_and_stays_there(toy, fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    fake.spec(auth_fail_bare=True)
    o = orch(toy)
    gaps_job(o)
    modes = [c["mode"] for c in fake.calls()]
    assert modes == ["bare", "login"]
    rec = o.records[0]
    assert rec["ok"] and rec["mode"] == "login" and rec["auth_fallback"] is True
    assert o.fallbacks == 1 and o.mode == "login"
    run(o.phase_plan())  # later jobs go straight to login mode
    assert [c["mode"] for c in fake.calls()][2:] == ["login"]


def test_budget_overrun_is_a_failed_recorded_job_and_is_not_cached(toy, fake):
    fake.spec(budget_overrun=["harness-gaps-reader"])
    o = orch(toy)
    r = gaps_job(o)
    assert "error" in r and "error_max_budget_usd" in o.records[0]["error"]
    assert o.records[0]["cost_usd"] == pytest.approx(2.01) and o.spent["cost_usd"] == pytest.approx(
        2.01
    )
    fake.spec()  # healthy now: the failed job left no result file, so it runs again
    gaps_job(orch(toy))
    assert len(fake.calls()) == 2


def test_an_output_that_fails_its_schema_is_a_failed_job(toy, fake):
    fake.spec(outputs={**OUTPUTS, "harness-gaps-reader": {"gaps": [{"kind": "nope"}]}})
    o = orch(toy)
    r = gaps_job(o)
    assert "fails its schema" in r["error"] and not o.records[0]["ok"]


def test_a_deadline_terminates_the_job(toy, fake, tmp_path):
    slow = tmp_path / "slow"
    slow.mkdir()
    (slow / "claude").write_text(
        "#!/bin/sh\nexec python3 -c 'import sys,time; sys.stdin.read(); time.sleep(60)'\n"
    )
    (slow / "claude").chmod(0o755)
    os.environ["PATH"] = f"{slow}{os.pathsep}{os.environ['PATH']}"
    cfg = toy / ".brick-harness" / "config.json"
    d = json.loads(cfg.read_text())
    d["budgets"] = {"job_timeout_s": 1}
    cfg.write_text(json.dumps(d))
    commit_all(toy, "budget")
    o = orch(toy)
    r = gaps_job(o)
    assert "deadline" in r["error"]


# ---------------------------------------------------------------- phases


def test_the_mechanical_phases_start_no_agent(toy, fake):
    """measure, merge and commit are code: no agent job starts for them."""
    git(toy, "checkout", "-qB", "bh/json-writer", "main")
    (toy / "src" / "json_writer.py").write_text(JSON_WRITER)
    ref = commit_all(toy, "build json-writer", "src")
    git(toy, "checkout", "-q", "main")
    o = orch(toy)
    r = run(o.phase_measure([{"ref": ref, "items": ["json-writer"]}]))
    assert [m["status"] for m in r["measured"]] == ["met"] and r["merged"]
    assert fake.calls() == [] and o.records == []
    s = bhcore.state(o.cfg)
    assert {b["id"]: b["status"] for b in s["bricks"]}["json-writer"] == "met"


def test_a_full_run_leads_with_the_product_view_and_records_auth_and_cost(toy, fake):
    o = orch(toy)
    res = run(o.run())
    assert list(res)[:3] == ["product", "status", "owner_questions"]
    assert res["auth"] == {
        "mode_at_start": "login",
        "mode_at_end": "login",
        "fallbacks_to_login": 0,
    }
    kinds = [j["job"] for j in res["jobs"]]
    assert kinds == ["gaps", "plan"]
    assert res["totals"]["jobs"] == len(kinds) and res["totals"]["cost_usd"] == pytest.approx(
        0.01 * len(kinds)
    )
    assert all(j["tokens"]["input"] == 10 for j in res["jobs"] if not j.get("skipped"))
    text = bhorch.summary_text(res, None)
    assert text.startswith("PRODUCT") and text.index("PRODUCT") < text.index("STATUS") < text.index(
        "AUTH"
    )
    assert res["phases"]["stopped"] == "no packets"  # building is the packet flow's, never a round here


def test_a_run_over_its_token_budget_stops_before_a_round(toy, fake):
    cfg = toy / ".brick-harness" / "config.json"
    d = json.loads(cfg.read_text())
    d["budgets"] = {"run_tokens": 1}
    cfg.write_text(json.dumps(d))
    commit_all(toy, "budget")
    res = run(orch(toy).run())
    assert res["phases"]["stopped"] == "budget"
    assert [j["job"] for j in res["jobs"]] == ["gaps", "plan"] and res["phases"]["rounds"] == []


def test_dry_run_lists_jobs_and_changes_nothing(toy, fake):
    head = git(toy, "rev-parse", "HEAD")
    p = subprocess.run(
        [
            sys.executable,
            str(BH),
            "--config",
            str(toy / ".brick-harness" / "config.json"),
            "run",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=toy,
    )
    assert fake.calls() == [] and git(toy, "rev-parse", "HEAD") == head
    assert p.stdout.startswith("PRODUCT") and "gaps review" in p.stdout, p.stderr
    assert not (toy / ".brick-harness" / "run-result.json").exists()


def test_the_bh_cli_runs_a_phase_and_writes_its_result_file(toy, fake):
    p = subprocess.run(
        [sys.executable, str(BH), "gaps", "--config", str(toy / ".brick-harness" / "config.json")],
        capture_output=True,
        text=True,
        cwd=toy,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads((toy / ".brick-harness" / "out" / "gaps-result.json").read_text())
    assert (
        out["phases"]["gaps"]["accepted"] == 0 and out["jobs"][0]["agent"] == "harness-gaps-reader"
    )


def test_owner_decides_gaps_become_the_owner_questions(toy, fake):
    gap = {
        "kind": "no-numeric-target",
        "summary": "the speed target is missing",
        "tag": "owner-decides",
        "evidence": [{"file": "features.md", "line": 1}],
    }
    fake.spec(outputs={**OUTPUTS, "harness-gaps-reader": {"gaps": [gap]}})
    res = run(orch(toy).run(skip=["plan", "harvest"]))
    assert [q["summary"] for q in res["owner_questions"]] == ["the speed target is missing"]
    assert res["owner_questions"][0]["id"].startswith("review:no-numeric-target:")


# ---------------------------------------------------------------- the agent files and schemas


def test_every_job_has_an_agent_file_with_model_tools_and_a_section():
    for job, (agent, phase) in bhorch.JOBS.items():
        d = bhorch.agent_def(agent)
        assert d["name"] == agent and d["model"] and d["tools"], agent
        body = (bhorch.AGENTS_DIR / f"{agent}.md").read_text()
        assert f"## Job: {job.replace('_', ' ')}" in body, (agent, job)
        assert phase in ("gaps", "plan", "harvest", "review", "test_author")
    assert bhorch.agent_def("harness-reviewer")["tools"] == [
        "Read",
        "Grep",
        "Glob",
        "Bash",
        "StructuredOutput",
    ]
    # stable text first: the rules every job shares come before the job's own section
    for agent in {a for a, _ in bhorch.JOBS.values()}:
        body = (bhorch.AGENTS_DIR / f"{agent}.md").read_text()
        assert body.index("## Rules (all jobs)") < body.index("## Job:")


ROW = {
    "id": "a-AC1",
    "scenario": "s",
    "given": [{"repo": {"name": "toy", "state": "base"}}],
    "when": {"entry_point": {"entry": "plugin_pytest"}},
    "then": [{"exit_code": {"code": 0}}],
    "traces_to": ["R3"],
    "verification": "test",
}


def test_job_schemas_are_self_contained_and_check_outputs():
    ok = {
        "gaps": {"gaps": [{"kind": "other", "summary": "s", "tag": "fixable", "evidence": []}]},
        "plan": PLAN_OUT,
        "harvest_find": {"candidates": []},
        "review": {"findings": [{"summary": "x", "severity": "S2"}]},
        "test_author": {"acceptance": [ROW]},
        "regression_row": {"acceptance": [ROW]},
    }
    assert set(ok) == set(bhorch.JOBS)
    for job, out in ok.items():
        s = bhorch.job_schema(job)
        assert "$ref" not in json.dumps(s) and bhcore.schema_errors(out, s) == [], job
    assert bhcore.schema_errors({"gaps": [{"kind": "nope"}]}, bhorch.job_schema("gaps"))


def test_the_workflow_path_is_gone():
    root = bhorch.PLUGIN_ROOT
    assert (
        not (root / "harness" / "workflows").exists()
        and not (root / "harness" / "lib" / "prelude.js").exists()
    )
    assert "workflows" not in json.loads((root / ".claude-plugin" / "plugin.json").read_text())


def test_claude_is_started_in_one_place_only():
    src = (ROOT / "lib" / "bhorch.py").read_text()
    assert src.count("create_subprocess_exec(") == 2  # the job's CLI and bh-measure; nothing else


# ---------------------------------------------------------------- safeguards proven here


def input_of(call):
    marker = "Input file (read it first; it names every other path): "
    return json.loads(Path(call["stdin"].split(marker)[1].split("\n")[0]).read_text())


def test_gaps_and_plan_jobs_get_the_decisions_and_answers_by_path_not_pasted(toy, fake):
    """SG-03, SG-16, SG-18: settled inputs are paths and config in the input file."""
    o = orch(toy)
    run(o.phase_gaps())
    run(o.phase_plan())
    g, p = [input_of(c) for c in fake.calls()]
    assert g["owner_answers_dir"] == ".brick-harness/decisions" and "standards" in g
    assert p["owner_answers_dir"] == ".brick-harness/decisions" and "sizing" in p
    plan_rules = (bhorch.AGENTS_DIR / "harness-planner.md").read_text()
    assert "citations, never copied text" in plan_rules and "settled inputs" in plan_rules


def test_a_job_prompt_is_paths_only_and_the_state_goes_through_a_file(toy, fake):
    """SG-07: no state value is typed into a prompt; the input file carries it."""
    o = orch(toy)
    run(o.phase_gaps())
    (c,) = fake.calls()
    assert "{" not in c["stdin"] and len(c["stdin"]) < 600
    assert input_of(c)["documents"]["features"]["rel"] == "features.md"


def test_a_re_review_job_is_given_only_the_diff_since_the_last_review_and_open_findings(toy, fake):
    """SG-13."""
    o = orch(toy)
    run(o.phase_gaps())
    assert input_of(fake.calls()[0])["review_input"]["since"] is None
    (toy / "features.md").write_text((toy / "features.md").read_text() + "\nNew text.\n")
    commit_all(toy, "docs")
    run(orch(toy).phase_gaps())
    ri = input_of(fake.calls()[1])["review_input"]
    assert ri["since"] and ri["changed"] == ["features.md"] and "New text." in ri["diff"]
    assert ri["open"] == []


def test_a_job_that_spent_money_and_failed_is_not_an_authentication_failure(toy, fake, monkeypatch):
    """A builder whose own tests mention authentication must not switch the run to login mode."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    fake.spec(fail=["harness-gaps-reader"], fail_text="authentication test failed", cost=0.5)
    o = orch(toy)
    gaps_job(o)
    assert [c["mode"] for c in fake.calls()] == ["bare"] and o.mode == "bare" and o.fallbacks == 0


def test_the_owner_is_told_about_overlay_candidates(toy, fake):
    res = run(orch(toy).run(skip=["gaps", "plan", "harvest"]))
    assert res["overlay_candidates"] == []
    assert list(res)[:4] == ["product", "status", "owner_questions", "overlay_candidates"]
