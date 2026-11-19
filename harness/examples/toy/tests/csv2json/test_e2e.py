import json
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def run(tmp_path, text):
    f = tmp_path / "in.csv"
    f.write_text(text, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SRC / "csv2json.py"), str(f)],
        capture_output=True,
        text=True,
        check=True,
        cwd=SRC,
    )
    return json.loads(out.stdout)


def test_n_rows_become_n_objects(tmp_path):
    assert run(tmp_path, "id,name\n1,a\n2,b\n3,c\n") == [
        {"id": str(i), "name": n} for i, n in ((1, "a"), (2, "b"), (3, "c"))
    ]


def test_quoted_fields_survive(tmp_path):
    assert run(tmp_path, 'a,b\n"1,2","x\ny"\n') == [{"a": "1,2", "b": "x\ny"}]


def test_empty_file(tmp_path):
    assert run(tmp_path, "") == []
