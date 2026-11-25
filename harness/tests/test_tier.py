"""R6, QBC-25 to QBC-30: the tier is derived from the declared paths and the actual diff.

Three planted cases: a minor pin bump stays mechanical, a major bump is design-affecting, and a
docs-only packet whose diff touches a compose file is re-planned with the fact "tier X from
paths Y" and built again at that tier; nothing is refused. The trigger table is the plugin's
default, which `tiers.triggers` in `.brick-harness/config.json` replaces (P8).
"""

import json

import bhcore
import bhpacket
import pytest
from test_bhorch import fake  # noqa: F401  (the fake claude fixture)
from test_setup_inference import bh_run  # noqa: F401  (bh run through its CLI entry)
from test_toy import commit_all, git


def uv_lock(**pkgs):
    rows = "".join(f'\n[[package]]\nname = "{n}"\nversion = "{v}"\n' for n, v in pkgs.items())
    return f'version = 1\nrequires-python = ">=3.12"\n{rows}'


def npm_lock(**pkgs):
    packages = {"": {"name": "app"}} | {
        f"node_modules/{n}": {"version": v} for n, v in pkgs.items()
    }
    return json.dumps({"name": "app", "lockfileVersion": 3, "packages": packages})


def bump(tmp_path, name, before, after):
    """A repository whose branch changes lockfile ``name`` from ``before`` to ``after``; the
    tier the measurer derives from that diff, and why."""
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / name).write_text(before)
    git(repo, "init", "-q", "-b", "main")
    base = commit_all(repo, "base")
    (repo / name).write_text(after)
    sha = commit_all(repo, "bump")
    diff = git(repo, "diff", "--name-only", base, sha).splitlines()
    return bhpacket.tier_of({}, diff, bhcore.major_bumps(repo, base, sha, diff))


@pytest.mark.parametrize(
    "name, lock",
    [("uv.lock", uv_lock), ("package-lock.json", npm_lock)],
    ids=["python-packaging", "npm-semver"],
)
def test_a_patch_or_minor_pin_bump_stays_mechanical(tmp_path, name, lock):
    tier, why = bump(
        tmp_path, name, lock(httpx="0.28.1", rich="14.0.0"), lock(httpx="0.28.2", rich="14.2.0")
    )
    assert (tier, why) == ("mechanical", [])


@pytest.mark.parametrize(
    "name, lock",
    [("uv.lock", uv_lock), ("package-lock.json", npm_lock)],
    ids=["python-packaging", "npm-semver"],
)
def test_a_major_pin_bump_is_design_affecting(tmp_path, name, lock):
    tier, why = bump(
        tmp_path, name, lock(httpx="0.28.1", rich="14.0.0"), lock(httpx="0.28.1", rich="15.0.0")
    )
    assert (tier, why) == ("design-affecting", [f"{name} rich 14.0.0 -> 15.0.0"])


def test_the_launch_tier_comes_from_the_declared_paths_and_the_project_may_override_the_triggers():
    assert bhpacket.tier_of({}, ["docs/guide.md"]) == ("mechanical", [])
    assert bhpacket.tier_of({}, ["db/schema.sql"]) == ("design-affecting", ["db/schema.sql"])
    own = {"tiers": {"triggers": [{"paths": ["docs/"], "tier": "design-affecting"}]}}
    assert bhpacket.tier_of(own, ["docs/guide.md", "db/schema.sql"]) == (
        "design-affecting",
        ["docs/guide.md"],
    )


GUIDE_TEST = (
    "from pathlib import Path\n\n\n"
    "def test_guide_AC1_the_guide_is_written():\n"
    '    """guide-AC1"""\n'
    "    assert (Path(__file__).resolve().parents[2] / 'docs' / 'guide.md').is_file()\n"
)


@pytest.fixture
def docs_repo(tmp_path):
    """One planned item whose declared path is a docs file: a mechanical packet."""
    repo = tmp_path / "docs-item"
    for d in ("docs", "tests", ".brick-harness"):
        (repo / d).mkdir(parents=True)
    (repo / "pytest.ini").write_text("[pytest]\n")
    (repo / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
    (repo / "docs" / "build-order.md").write_text(
        "# Plan\n\n## Build order\n\n1. guide: the user guide.\n"
    )
    (repo / "docs" / "features.md").write_text(
        "# Features\n\n## F1 guide\n\n- Acceptance checks:\n  - a guide\n"
    )
    brick = {
        "id": "guide",
        "job": "Write the user guide.",
        "features": ["F1"],
        "ecosystem": "python",
        "path": "docs/guide.md",
        "source": "docs/build-order.md:5",
    }
    (repo / ".brick-harness" / "bricks.json").write_text(json.dumps({"bricks": [brick]}))
    (repo / ".brick-harness" / "targets.json").write_text(
        json.dumps(
            {"targets": [{"item": "guide", "metric": "tests.failed", "op": "==", "value": 0}]}
        )
    )
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "docs item")
    return repo


def test_a_docs_packet_whose_diff_touches_compose_is_replanned_not_refused(docs_repo, fake, bh_run):  # noqa: F811
    accept = {
        "guide": {
            "acceptance": [
                {
                    "id": "guide-AC1",
                    "scenario": "s",
                    "traces_to": ["docs/build-order.md:5"],
                    "verification": "test",
                }
            ],
            "test_code": GUIDE_TEST,
        }
    }
    fake.spec(
        outputs_by_item={"harness-test-author": accept},
        files={"harness-builder": {"docs/guide.md": "# Guide\n", "compose.yaml": "services: {}\n"}},
    )
    res, _ = bh_run(docs_repo)
    rounds = res["phases"]["rounds"]
    assert [(r["item"], r["status"]) for r in rounds] == [("guide", "re-tiered"), ("guide", "met")]
    scope = [f for f in rounds[0]["facts"] if f["kind"] == "scope"]
    assert [f["detail"] for f in scope] == ["tier design-affecting from paths compose.yaml"]
    assert not [
        f for f in rounds[1]["facts"] if f["kind"] == "scope"
    ]  # built again at its real tier
    log = git(docs_repo, "log", "--format=%s", "main")
    assert (
        "brick-harness: re-tier guide as design-affecting" in log
        and "brick-harness: merge guide" in log
    )
    final = json.loads(git(docs_repo, "show", "HEAD:.brick-harness/packets/guide.json"))
    assert final["tier"] == "design-affecting"
    planned = git(docs_repo, "log", "--format=%H", "--grep", "acceptance guide", "main").split()[-1]
    assert (
        json.loads(git(docs_repo, "show", f"{planned}:.brick-harness/packets/guide.json"))["tier"]
        == "mechanical"
    )
