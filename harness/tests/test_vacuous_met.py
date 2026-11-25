"""A pending item is never met by an implicit measure, and an item with a packet is met only by its own
acceptance tests (QBC section 0 R3, packet-standards L5; ISTQB: entry criteria hold before exit
criteria are judged, and an exit criterion needs executed tests).

A project whose test recipe runs the whole suite built one item; another item is pending (no packet,
no build). ``bh measure`` at HEAD with no item leaves the pending one alone: it stays unmet and queued
for its test author, while the built item with passing tests is met (the negative control)."""

import json

import bhcore
import bhpacket
from junitparser import Skipped, TestCase
from test_bhorch import ACCEPT, orch, run
from test_toy import commit_all, copy_toy, git

WHOLE_SUITE = "PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests --junitxml {out}/junit.xml"


def _author(repo, item):
    """The test author's step: the item's packet with its rows kept in custody, and its acceptance file committed."""
    cfg = bhcore.Config(repo / ".brick-harness" / "config.json")
    packet = {**bhpacket.plan_packet(cfg, item), "acceptance": ACCEPT[item]["acceptance"]}
    bhpacket.custody_store(repo, (json.dumps(packet, indent=2) + "\n").encode())
    test = repo / bhpacket.acceptance_file(packet)
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text(ACCEPT[item]["test_code"])
    commit_all(repo, f"acceptance {item}")
    return packet


def _project(tmp_path, recipe=WHOLE_SUITE):
    """The toy with only csv-reader started (source in, its test author's tests committed); json-writer
    is pending: no source, no packet, no build, and no tests of its own."""
    toy = tmp_path / "toy"
    copy_toy(toy)
    c = toy / ".brick-harness" / "config.json"
    data = json.loads(c.read_text())
    data["commands"]["test"]["run"] = recipe
    c.write_text(json.dumps(data, indent=2))
    git(toy, "init", "-q", "-b", "main")
    commit_all(toy, "toy")
    git(toy, "rm", "-rq", "tests/csv-reader", "tests/json-writer", "tests/csv2json")
    commit_all(toy, "a whole-suite test recipe")
    _author(toy, "csv-reader")
    return toy


def test_an_implicit_measure_leaves_a_pending_item_unmet_and_queued_for_its_test_author(tmp_path):
    toy = _project(tmp_path)
    res = run(orch(toy).phase_measure())
    got = {r["item"]: r["status"] for r in res["remeasured"]}
    assert got.get("csv-reader") == "met", res  # the negative control: built, its own tests pass
    assert "json-writer" not in got, res  # pending: no other item's passing tests make it met
    status = {b["id"]: b["status"] for b in orch(toy).state()["bricks"]}
    assert status["json-writer"] != "met" and status["json-writer"] in bhcore.READY_FROM
    assert "json-writer" in orch(toy).queue(set())
    dry = run(orch(toy, dry=True).run(skip=["gaps", "plan", "harvest"]))
    assert {"item": "json-writer", "dry_run": True} in dry["phases"]["rounds"]


def test_a_packet_whose_acceptance_file_ran_no_test_is_unmet(tmp_path):
    """The toy's own recipe runs tests/csv-reader only: its packet's acceptance file never runs."""
    toy = _project(tmp_path, "PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/csv-reader --junitxml {out}/junit.xml")
    (toy / "tests" / "csv-reader").mkdir()
    (toy / "tests" / "csv-reader" / "test_other.py").write_text("def test_other():\n    assert True\n")
    commit_all(toy, "another test")
    r = bhcore.measure(bhcore.Config(toy / ".brick-harness" / "config.json"), [("csv-reader", "HEAD")])["items"]["csv-reader"]
    assert r["status"] == "unmet", r
    assert any("no acceptance tests ran for csv-reader" in e for e in r["errors"]), r


def test_own_tests_are_those_of_the_packets_acceptance_files(tmp_path):
    packet = {"verifier": {"acceptance_paths": ["tests/acceptance/test_csv_reader.py"]}}
    own = TestCase("test_anything", classname="tests.acceptance.test_csv_reader")
    other = TestCase("test_csv_reader_AC1", classname="tests.test_other")
    skipped = TestCase("test_x", classname="tests.acceptance.test_csv_reader")
    skipped.result = [Skipped()]
    assert bhcore.own_tests_ran("csv-reader", packet, [own, other]) is None  # not named after an id: still its own
    for cases in ([other], [skipped], []):
        why = bhcore.own_tests_ran("csv-reader", packet, cases)
        assert why and "no acceptance tests ran for csv-reader" in why
    node = TestCase("greet works", classname="test")  # node's junit reporter: an absolute file, no module path
    node._elem.set("file", "/work/clone/test/acceptance/greet.test.js")
    assert bhcore.own_tests_ran("greet", {"verifier": {"acceptance_paths": ["test/acceptance/greet.test.js"]}}, [node]) is None
