"""d3 (R5, QBC-51, P4): a builder that finishes without running `bh check` is not refused. bh check
is the builder's own paved-road self-check, never a gate: the measurer alone decides met."""

from test_bhorch import ACCEPT, JSON_WRITER, fake, orch, run  # noqa: F401  (fake is a fixture)


def test_a_build_finished_without_bh_check_is_measured_and_merged(toy, fake):  # noqa: F811
    fake.spec(  # the fake builder writes and commits; it never runs bh check
        outputs_by_item={"harness-test-author": ACCEPT},
        files={"harness-builder": {"src/json_writer.py": JSON_WRITER}},
    )
    res = run(orch(toy).run(skip=["harvest"]))
    rounds = {r["item"]: r for r in res["phases"]["rounds"]}
    assert rounds["json-writer"]["status"] == "met"
    kinds = {f["kind"] for r in rounds.values() for f in r["facts"]}
    assert not kinds & {"launch_refused", "stuck"}
