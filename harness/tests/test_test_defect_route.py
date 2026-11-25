"""A faulty acceptance test goes back to its author (R3, IR-M2, L3), and an item whose acceptance
tests are red on main is finished before a stale item is rebuilt (Kanban: finish before start).

The toy: json-writer is built first; its author's test counts the writes since import, so it
leaks the module's state between tests. csv2json's build makes its own test call the writer
before that test runs, so json-writer's test passes alone and fails in the suite (an Interacting
Test, xUnit Test Patterns). The builder of csv2json may not edit tests: it claims the defect, the
program runs the test alone, and json-writer's author corrects it.
"""

import json

from test_bhorch import ACCEPT, fake, orch, run  # noqa: F401  (fake is a fixture)
from test_toy import ROOT, commit_all, git

TOY = ROOT / "examples" / "toy"

HEAD = "import importlib\nimport sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))\n\n\n"
LEAKY = HEAD + (
    "def test_json_writer_AC1_counts_writes():\n"
    '    """json-writer-AC1"""\n'
    "    w = importlib.import_module('json_writer')\n"
    "    w.write_rows([{'a': '1'}])\n"
    "    assert w.WRITES == 1  # counts every write since import: the state of earlier tests\n"
)
OWNED = HEAD + (
    "def test_json_writer_AC1_counts_writes():\n"
    '    """json-writer-AC1"""\n'
    "    w = importlib.import_module('json_writer')\n"
    "    w.WRITES = 0  # the test sets up the state it reads\n"
    "    w.write_rows([{'a': '1'}])\n"
    "    assert w.WRITES == 1\n"
)
PRETTY = HEAD + (
    "def test_csv2json_AC1_indents():\n"
    '    """csv2json-AC1"""\n'
    "    c = importlib.import_module('csv2json')\n"
    "    assert c.convert('a\\n1\\n', indent=1) == '[\\n {\\n  \"a\": \"1\"\\n }\\n]'\n"
)
WRITER = (  # the toy's json-writer, counting its writes in module state
    "import json\n\nWRITES = 0\n\n\n"
    "def write_rows(rows, indent=None):\n"
    "    global WRITES\n"
    "    WRITES += 1\n"
    "    return json.dumps(rows, ensure_ascii=False, indent=indent)\n"
)
CSV2JSON = (TOY / "src" / "csv2json.py").read_text().replace(
    "def convert(text: str) -> str:\n    return write_rows(read_rows(text))",
    "def convert(text: str, indent: int | None = None) -> str:\n    return write_rows(read_rows(text), indent=indent)",
)
LEAKY_ID = "tests/acceptance/test_json_writer.py::test_json_writer_AC1_counts_writes"
OWN_ID = "tests/acceptance/test_csv2json.py::test_csv2json_AC1_indents"


def answer(item, code):
    return {"output": {"acceptance": ACCEPT[item]["acceptance"], "test_code": code}}


def spec(fake, json_writer_tests, csv2json_rounds):  # noqa: F811
    fake.spec(
        rounds_by_item={
            "harness-test-author": {
                "csv-reader": [{"output": ACCEPT["csv-reader"]}],
                "json-writer": [answer("json-writer", c) for c in json_writer_tests],
                "csv2json": [answer("csv2json", PRETTY)],
            },
            "harness-builder": {
                "json-writer": [{"files": {"src/json_writer.py": WRITER}}],
                "csv2json": csv2json_rounds,
            },
        }
    )


def roles(res, item):
    return [j.get("role") or j.get("step") for j in res["jobs"] if j.get("item") == item]


def inputs(toy, item):
    found = [json.loads(f.read_text()) for f in (toy / ".brick-harness" / "out" / "jobs").glob("*.input.json")]
    return [i for i in found if i.get("task") == "test_author" and i.get("item") == item]


def test_a_confirmed_test_defect_goes_to_its_author_and_the_item_ends_met(toy, fake):  # noqa: F811
    claim = {"test_defects": [{"test": LEAKY_ID, "evidence": "passes alone, fails after test_csv2json ran"}]}
    built = {"src/csv2json.py": CSV2JSON}
    spec(fake, [LEAKY, OWNED], [{"files": built, "output": claim}, {"files": built}])
    res = run(orch(toy).run(skip=["harvest"]))
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]} == {"csv-reader": "met", "json-writer": "met", "csv2json": "met"}
    c2j = roles(res, "csv2json")
    assert c2j[:6] == ["test_author", "red_run", "builder", "measurer", "test_defect", "red_run"]
    assert c2j.count("builder") == 2 and c2j[-1] == "merge"  # rebuilt on the corrected tests, then merged
    fixes = [i for i in inputs(toy, "json-writer") if i.get("feedback")]
    assert len(fixes) == 1 and "passes alone and fails in the suite" in json.dumps(fixes[0]["feedback"])
    assert "fresh fixture" in json.dumps(fixes[0]["feedback"])  # wrong -> right -> prevent
    log = git(toy, "log", "--format=%s", "main")
    assert "brick-harness: acceptance csv2json: the tests of json-writer corrected" in log
    assert (toy / "tests" / "acceptance" / "test_json_writer.py").read_text() == OWNED  # the author's bytes, no hand edit
    assert "tests/conftest.py" not in git(toy, "ls-files")


def test_a_false_test_defect_claim_is_refused_taught_and_costs_its_round(toy, fake):  # noqa: F811
    claim = {"test_defects": [{"test": OWN_ID, "evidence": "the expected text looks wrong"}]}
    spec(fake, [OWNED], [{"files": {}, "output": claim}, {"files": {"src/csv2json.py": CSV2JSON}}])
    res = run(orch(toy).run(skip=["harvest"]))
    rnd = next(r for r in res["phases"]["rounds"] if r["item"] == "csv2json")
    assert rnd["status"] == "met"
    c2j = roles(res, "csv2json")
    assert c2j[:5] == ["test_author", "red_run", "builder", "measurer", "test_defect"]
    assert c2j.count("test_author") == 1 and len(inputs(toy, "json-writer")) == 1  # nobody's tests went back
    builder_prompts = [c["stdin"] for c in fake.calls() if c["agent"] == "harness-builder" and "csv2json" in c["cwd"]]
    second = builder_prompts[1]
    assert "failed alone" in second and "the build is wrong, not the test" in second and "-> make it pass" in second
    rounds = [j["round"] for j in res["jobs"] if j.get("role") == "builder" and j.get("item") == "csv2json"]
    assert rounds == [1, 2]  # the refused claim spent round 1


def test_an_item_red_on_main_is_finished_before_a_stale_item_is_rebuilt(toy, fake):  # noqa: F811
    """The deadlock of a run: csv2json's tests are red on main (its build ran out of rounds) and a
    hand commit makes json-writer stale. json-writer is measured with csv2json's red tests in its
    suite, so it can never be met first, and csv2json waited for it. Now csv2json goes first."""
    spec(fake, [OWNED], [{"files": {}}, {"files": {"src/csv2json.py": CSV2JSON}}])
    first = orch(toy)
    first.cfg.data["max_rounds"] = 1
    res = run(first.run(skip=["harvest"]))
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["csv2json"] == "unmet"
    (toy / "src" / "json_writer.py").write_text(WRITER + "# a hand edit\n")
    conf = toy / ".brick-harness" / "config.json"
    data = json.loads(conf.read_text())  # each item measured by the whole suite, as a project's own recipe runs it
    data["commands"]["test"]["run"] = data["commands"]["test"]["run"].replace("tests/{item}", "tests")
    conf.write_text(json.dumps(data, indent=2) + "\n")
    commit_all(toy, "a hand edit of json-writer; the whole suite per item")
    res = run(orch(toy).run(skip=["harvest"]))
    assert res["phases"]["rounds"][0]["item"] == "csv2json"
    assert {r["item"]: r["status"] for r in res["phases"]["rounds"]}["csv2json"] == "met"
    assert "builder" not in roles(res, "json-writer")  # re-measured after the merge, never rebuilt
    assert res["status"]["all_met"], res["status"]
