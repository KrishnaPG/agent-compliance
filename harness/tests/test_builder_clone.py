"""b9: the builder's shared clone, its generated settings, the program's commit and the SG-01 hooks."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
pytest.importorskip("jsonschema")
import bhbuilder  # noqa: E402
import bhpacket  # noqa: E402

PLUGIN = LIB.parents[1]
PACKET = json.loads((LIB.parent / "acceptance" / "fixtures" / "packet" / "toy_item" / "valid.json").read_text())
STUB = LIB.parent / "acceptance" / "keywords" / "stub_claude.py"


def run(*args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})


def make_repo(path: Path) -> str:
    run("git", "init", "-q", "-b", "main", str(path), cwd=path.parent)
    (path / "tests" / "acceptance").mkdir(parents=True)
    (path / "tests" / "acceptance" / "test_a.py").write_text("def test_a(): pass\n")
    (path / "src").mkdir()
    (path / "src" / "m.py").write_text("x = 1\n")
    (path / ".brick-harness" / "packets").mkdir(parents=True)
    (path / ".brick-harness" / "packets" / "toy_item.json").write_text(json.dumps(PACKET))
    run("git", "add", "-A", "-f", cwd=path)
    run("git", "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "base", cwd=path)
    return run("git", "rev-parse", "HEAD", cwd=path).stdout.strip()


def test_clone_is_shared_at_the_base_with_no_remote_and_its_ref_changes_stay_in_it(tmp_path):
    root = tmp_path / "src_repo"
    root.mkdir()
    base = make_repo(root)
    refs = run("git", "for-each-ref", cwd=root).stdout
    clone = root / bhpacket.CLONES_DIR / "toy_item-x"
    bhbuilder.make_clone(root, clone, base)
    assert (clone / ".git" / "objects" / "info" / "alternates").is_file()
    assert run("git", "remote", cwd=clone).stdout.strip() == ""
    assert run("git", "rev-parse", "HEAD", cwd=clone).stdout.strip() == base
    run("git", "update-ref", "-d", "refs/heads/main", cwd=clone)
    assert run("git", "for-each-ref", cwd=root).stdout == refs


def test_the_program_commits_as_itself_with_packet_and_acceptance_trailers(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    base = make_repo(root)
    clone = root / bhpacket.CLONES_DIR / "toy_item-x"
    bhbuilder.make_clone(root, clone, base)
    (clone / "src" / "m.py").write_text("x = 2\n")
    (clone / ".brick-harness").mkdir(exist_ok=True)
    (clone / ".brick-harness" / "state").write_text("not part of the change")
    env = {"GIT_AUTHOR_NAME": "Fixture", "GIT_COMMITTER_NAME": "Fixture"}
    os.environ.update(env)
    try:
        sha = bhbuilder.commit_build(clone, PACKET, "d" * 64)
    finally:
        for k in env:
            os.environ.pop(k)
    log = run("git", "log", "-1", "--format=%an|%cn|%s%n%b", cwd=clone).stdout
    assert log.startswith("bh|bh|feat(toy_item): ")
    assert f"Packet: toy_item@{'d' * 64}" in log and "Acceptance: toy_item-AC1" in log
    assert run("git", "show", "--name-only", "--format=", sha, cwd=clone).stdout.split() == ["src/m.py"]
    assert bhbuilder.commit_build(clone, PACKET, "d" * 64) == sha  # nothing changed: no second commit


def test_settings_scope_the_file_tools_allow_bash_only_through_the_sandbox_and_protect_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BH_ORCHESTRATOR_DIR", str(tmp_path / "orchestrator"))
    root, clone = tmp_path / "r", tmp_path / "r" / bhpacket.CLONES_DIR / "c"
    s = bhbuilder.builder_settings(PACKET, root, clone, PLUGIN, {"excludedCommands": ["docker"], "network": {"x": 1}})
    assert s["permissions"]["allow"] == ["Edit(*)", "Write(*)"]
    assert s["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    assert not any(a.startswith("Bash") for a in s["permissions"]["allow"]) and s["permissions"]["deny"] == []
    sb = s["sandbox"]
    assert sb["autoAllowBashIfSandboxed"] is True and sb["allowUnsandboxedCommands"] is False
    assert sb["excludedCommands"] == ["docker"] and sb["network"] == {"allowAllUnixSockets": False, "x": 1}
    assert "denyRead" not in sb["filesystem"]
    deny = sb["filesystem"]["denyWrite"]
    for p in (clone / "tests" / "acceptance", clone / ".brick-harness" / "packets", root / ".git",
              root / ".brick-harness" / "custody", tmp_path / "orchestrator", PLUGIN):
        assert str(p) in deny
    assert str(root / ".brick-harness") not in deny and str(root) not in deny  # the clone lives under them
    assert sb["filesystem"]["allowWrite"] == [str(clone)]


def hook(name, data, root):
    p = subprocess.run([sys.executable, str(PLUGIN / "hooks" / name)], input=json.dumps({**data, "cwd": str(root)}),
                       capture_output=True, text=True, cwd=root)
    return json.loads(p.stdout)


def test_sg01_refuses_an_acceptance_test_edit_and_notes_the_sandbox_error(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    make_repo(root)
    ev = {"agent_type": "builder", "tool_name": "Edit"}
    hit = hook("sg01.py", {**ev, "tool_input": {"file_path": str(root / "tests/acceptance/test_a.py")}}, root)
    assert hit["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "SG-01" in hit["hookSpecificOutput"]["permissionDecisionReason"]
    assert "hookSpecificOutput" not in hook("sg01.py", {**ev, "tool_input": {"file_path": str(root / "src/m.py")}}, root)
    ro = {"agent_type": "builder", "tool_name": "Bash", "tool_response": {"stderr": "rm: Read-only file system"}}
    assert "SG-01 note" in hook("sg01_note.py", ro, root)["hookSpecificOutput"]["additionalContext"]
    assert "hookSpecificOutput" not in hook("sg01_note.py", {**ro, "tool_response": {"stderr": "ok"}}, root)


def test_launch_uses_the_settings_file_and_no_add_dir_and_never_pre_approves_bash(tmp_path, monkeypatch):
    root = tmp_path / "r"
    root.mkdir()
    make_repo(root)
    (root / ".brick-harness" / "config.json").write_text(json.dumps({"sandbox": {"excludedCommands": ["docker"]}}))
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(STUB.read_text())
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    log = tmp_path / "model.log"
    monkeypatch.setenv("ATDD_MODEL_LOG", str(log))
    code, out, err = bhpacket.step("launch_builder", root, "toy_item")
    assert code == 0, err
    argv = json.loads(log.read_text().splitlines()[-1])["argv"]
    assert "--add-dir" not in argv and "Bash" not in argv[argv.index("--allowedTools") + 1].split(",")
    clone = next((root / bhpacket.CLONES_DIR).iterdir())
    path = Path(argv[argv.index("--settings") + 1])
    assert path == root / bhbuilder.LAUNCH_DIR / f"{clone.name}.settings.json"  # this launch's own file
    settings = json.loads(path.read_text())
    assert settings["sandbox"]["excludedCommands"] == ["docker"]
    assert settings["sandbox"]["filesystem"]["allowWrite"] == [str(clone)]
    assert not path.is_relative_to(clone)  # the builder cannot write its own settings
    assert (clone / ".git" / "objects" / "info" / "alternates").is_file()  # the launch used the clone


def test_two_launches_never_share_a_settings_file(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    make_repo(root)
    a, b = root / bhpacket.CLONES_DIR / "x-1", root / bhpacket.CLONES_DIR / "y-2"
    pa = bhbuilder.write_settings(root, a, {"n": 1})
    pb = bhbuilder.write_settings(root, b, {"n": 2})
    assert pa != pb and json.loads(pa.read_text()) == {"n": 1} and json.loads(pb.read_text()) == {"n": 2}
