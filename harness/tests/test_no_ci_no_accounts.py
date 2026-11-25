"""P12: the plugin plans nothing around CI or accounts. Its tree has no CI workflow, no acceptance
test needs the network or an account (recorded fixtures only), and the plan names no CI task."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROWS = sorted((ROOT / "docs" / "atdd" / "criteria").glob("*.yaml"))
CI_WORDS = re.compile(r"github actions|\.github/workflows|\bCI (job|task|workflow|pipeline)\b|continuous integration", re.I)


def test_the_tree_has_no_ci_workflow():
    assert not (ROOT / ".github" / "workflows").exists()


def test_no_acceptance_row_needs_the_network_or_an_account():
    live = [
        f"{f.name}:{n}"
        for f in ROWS
        for n, line in enumerate(f.read_text().splitlines(), 1)
        if re.search(r"https?://(?!127\.0\.0\.1|localhost)|\bapi_key\b|\bGITHUB_TOKEN\b|\bgh auth\b", line)
    ]
    assert live == [], f"rows reach out to a live service or account: {live[:5]}"


def test_the_plan_names_no_ci_task():
    plan = (ROOT / "docs" / "plan" / "v2-work-plan.md").read_text().splitlines()
    tasks = [l for l in plan if re.match(r"\s*- \[[ x]\]", l) and CI_WORDS.search(l)]
    assert tasks == []
