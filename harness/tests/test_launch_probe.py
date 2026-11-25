"""R10: the builder launch probes the host through the builder's own sandbox (bubblewrap) and reads
the account's groups (id -nG); a failure refuses with a teaching line, and allowAllUnixSockets is
set only when the probe passes with it and fails without it."""

import socket
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import bhbuilder  # noqa: E402

PACKET = {"verifier": {"acceptance_paths": []}}


def settings(tmp_path):
    root, clone = tmp_path / "r", tmp_path / "r" / "clone"
    clone.mkdir(parents=True)
    return clone, bhbuilder.builder_settings(PACKET, root, clone, LIB.parents[1])


def test_a_listed_group_refuses_with_its_teaching_before_any_probe(tmp_path):
    clone, s = settings(tmp_path)
    facts, refusal = bhbuilder.probe_host(s, clone, bhbuilder.launch_policy(None), groups=["dev", "docker"])
    assert "[sandbox-probe]" in refusal and "docker" in refusal and "->" in refusal


def test_the_group_list_is_policy_not_code(tmp_path):
    clone, s = settings(tmp_path)
    policy = bhbuilder.launch_policy({"launch": {"refuse_groups": ["wheel"]}})
    assert bhbuilder.probe_host(s, clone, policy, groups=["docker"])[1] == ""
    assert "wheel" in bhbuilder.probe_host(s, clone, policy, groups=["wheel"])[1]


def test_a_failing_probe_refuses(tmp_path):
    clone, s = settings(tmp_path)
    policy = bhbuilder.launch_policy({"launch": {"probe": ["sh", "-c", "exit 1"]}})
    assert "probe failed" in bhbuilder.probe_host(s, clone, policy, groups=[])[1]


def test_the_default_probe_passes_in_the_builders_sandbox_and_unix_sockets_stay_off(tmp_path):
    clone, s = settings(tmp_path)
    facts, refusal = bhbuilder.probe_host(s, clone, bhbuilder.launch_policy(None), groups=[])
    assert refusal == "" and s["sandbox"]["network"]["allowAllUnixSockets"] is False
    assert (clone / ".brick-harness" / "probe-ok").is_file()


@pytest.mark.parametrize("needs_socket,allowed", [(True, True), (False, False)])
def test_unix_sockets_are_allowed_only_when_the_probe_needs_them(tmp_path, needs_socket, allowed):
    clone, s = settings(tmp_path)
    sock = tmp_path / "host.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(sock))
    try:
        cmd = ["sh", "-c", f"test -S {sock}" if needs_socket else "true"]
        policy = bhbuilder.launch_policy({"launch": {"unix_socket_paths": [str(sock)], "unix_socket_probe": cmd}})
        facts, refusal = bhbuilder.probe_host(s, clone, policy, groups=[])
    finally:
        srv.close()
    assert refusal == "" and s["sandbox"]["network"]["allowAllUnixSockets"] is allowed
    assert facts[0]["kind"] == "sandbox_unix_sockets" and f"={str(allowed).lower()}" in facts[0]["detail"]
