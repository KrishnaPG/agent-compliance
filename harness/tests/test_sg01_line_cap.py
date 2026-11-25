"""SG-01's refusal lines keep the teaching shape within the cap for any path length: the cap cuts the path, never
what is wrong, the right way or how to prevent it (P5, QBC-43)."""

import json
import subprocess
import sys
from pathlib import Path

from atdd_engine import teaching

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "sg01.py"


def _refusal(clone, target):
    (clone / ".brick-harness" / "packets").mkdir(parents=True)
    (clone / ".brick-harness" / "packets" / "item.json").write_text(
        json.dumps({"verifier": {"acceptance_paths": ["tests/*"]}})
    )
    data = {
        "cwd": str(clone),
        "agent_type": "builder",
        "tool_name": "Write",
        "tool_input": {"file_path": str(target)},
    }
    p = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_write_to_a_deep_packet_path_outside_the_clone_is_one_capped_teaching_line(tmp_path):
    target = tmp_path / ("orchestrator-" * 12) / ".brick-harness" / "custody" / (64 * "a" + ".json")
    msg = _refusal(tmp_path / "clone", target)
    assert (
        teaching.match(
            msg,
            "packet is orchestrator-owned",
            "the orchestrator writes the packet",
            "file tools are scoped to the clone",
        )
        is None
    )
    assert (
        teaching.match(
            msg,
            "path is outside the clone",
            "write only inside the clone",
            "file tools are scoped to the clone",
        )
        is None
    )


def test_an_edit_to_a_deep_protected_test_is_one_capped_teaching_line(tmp_path):
    clone = tmp_path / "clone"
    msg = _refusal(clone, clone / "tests" / (("deep_" * 60) + ".py"))
    assert (
        teaching.match(
            msg,
            "acceptance test is protected (SG-01)",
            "ask the orchestrator to change it in the plan",
            "tests sit in protected paths",
        )
        is None
    )
