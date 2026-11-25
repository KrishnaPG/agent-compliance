"""b9: a builder clone holds only the packet of its own launch, and each builder job records its
outcome from the Claude CLI result (subtype, num_turns) and whether the round changed the tree."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
pytest.importorskip("jsonschema")
import bhpacket  # noqa: E402

PACKET = json.loads((LIB.parent / "acceptance" / "fixtures" / "packet" / "toy_item" / "valid.json").read_text())


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def repo_with_an_earlier_packet(root: Path) -> None:
    """A base commit that, like every plan commit after the first, also holds an earlier item's
    packet, one that sorts before the launched item's."""
    git("init", "-q", "-b", "main", str(root), cwd=root.parent)
    (root / "tests" / "acceptance").mkdir(parents=True)
    (root / "tests" / "acceptance" / "test_a.py").write_text("def test_a(): pass\n")
    (root / "src").mkdir()
    (root / "src" / "m.py").write_text("x = 1\n")
    packets = root / bhpacket.PACKETS_DIR
    packets.mkdir(parents=True)
    (packets / "toy_item.json").write_text(json.dumps(PACKET))
    (packets / "a_built_item.json").write_text(json.dumps({**PACKET, "id": "a_built_item"}))
    (root / ".brick-harness" / "config.json").write_text(json.dumps({"launch": {"refuse_groups": []}}))
    git("add", "-A", "-f", cwd=root)
    git("-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "plan", cwd=root)


def fake_claude(tmp_path: Path, monkeypatch, edit: bool) -> None:
    """A claude that prints one --output-format json result and, when ``edit``, changes a file."""
    result = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "result": "done", "total_cost_usd": 0.01}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    exe.write_text("#!/bin/sh\ncat > /dev/null\n" + ("echo 'x = 2' > src/m.py\n" if edit else "") + f"echo '{json.dumps(result)}'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.parametrize("edit", [False, True])
def test_the_clone_holds_only_its_launch_packet_and_the_job_records_the_round_outcome(tmp_path, monkeypatch, edit):
    root = tmp_path / "r"
    root.mkdir()
    repo_with_an_earlier_packet(root)
    fake_claude(tmp_path, monkeypatch, edit)
    code, out, err = bhpacket.step("launch_builder", root, "toy_item")
    assert code == 0, err
    clone = next((root / bhpacket.CLONES_DIR).iterdir())
    assert [p.name for p in sorted((clone / bhpacket.PACKETS_DIR).glob("*.json"))] == ["toy_item.json"]
    job = json.loads(out)["jobs"][0]
    assert (job["exit_code"], job["subtype"], job["num_turns"], job["tree_changed"]) == (0, "success", 3, edit)
