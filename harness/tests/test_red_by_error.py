"""d6 (R3, L3): a test that errors on main is recorded red_by_error, never red, and its file goes back
to the test author with the error, at most max_rounds times; no builder starts on it."""

import json

from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fake is a fixture)

ERRORS = {  # an import error: the test cannot run, so it is not red by an assertion
    "acceptance": ACCEPT["json-writer"]["acceptance"],
    "test_code": "import no_such_module  # noqa: F401\n\n\ndef test_json_writer_AC1_works():\n    assert True\n",
}


def test_a_test_that_errors_on_main_goes_back_to_the_test_author(toy, fake):  # noqa: F811
    fake.spec(outputs_by_item={"harness-test-author": {**ACCEPT, "json-writer": ERRORS}})
    res = run(orch(toy).run(skip=["harvest"]))
    jw = [j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == "json-writer"]
    assert jw[:4] == ["test_author", "red_run", "test_author", "red_run"]
    assert "builder" not in jw  # nothing is built on tests that are not red by an assertion
    rnd = next(r for r in res["phases"]["rounds"] if r["item"] == "json-writer")
    kinds = {f["kind"] for f in rnd["facts"]}
    assert "red_by_error" in kinds and "red" not in kinds and rnd["status"] == "stuck"
    inputs = [json.loads(f.read_text()) for f in (toy / ".brick-harness" / "out" / "jobs").glob("*.input.json")]
    again = [i for i in inputs if i.get("task") == "test_author" and i.get("item") == "json-writer" and i.get("feedback")]
    assert again and "red-by-error" in json.dumps(again[0]["feedback"])  # the author is told it errored
