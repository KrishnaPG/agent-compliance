"""d4: the kept packet is read by digest; the clone's copy is a copy; the prompt holds no goal."""

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
from bhcore import HarnessError  # noqa: E402

PACKET = LIB.parent / "acceptance" / "fixtures" / "packet" / "toy_item" / "valid.json"
STUB = LIB.parent / "acceptance" / "keywords" / "stub_claude.py"


def make_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=n",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
        check=True,
    )
    d = tmp_path / bhpacket.PACKETS_DIR
    d.mkdir(parents=True)
    (d / "toy_item.json").write_bytes(PACKET.read_bytes())
    (tmp_path / ".brick-harness" / "config.json").write_text('{"launch": {"refuse_groups": []}}')  # R10 is tested in test_launch_probe


def test_custody_is_read_by_digest_and_a_changed_file_is_refused(tmp_path):
    raw = PACKET.read_bytes()
    digest = bhpacket.custody_store(tmp_path, raw)
    assert bhpacket.custody_read(tmp_path, digest) == raw
    path = bhpacket.custody_path(tmp_path, digest)
    path.chmod(0o644)
    path.write_text("{}")
    with pytest.raises(HarnessError, match="packet-custody"):
        bhpacket.custody_read(tmp_path, digest)


def test_launch_registers_a_copy_and_a_clone_edit_changes_nothing_kept(tmp_path, monkeypatch):
    make_repo(tmp_path)
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(STUB.read_text())
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "model.log"
    monkeypatch.setenv("ATDD_MODEL_LOG", str(log))
    code, out, _ = bhpacket.step("launch_builder", tmp_path, "toy_item")
    assert code == 0
    doc = json.loads(out)
    digest = doc["jobs"][0]["packet_sha256"]
    kept = bhpacket.custody_path(tmp_path, digest)
    clone_copy = (
        next((tmp_path / bhpacket.CLONES_DIR).iterdir()) / bhpacket.PACKETS_DIR / "toy_item.json"
    )
    assert clone_copy.read_bytes() == kept.read_bytes()
    clone_copy.write_text("edited")
    assert bhpacket.custody_read(tmp_path, digest) == PACKET.read_bytes()
    prompt = json.loads(log.read_text().splitlines()[-1])["stdin"]
    assert prompt == bhpacket.LAUNCH_PROMPT and "goal" not in prompt.lower()


def test_custody_is_the_one_identity_of_an_item_and_its_trailer(tmp_path):
    old = PACKET.read_bytes()
    new = json.dumps({**json.loads(old), "goal": "A changed goal."}).encode()
    d_old = bhpacket.custody_store(tmp_path, old)
    assert bhpacket.custody_digest(tmp_path, "toy_item") == d_old
    os.utime(bhpacket.custody_path(tmp_path, d_old), ns=(1, 1))  # the first kept packet is the older one
    d_new = bhpacket.custody_store(tmp_path, new)
    assert bhpacket.custody_digest(tmp_path, "toy_item") == d_new != d_old
    assert bhpacket.custody_digest(tmp_path, "other_item") is None
    assert bhpacket.trailer(json.loads(new), d_new) == f"toy_item@{d_new}"
