"""R6, QBC-25 to QBC-30: the tier is derived from the declared paths and the actual diff.

Mechanical is proven from facts (section 6.1): docs only, a pure rename, a patch or minor pin
bump, or a defect fix within one owner; anything unproven is design-affecting (ISTQB risk-based
testing). Planted cases: a minor pin bump is mechanical, a major bump is design-affecting, a new
feature in an existing owner is design-affecting, and a docs-only packet whose diff touches a
compose file is re-planned with the fact "tier X from paths Y" and built again at that tier;
nothing is refused. The trigger table is the plugin's default, which `tiers.triggers` in
`.brick-harness/config.json` replaces (P8).
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


def change(tmp_path, before, after, kind="slice"):
    """A repository whose branch turns files ``before`` into ``after`` (path -> text); the tier
    the measurer derives from that diff, and why."""
    repo = tmp_path / "r"
    repo.mkdir(parents=True)
    for path, text in before.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git(repo, "init", "-q", "-b", "main")
    base = commit_all(repo, "base")
    for path in before.keys() - after.keys():
        git(repo, "rm", "-q", path)
    for path, text in after.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    sha = commit_all(repo, "change")
    return bhcore.diff_tier({}, repo, base, sha, kind)


def bump(tmp_path, name, before, after):
    return change(tmp_path, {name: before}, {name: after})


@pytest.mark.parametrize(
    "name, lock",
    [("uv.lock", uv_lock), ("package-lock.json", npm_lock)],
    ids=["python-packaging", "npm-semver"],
)
def test_a_patch_or_minor_pin_bump_stays_mechanical(tmp_path, name, lock):
    tier, why = bump(
        tmp_path, name, lock(httpx="0.28.1", rich="14.0.0"), lock(httpx="0.28.2", rich="14.2.0")
    )
    assert (tier, why) == ("mechanical", ["patch or minor pin bump"])


def test_a_lockfile_that_adds_a_package_is_not_a_pin_bump(tmp_path):
    tier, why = bump(tmp_path, "uv.lock", uv_lock(httpx="0.28.1"), uv_lock(httpx="0.28.1", rich="14.0.0"))
    assert (tier, why) == ("design-affecting", ["uv.lock"])


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


def test_a_new_feature_in_an_existing_owner_is_design_affecting():
    """No fact proves a new feature mechanical, whichever owner it lands in (section 6.1)."""
    paths = ["src/shop/orders/refunds.py", "tests/test_refunds.py"]
    assert bhpacket.tier_of({}, paths, owners=["orders"]) == ("design-affecting", sorted(paths))


def test_a_defect_fix_within_one_owner_is_mechanical_and_unproven_owners_are_not():
    paths = ["src/shop/orders/refunds.py", "tests/test_refunds.py"]
    assert bhpacket.tier_of({}, paths, kind="defect", owners=["orders"]) == (
        "mechanical",
        ["defect fix within owner orders"],
    )
    for owners in ([], ["orders", "billing"]):  # no owner map, or two owners: not proven
        assert bhpacket.tier_of({}, paths, kind="defect", owners=owners)[0] == "design-affecting"
    assert bhpacket.tier_of({}, ["db/schema.sql"], kind="defect", owners=["orders"]) == (
        "design-affecting",
        ["db/schema.sql"],
    )


def test_a_pure_rename_is_mechanical_and_an_edit_with_it_is_not(tmp_path):
    code = "def total(rows):\n    return sum(r['n'] for r in rows)\n"
    assert change(tmp_path / "a", {"src/sum.py": code}, {"src/totals.py": code}) == (
        "mechanical",
        ["pure rename"],
    )
    assert change(tmp_path / "b", {"src/sum.py": code}, {"src/totals.py": code + "# x\n"})[0] == (
        "design-affecting"
    )


def test_the_launch_tier_comes_from_the_declared_paths_and_the_project_may_override_the_triggers():
    assert bhpacket.tier_of({}, ["docs/guide.md"]) == ("mechanical", ["docs"])
    assert bhpacket.tier_of({}, ["db/schema.sql"]) == ("design-affecting", ["db/schema.sql"])
    assert bhpacket.tier_of({}, ["src/app.py"]) == ("design-affecting", ["src/app.py"])
    assert bhpacket.tier_of({}, []) == ("mechanical", [])  # an empty diff changes nothing
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
