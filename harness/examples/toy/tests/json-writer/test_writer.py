import json

from json_writer import write_rows


def test_round_trip():
    rows = [{"a": "1", "b": "é"}]
    assert json.loads(write_rows(rows)) == rows


def test_empty():
    assert write_rows([]) == "[]"
