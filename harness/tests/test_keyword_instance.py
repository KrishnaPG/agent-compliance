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


def test_a_bare_schema_name_is_a_schema_of_the_repo_under_test(tmp_path):
    from when import load_schema

    (tmp_path / "harness" / "schema").mkdir(parents=True)
    (tmp_path / "harness" / "schema" / "x.schema.json").write_text('{"title": "planted"}')
    ctx = SimpleNamespace(state={"repo": tmp_path}, tree=tmp_path / "none")
    assert load_schema(ctx, "x.schema.json") == {"title": "planted"}

def test_a_lines_pattern_may_write_the_teaching_shape_inside_an_alternation():
    from then import then_lines

    def run(*lines):
        return SimpleNamespace(last=SimpleNamespace(stdout="\n".join(lines)))

    ok = run("[R-1] wrong thing -> right thing . ref", "fresh-stack runs are skipped")
    then_lines(ok, "stdout", "@teaching_shape|fresh-stack", every=True)
    bad = run("[R-1] wrong thing -> right thing . ref", "something else")
    try:
        then_lines(bad, "stdout", "@teaching_shape|fresh-stack", every=True)
    except AssertionError:
        return
    raise AssertionError("a line matching neither alternative must fail the row")
