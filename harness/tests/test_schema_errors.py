"""The harness validates with jsonschema, so every keyword of a schema counts and a gap kind is
defined in gaps.schema.json alone (RH-M6)."""

import json
import shutil

import bhcore


def test_a_keyword_the_old_validator_ignored_rejects_bad_input():
    schema = bhcore.load_schema("tracker")
    item = {"ref": "", "title": "t", "state": "open"}  # ref has minLength 1
    errs = bhcore.schema_errors(item, schema["$defs"]["entry"], schema)
    assert any(".ref" in e and "non-empty" in e for e in errs), errs


def test_a_gap_kind_added_to_the_schema_alone_is_accepted_and_removed_one_is_not(tmp_path, monkeypatch):
    shutil.copytree(bhcore.SCHEMA_DIR, tmp_path / "schema")
    path = tmp_path / "schema" / "gaps.schema.json"
    schema = json.loads(path.read_text())
    schema["$defs"]["gap"]["properties"]["kind"]["enum"].append("newly-added-kind")
    path.write_text(json.dumps(schema))
    monkeypatch.setattr(bhcore, "SCHEMA_DIR", tmp_path / "schema")
    gap = {"kind": "newly-added-kind", "summary": "s", "tag": "fixable", "evidence": [{"file": "a", "line": 1}]}
    assert "newly-added-kind" in bhcore.gap_kinds()
    assert bhcore.schema_errors({"gaps": [gap]}, bhcore.load_schema("gaps")) == []
    assert bhcore.schema_errors({"gaps": [{**gap, "kind": "never-added"}]}, bhcore.load_schema("gaps"))
