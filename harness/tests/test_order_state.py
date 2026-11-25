"""The order engine's state is its jobs[*] records (bhorch.Orchestrator.keep): a restart skips a step
recorded done for the same packet sha, never because a file exists, and each builder job carries
its round, counted per packet across runs, so the item's rounds are computed and never stored."""

import json

import bhmetrics
from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fixtures and helpers)
from test_toy import commit_all, toy  # noqa: F401


def builder_rounds(res):
    return [(j["id"], j["round"]) for j in res["jobs"] if j.get("role") == "builder" and j.get("item") == "json-writer"]


def test_a_restart_skips_the_recorded_author_and_continues_the_rounds(toy, fake):  # noqa: F811
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["max_rounds"] = 2
    cfgp.write_text(json.dumps(cfg))
    commit_all(toy, "two rounds")
    fake.spec(outputs_by_item={"harness-test-author": ACCEPT}, files={"harness-builder": {}})  # a builder that builds nothing
    first = run(orch(toy).run(skip=["gaps", "plan", "harvest"]))
    authors = [c for c in fake.calls() if c["agent"] == "harness-test-author"]
    rounds = builder_rounds(first)
    assert [r for _, r in rounds] == [1, 2] and len({i for i, _ in rounds}) == 2  # one id per round

    second = run(orch(toy).run(skip=["gaps", "plan", "harvest"]))
    assert [c for c in fake.calls() if c["agent"] == "harness-test-author"] == authors  # recorded done: not relaunched
    assert builder_rounds(second) == []  # the packet's rounds are spent across runs
    stuck = [f for r in second["phases"]["rounds"] for f in r["facts"] if f["kind"] == "stuck"]
    assert stuck and "round limit of 2" in stuck[0]["detail"]
    assert bhmetrics.job_totals(toy / ".brick-harness" / "out")["json-writer"]["rounds"] == 2  # computed, not stored


def test_a_test_file_without_a_recorded_step_is_authored(toy, fake):  # noqa: F811
    """The state decides, not the file system: a test file nobody recorded does not count as done."""
    fake.spec(outputs_by_item={"harness-test-author": ACCEPT}, files={"harness-builder": {}})
    (toy / "tests" / "acceptance").mkdir(parents=True, exist_ok=True)
    (toy / "tests" / "acceptance" / "test_json_writer.py").write_text("def test_x():\n    assert False\n")
    commit_all(toy, "a test file from elsewhere")
    run(orch(toy).run(skip=["gaps", "plan", "harvest"]))
    assert [c for c in fake.calls() if c["agent"] == "harness-test-author"]
