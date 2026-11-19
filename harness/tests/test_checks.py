"""Unit checks of the mechanical gap helpers and lockfile readers."""

import json
from pathlib import Path

import bhcore
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_line_of_never_fabricates_and_matches_whole_tokens(tmp_path):
    p = tmp_path / "b.json"
    p.write_text('{"id": "csv-reader-x"}\n{"id": "csv-reader"}\n')
    assert bhcore._line_of(p, '"csv-reader"') == 2
    assert bhcore._line_of(p, "csv-reader") == 2  # not the -x line
    assert bhcore._line_of(p, "absent") is None
    assert bhcore._line_of(None, "x") is None


def test_gap_without_a_line_is_marked_unlocated():
    g = bhcore._gap("other", "s", "fixable", [])
    assert g["unlocated"] is True and g["evidence"] == []


@pytest.mark.parametrize(
    "run,flagged",
    [
        ("PYTHONPATH=src python3 -m pytest", False),
        ("FOO=1 BAR=2 scripts/run.sh", True),
        ("{root}/scripts/run.sh {item}", False),
        ("$HOME/bin/x", False),
        ("make test", False),
        ("<test command>", True),
    ],
)
def test_command_detection_skips_env_prefix_and_templates(tmp_path, run, flagged):
    assert (bhcore._cmd_problem({"run": run}, tmp_path) is not None) is flagged


def test_numbers_on_a_line_ignore_thousand_separators():
    assert 20000 in bhcore._numbers("at least 20,000 rows/s")
    assert 1500.5 in bhcore._numbers("p95 1 500.5 ms")


def test_lockfile_readers_and_malformed_files(tmp_path):
    (tmp_path / "yarn.lock").write_text(
        '"@scope/pkg@^1.0.0", "@scope/pkg@^1.1.0":\n  version "1.2.3"\n\nleft-pad@^1:\n  version "1.3.0"\n'
    )
    (tmp_path / "pnpm-lock.yaml").write_text("packages:\n  /lodash@4.17.21:\n    resolution: {}\n")
    (tmp_path / "go.sum").write_text(
        "github.com/pkg/errors v0.9.1 h1:x=\ngithub.com/pkg/errors v0.9.1/go.mod h1:y=\n"
    )
    (tmp_path / "Gemfile.lock").write_text("GEM\n  specs:\n    rake (13.2.1)\n      dep (>= 1)\n")
    (tmp_path / "uv.lock").write_text("not [ toml")
    (tmp_path / "package-lock.json").write_text("{broken")
    problems: list[str] = []
    v = bhcore.lock_versions(
        [
            tmp_path / n
            for n in (
                "yarn.lock",
                "pnpm-lock.yaml",
                "go.sum",
                "Gemfile.lock",
                "uv.lock",
                "package-lock.json",
            )
        ],
        problems,
    )
    assert v["@scope/pkg"] == "1.2.3" and v["left-pad"] == "1.3.0"
    assert v["lodash"] == "4.17.21" and v["github-com/pkg/errors"] == "v0.9.1"
    assert v["rake"] == "13.2.1" and "dep" not in v
    assert len(problems) == 2


def test_union_catalogue_validates():
    a = {"entries": [{"job": "j", "ecosystem": "e", "library": "x", "used_by": ["a"]}]}
    b = {"entries": [{"job": "j", "ecosystem": "e", "library": "x", "used_by": ["b"]}]}
    assert bhcore.union_catalogue(a, b)["entries"][0]["used_by"] == ["a", "b"]
    with pytest.raises(bhcore.HarnessError):
        bhcore.union_catalogue(a, {"entries": [{"job": "j", "ecosystem": "e", "library": "y"}]})


def test_gap_kinds_agree_everywhere():
    schema = bhcore.load_schema("gaps")["$defs"]["gap"]["properties"]["kind"]["enum"]
    prelude = (ROOT / "lib" / "prelude.js").read_text()
    js = json.loads(
        prelude[
            prelude.index("const GAP_KINDS = ") + len("const GAP_KINDS = ") : prelude.index(
                "]\n", prelude.index("const GAP_KINDS")
            )
            + 1
        ]
        .replace("'", '"')
        .replace("\n", "")
    )
    assert list(bhcore.GAP_KINDS) == schema == js
