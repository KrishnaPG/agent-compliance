"""The config schema accepts the toy and sample configs (checked by jsonschema and by the stdlib subset validator)."""

import json
from pathlib import Path

import bhcore
import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
TOY = ROOT / "examples" / "toy"
TOYH = TOY / ".brick-harness"
CASES = [
    ("harness.config", ROOT / "examples" / "sample.config.json"),
    ("harness.config", TOYH / "config.json"),
    ("bricks", TOYH / "bricks.json"),
    ("targets", TOYH / "targets.json"),
    ("catalogue", TOYH / "catalogue.json"),
]


@pytest.mark.parametrize("schema,path", CASES, ids=[p.name for _, p in CASES])
def test_valid(schema, path):
    s = bhcore.load_schema(schema)
    jsonschema.Draft202012Validator.check_schema(s)
    data = json.loads(path.read_text())
    jsonschema.Draft202012Validator(s).validate(data)
    assert bhcore.schema_errors(data, s) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.pop("ecosystems"),
        lambda c: c["paths"].update(bogus="x"),
        lambda c: c.update(concurrency=0),
        lambda c: c.update(models={"nophase": "x"}),
        lambda c: c.update(create=["targets"]),
        lambda c: c.update(models={"decide": "x"}),
        lambda c: c["commands"]["test"].update(pending=True),
        lambda c: c["standards"].update(rules=["x"]),
        lambda c: c["commands"]["bench"].update(format="xml"),
    ],
)
def test_invalid_rejected_by_both(mutate):
    s = bhcore.load_schema("harness.config")
    c = json.loads((ROOT / "examples" / "sample.config.json").read_text())
    mutate(c)
    assert not jsonschema.Draft202012Validator(s).is_valid(c)
    assert bhcore.schema_errors(c, s) != []


def test_toy_state_has_no_problems():
    assert bhcore.state(bhcore.Config(TOYH / "config.json"))["problems"] == []


def test_root_resolution(tmp_path):
    cfg = {"commands": {"test": {"run": "true"}}, "ecosystems": ["python"]}
    (tmp_path / ".brick-harness").mkdir()
    (tmp_path / "elsewhere").mkdir()
    for f, extra in (
        (tmp_path / ".brick-harness" / "config.json", {}),
        (tmp_path / "plain.json", {}),
        (tmp_path / "elsewhere" / "c.json", {"root": ".."}),
    ):
        f.write_text(json.dumps({**cfg, **extra}))
    assert bhcore.Config(tmp_path / ".brick-harness" / "config.json").dir == tmp_path
    assert bhcore.Config(tmp_path / "plain.json").dir == tmp_path
    c = bhcore.Config(tmp_path / "elsewhere" / "c.json")
    assert c.dir == tmp_path
    assert (
        c.file("targets") == tmp_path / ".brick-harness" / "targets.json"
    )  # default under .brick-harness/
    assert c.file("measure_out") == tmp_path / ".brick-harness" / "out"


def test_list_paths_are_one_entry(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "features.md").write_text("# F\n")
    cfg = {
        "paths": {
            "features": ["a/features.md", "b/features.md"],
            "targets": "t.json",
            "bricks": "b.json",
            "catalogue": "c.json",
            "scoreboard": "s.json",
        },
        "commands": {"test": {"run": "true"}},
        "ecosystems": ["python"],
    }
    (tmp_path / "h.json").write_text(json.dumps(cfg))
    f = bhcore.state(bhcore.Config(tmp_path / "h.json"))["files"]["features"]
    assert f["exists"] is True
    assert f["path"] == f"{tmp_path}/a/features.md, {tmp_path}/b/features.md"
