"""validate: a row names the packet it was given as <id>_packet or assembled_<id>_packet."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from when import load_instance  # noqa: E402


def test_a_row_names_the_given_packet_as_id_packet(tmp_path):
    f = tmp_path / "p.json"
    f.write_text('{"id": "x"}')
    ctx = SimpleNamespace(
        state={"repo": tmp_path, "packet": {"id": "x", "repo_copy": f}}, tree=tmp_path / "none"
    )
    assert load_instance(ctx, "x_packet") == load_instance(ctx, "assembled_x_packet") == {"id": "x"}
