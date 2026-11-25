"""Rule selection (R12, section 6.6): the release checks of QBC-103, QBC-104, QBC-105 (i), (iii)
and (iv), QBC-106, QBC-110 and QBC-111, each with a negative control (QBC-109), and the one
traceability test. The toy runs on the plugin's own catalog: csv-reader is a queue worker that
imports a broker client, json-writer a pure library."""

import copy
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import bhcore
import bhorch
import bhpacket
import bhrules
import jsonschema
import pytest
from bhcore import HarnessError
from test_toy import commit_all, copy_toy, git
from test_bhorch import fake, input_of, orch, run  # noqa: F401  (fake is a fixture)
from test_rank import edit_json
from test_work_tracking import cfg_edit, plan_edit

PLUGIN = Path(__file__).resolve().parents[2]
RULES = tomllib.loads((PLUGIN / "catalog" / "rules.toml").read_text())
HOUSE = RULES["house"]
V1 = [ln for ln in (Path(__file__).parent / "fixtures" / "rules" / "v1-base-ids.txt").read_text().splitlines() if ln and ln[0] != "#"]
CLOSED = {"always", "messaging", "network-client", "http-server", "database", "auth", "deploy",
          "concurrency", "money", "time", "config", "dependency-change", "defect"}  # fmt: skip
MESSAGING = {k for k, v in HOUSE.items() if {"messaging", "deploy"} & set(v["applies"])}
NETWORK = {k for k, v in HOUSE.items() if "network-client" in v["applies"]}
CORE = {k for k, v in HOUSE.items() if "always" in v["applies"]}


@pytest.fixture
def toy(tmp_path):
    repo = tmp_path / "toy"
    copy_toy(repo)
    (repo / "src" / "queue_worker.py").write_text("import nats\n\n\nasync def handle(msg):\n    return msg.data\n")
    (repo / "src" / "json_writer.py").write_text("import json\n\n\ndef write(rows):\n    return json.dumps(rows)\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    cfg_edit(repo, standards={})
    plan_edit(repo, "bricks.json", lambda d: d["bricks"][0].update(path="src/queue_worker.py"))
    return repo


def conf(repo):
    return str(repo / ".brick-harness" / "config.json")


def rules_of(repo, item):
    return bhpacket.plan_packet(bhcore.Config(conf(repo)), item)["verifier"]["rules"]


def chosen(repo, item):
    return [r["id"] for r in rules_of(repo, item)]


def bh(capsys, *argv):
    code = bhorch.main(list(argv))
    return code, capsys.readouterr().out


def catalog(tmp_path, text):
    """A config whose catalog is ``text`` (a rules.toml)."""
    (tmp_path / "cat" / "catalog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cat" / "catalog" / "rules.toml").write_text(text)
    return SimpleNamespace(data={"standards": {"catalog": str(tmp_path / "cat")}}, dir=tmp_path)


def test_qbc_103_core_and_closed_tags(tmp_path):
    assert set(RULES["tags"]) == CLOSED == set(bhrules.TAGS)
    assert all(r["applies"] and set(r["applies"]) <= CLOSED for r in HOUSE.values() if not r.get("embodied_by"))
    core = [k for k, r in HOUSE.items() if "always" in r["applies"]]
    assert 0 < len(core) <= 10
    assert bhrules.rules_doc(catalog(tmp_path, '[house.XX-01]\ntext = "t"\nseverity = "S2"\napplies = ["time"]\n'))
    ten = "".join(f'[house.XX-{i}]\ntext = "t"\nseverity = "S2"\napplies = ["always"]\n' for i in range(10))
    assert len(bhrules.rules_doc(catalog(tmp_path, ten))["house"]) == 10  # a core of exactly 10 is allowed
    for bad in ('[house.XX-01]\ntext = "t"\nseverity = "S2"\napplies = ["queues"]\n', "[tags.queues]\n",
                "".join(f'[house.XX-{i}]\ntext = "t"\nseverity = "S2"\napplies = ["always"]\n' for i in range(11))):  # fmt: skip
        with pytest.raises(HarnessError, match="catalog-tags"):  # negative control: refused
            bhrules.rules_doc(catalog(tmp_path, bad))


def fresh_selection(repo, item, seed):
    """``bh rules --item`` in a new interpreter with its own hash seed: no state shared in-process."""
    lib = str(PLUGIN / "harness" / "lib")
    code = f"import sys; sys.path.insert(0, {lib!r}); import bhorch; sys.exit(bhorch.main(['rules', '--config', {conf(repo)!r}, '--item', {item!r}]))"
    r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True, check=True)
    sel = json.loads(r.stdout)
    return [x["id"] for x in sel["chosen"] + sel["more"]]


def test_qbc_104_facts_decide_at_0_tokens(toy):
    worker, library = chosen(toy, "csv-reader"), chosen(toy, "json-writer")
    assert CORE <= set(worker) and CORE <= set(library)  # the core reaches every item
    assert fresh_selection(toy, "csv-reader", "1") == fresh_selection(toy, "csv-reader", "2") == worker  # any process, any hash seed
    assert {"HO-01", "HO-02"} <= set(worker)  # (b) the owned path imports a broker client
    assert library and not set(library) & MESSAGING  # negative control: a pure library gets the core
    assert chosen(toy, "csv-reader") == worker  # the same inputs give the same selection
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(interfaces=[{"kind": "publishes", "name": "rows.written"}]))
    assert {"HO-01", "HO-02"} <= set(chosen(toy, "json-writer"))  # (b) a declared interface
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].pop("interfaces"))
    cfg_edit(toy, standards={"stack": ["nats-py==2.9.0"]})
    assert {"HO-01", "HO-02"} <= set(chosen(toy, "json-writer"))  # (a) the stack
    cfg_edit(toy, standards={})
    (toy / "requirements.txt").write_text("nats-py==2.9.0\n")
    edit_json(toy / ".brick-harness" / "config.json", lambda c: c["paths"].update(lockfiles=["requirements.txt"]))
    commit_all(toy, "lock")
    assert {"HO-01", "HO-02"} <= set(chosen(toy, "json-writer"))  # (a) the lock file's dependencies


def test_qbc_105_i_bh_rules_diff_prints_the_rules_the_change_adds(toy, capsys):
    item = ["rules", "--config", conf(toy), "--item", "json-writer"]
    code, out = bh(capsys, *item, "--diff")
    assert code == 0 and not set(json.loads(out)["added_by_diff"]) & NETWORK  # negative control
    (toy / "src" / "json_writer.py").write_text("import json\nimport httpx\n\n\ndef write(rows):\n    return json.dumps(rows)\n")
    sel = json.loads(bh(capsys, *item, "--diff")[1])
    assert "network-client" in sel["tags"]["diff"] and set(sel["added_by_diff"]) & NETWORK
    base = git(toy, "rev-parse", "HEAD").strip()
    commit_all(toy, "call out", "src")
    assert "network-client" in json.loads(bh(capsys, *item, "--diff", base, "HEAD")[1])["tags"]["diff"]
    assert "network-client" not in json.loads(bh(capsys, *item, "--diff")[1])["tags"]["diff"]
    packet = bhpacket.render_markdown(bhpacket.plan_packet(bhcore.Config(conf(toy)), "json-writer"))
    assert "`bh rules --item json-writer --diff`" in packet  # the packet names the self-check


def test_qbc_105_iii_bh_rule_prints_the_full_rule_from_the_repo(toy, capsys):
    code, out = bh(capsys, "rule", "--config", conf(toy), "HO-01")
    r = HOUSE["HO-01"]
    assert code == 0 and out.startswith(f"HO-01: {r['text']}\n")
    assert all(x in out for x in (r["why"], r["right"], r["question"], "Cites: "))
    assert bh(capsys, "rule", "--config", conf(toy), "XX-99")[0] == 2  # negative control


def test_qbc_105_iv_no_rule_is_dropped_for_size(toy):
    cfg = bhcore.Config(conf(toy))
    full = rules_of(toy, "csv-reader")
    cap = cfg.limit("packet_rules")
    assert cap == 15 and len(full) > cap
    rows = bhrules.rule_rows(cfg)
    assert all(r["message"] == bhrules.rule_text(rows, r["id"]) for r in full[:cap])
    assert all(r["message"].endswith(f"(bh rule {r['id']})") and len(r["message"]) < 80 for r in full[cap:])
    every = bhrules.select_rules(cfg, {"id": "w", "path": "src/queue_worker.py"}, [])
    assert [r["id"] for r in full] == every["chosen"] + every["more"]
    cfg_edit(toy, limits={"packet_rules": 2})
    small = rules_of(toy, "csv-reader")
    assert {r["id"] for r in small} == {r["id"] for r in full}  # a smaller cap drops none
    assert sum(not r["message"].endswith(f"(bh rule {r['id']})") for r in small) == 2  # negative control


def test_qbc_106_agents_add_owners_remove(toy, fake):  # noqa: F811
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(rules=[{"id": "DS-01", "reason": "it overwrites its output"}]))
    assert chosen(toy, "json-writer")[0] == "DS-01"  # the planner adds, with a reason
    schema = json.loads((PLUGIN / "harness" / "schema" / "bricks.schema.json").read_text())
    pin = {"$defs": schema.get("$defs", {}), **schema["properties"]["bricks"]["items"]["properties"]["rules"]["items"]}
    jsonschema.validate({"id": "DS-01", "reason": "r"}, pin)
    for bad in ("DS-01", {"id": "DS-01"}, {"id": "DS-01", "reason": " "}, {"id": "DS-01", "reason": "a\nb"}, {"id": "HO-01", "reason": "r", "remove": True}):
        with pytest.raises(jsonschema.ValidationError):  # negative controls: no reason, an empty or two-line one, a removal
            jsonschema.validate(bad, pin)
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(rules=["DS-01"]))  # the plan's validator refuses, teaching
    with pytest.raises(HarnessError, match=r"rules\[0\]: 'DS-01' is not of type 'object' -> A rule the planner adds carries a one-line reason \(QBC-106\)"):
        bhcore.load_json(bhcore.Config(conf(toy)).file("bricks"), "bricks")
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(rules=[{"id": "DS-01", "reason": "it overwrites its output"}]))
    (toy / "docs" / "agents").mkdir(parents=True)
    (toy / "docs" / "agents" / "design-compliance.md").write_text(
        "# Overlay\n\n## Check opt-outs\n\n- HO-01 not-applicable: the worker is the broker's own bridge\n- HO-02 not-applicable:\n"
    )
    commit_all(toy, "overlay", "docs")
    worker = chosen(toy, "csv-reader")
    assert "HO-01" not in worker and "HO-02" in worker  # removal needs a reason (negative control)
    cfg = bhcore.Config(conf(toy))
    lines = bhrules.project_rules(cfg)  # what a gaps or judge job gets: never the whole catalog
    assert 0 < len(lines) < len(HOUSE) and str(bhrules.rules_file(cfg)) not in json.dumps(lines)
    agents = sorted((PLUGIN / "agents").glob("harness-*.md"))
    assert len(agents) >= 7 and not [a.name for a in agents if "rules.toml" in a.read_text()]
    run(orch(toy).phase_gaps())
    (gaps,) = [c for c in fake.calls() if c["agent"] == "harness-gaps-reader"]
    given = input_of(gaps)["rules"]  # the gaps job's actual input: the project's selection
    assert given == lines and {r["id"] for r in given} == CORE | {"PRJ-0001-1"}  # and the toy's decision record (QBC-112)
    assert {r["id"] for r in given} != set(HOUSE)  # negative control: the whole catalog is not it


def test_qbc_106_embodies_marks_a_rule_and_never_removes_it(toy):
    """A dependency's ``embodies`` is a planner's word, not a fact, so it only marks the line: the
    rule stays in the packet (a false inclusion costs one line, QBC-104) and only the overlay removes."""
    worker = chosen(toy, "csv-reader")
    rid = worker[-1]
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][1].update(embodies=[rid]))
    assert chosen(toy, "csv-reader") == worker  # negative control: no dependency, no mark
    assert not any(r["message"].endswith("[embodied by json-writer]") for r in rules_of(toy, "csv-reader"))
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(depends_on=["json-writer"]))
    assert chosen(toy, "csv-reader") == worker  # kept, in the same place
    (line,) = [r for r in rules_of(toy, "csv-reader") if r["id"] == rid]
    assert line["message"].endswith("[embodied by json-writer]")
    cfg = bhcore.Config(conf(toy))
    ctx = bhcore.packet_context(cfg)
    sel = bhrules.select_rules(cfg, ctx["bricks"]["csv-reader"], list(ctx["bricks"].values()))
    assert sel["embodied"] == {rid: ["json-writer"]}


def no_rule_lost(house):
    missing = sorted(set(V1) - set(house))
    assert not missing, f"v1 rules lost: {missing}"


def test_qbc_110_no_rule_lost():
    assert len(V1) == 332
    no_rule_lost(HOUSE)
    embodied = {k: v["embodied_by"] for k, v in HOUSE.items() if v.get("embodied_by")}
    assert embodied and all(isinstance(m, str) and m and HOUSE[k]["text"] for k, m in embodied.items())
    with pytest.raises(AssertionError, match="HO-01"):  # negative control: a deleted v1 id fails
        no_rule_lost({k: v for k, v in HOUSE.items() if k != "HO-01"})


def explained(rules):
    for rid, r in rules["house"].items():
        for f in ("text", "why", "right", "question"):
            v = r.get(f, "")
            assert v.strip() and not re.fullmatch(r"\s*https?://\S+\s*", v), f"{rid}.{f} is empty or only a URL"
    for k, s in rules["standards"].items():
        assert s.get("summary", "").strip() and s["version"] not in ("book", "current"), f"standard {k}"


def test_qbc_111_explained_in_the_repo():
    explained(RULES)
    assert all(len(r["right"]) <= 160 for r in HOUSE.values())  # the packet's one line
    for part, key, field, value in (("house", "HO-01", "why", ""), ("house", "HO-02", "right", "https://example.org/x"),
                                    ("standards", "EIP", "summary", "")):  # fmt: skip
        bad = copy.deepcopy(RULES)
        bad[part][key][field] = value
        with pytest.raises(AssertionError):  # negative control
            explained(bad)


def ids_without_test(spec: str, names: set[str]) -> list[str]:
    section = re.split(r"\n#{2,3} ", spec.split("### 6.6", 1)[1], maxsplit=1)[0]
    ids = sorted(set(re.findall(r"^- QBC-(\d+)\.", section, re.M)) - {"109"})
    missing = [i for i in ids if not any(n.startswith(f"test_qbc_{i}_") for n in names)]
    # a requirement split into (i), (ii) ... gets a test per clause, named test_qbc_<id>_<clause>_
    for i, body in re.findall(r"^- QBC-(\d+)\.(.*?)(?=^- |\Z)", section, re.M | re.S):
        for c in re.findall(r"^  - \(([ivx]+)\)", body, re.M):
            if i != "109" and not any(n.startswith(f"test_qbc_{i}_{c}_") for n in names):
                missing.append(f"{i}-{c}")
    return missing


# Ids whose test is still owed; empty: every section 6.6 requirement has its test.
OWED: set[str] = set()


def test_qbc_109_every_section_6_6_requirement_has_a_test_named_for_it():
    spec = (PLUGIN / "docs" / "spec" / "quality-by-construction.md").read_text()
    names = {n for p in (PLUGIN / "harness" / "tests").glob("test_*.py") for n in re.findall(r"^def (test_qbc_\w+)", p.read_text(), re.M)}
    missing = ids_without_test(spec, names)
    assert set(missing) <= OWED, missing
    assert not OWED & {i for i in OWED if i not in missing}, "a QBC-107/108 test landed: empty OWED"
    assert ids_without_test(spec, names - {"test_qbc_110_no_rule_lost"}) == sorted(["110", *missing])  # negative control
    gone = {n for n in names if n.startswith("test_qbc_105_ii_")}
    assert gone and "105-ii" in ids_without_test(spec, names - gone)  # negative control: one clause's test removed


def test_selection_replays_at_any_commit_with_no_agent(toy, capsys):
    before = git(toy, "rev-parse", "HEAD").strip()
    plan_edit(toy, "bricks.json", lambda d: d["bricks"][0].update(path="src/csv_reader.py"))
    sel = json.loads(bh(capsys, "rules", "--config", conf(toy), "--item", "csv-reader", "--at", before)[1])
    assert "messaging" in sel["tags"]["contract"] and "HO-01" in {r["id"] for r in sel["chosen"]}
    now = json.loads(bh(capsys, "rules", "--config", conf(toy), "--item", "csv-reader")[1])
    assert "HO-01" not in {r["id"] for r in now["chosen"] + now["more"]}
