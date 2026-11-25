"""scan kind frontmatter lists the front matter fields, narrowed to those matching the row's pattern."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
from when import when_scan  # noqa: E402


def scan(tmp_path, pattern=None):
    d = tmp_path / "skills" / "x"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: x\ndescription: use vet-oss before adoption\nmodel: sonnet\n---\nbody\n")
    ctx = SimpleNamespace(state={"repo": tmp_path})
    out = when_scan(ctx, ["skills/*/SKILL.md"], "frontmatter", pattern)
    return out.extra["matches"]


def test_without_a_pattern_every_field_is_listed(tmp_path):
    assert len(scan(tmp_path)) == 3


def test_a_pattern_keeps_only_the_matching_fields(tmp_path):
    assert len(scan(tmp_path, "description: .*vet-oss")) == 1
    assert scan(tmp_path, "description: .*bug-analysis") == []
