"""bh run pulls work Kanban-style (WIP limit, finish before start): the work queue is every packet
that is not met (R5: the planner's and orchestrator's output is packets); gaps and plan run only when
that queue is empty."""

import hashlib
import json
from datetime import UTC, datetime

import bhpacket
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_toy import commit_all


def test_waiting_work_starts_no_gaps_or_plan_job(toy, fake):  # noqa: F811
    res = run(orch(toy).run(skip=["harvest"]))
    assert not {"gaps", "plan"} & {j.get("job") for j in res["jobs"]}


def test_an_empty_queue_runs_gaps_then_plan(toy, fake):  # noqa: F811
    bricks = toy / ".brick-harness" / "bricks.json"
    doc = json.loads(bricks.read_text())
    doc["bricks"] = []
    bricks.write_text(json.dumps(doc))
    commit_all(toy, "nothing planned")
    res = run(orch(toy).run(skip=["harvest"]))
    assert [j.get("job") for j in res["jobs"]][:2] == ["gaps", "plan"]


def test_a_packet_outside_the_plan_is_queued_until_its_merge_is_recorded(toy, fake):  # noqa: F811
    o = orch(toy)
    path = bhpacket.packet_path(toy, "extra")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": "extra"}))
    assert "extra" in o.queue(set())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    o.keep(bhpacket.program_job("merge", "extra", datetime.now(UTC), digest))
    assert "extra" not in o.queue(set())
    path.write_text(json.dumps({"id": "extra", "goal": "changed"}))  # a changed packet is new work
    assert "extra" in o.queue(set())
