"""The pre-push review hook, driven by a real ``git push`` through an installed pre-commit hook to a
bare remote (QBC-16, G1): found without the user's PATH, and a new branch's first push reviewed from
its merge-base with the remote's default branch (git's own pre-push sample, ``rev-list --not --remotes``)."""

import os
import subprocess

import bhpresets
from ruamel.yaml import YAML
from test_bhorch import fake  # noqa: F401  (fixture)
from test_review_rules import MAJOR, network_build, reviews
from test_toy import commit_all, git

OLD_ENTRY = "sh -c 'if [ -z \"$PRE_COMMIT_FROM_REF\" ]; then echo old; fi; exit 0'"  # b91b700's


def _no_bh_path():
    return os.pathsep.join(d for d in os.environ["PATH"].split(os.pathsep) if not os.access(os.path.join(d, "bh"), os.X_OK))


def _installed(tmp_path, toy):
    """The toy with the preset's hooks installed and a bare remote that has main."""
    bhpresets.write_precommit(toy, bhpresets.presets()["python"])
    bhpresets.record_plugin_bin(toy)
    subprocess.run(["uvx", "pre-commit@4.7.0", "install"], cwd=toy, check=True, capture_output=True)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(toy, "remote", "add", "origin", str(bare))
    git(toy, "push", "-q", "origin", "main", "--no-verify")
    git(toy, "remote", "set-head", "origin", "main")


def _push(toy, branch, monkeypatch):
    monkeypatch.setenv("PATH", _no_bh_path())
    r = subprocess.run(["git", "push", "origin", branch], cwd=toy, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_new_branch_push_is_reviewed_once_and_bh_is_found_without_path(tmp_path, toy, fake, monkeypatch):  # noqa: F811
    _, base, sha = network_build(toy)
    _installed(tmp_path, toy)
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": [MAJOR]}]})
    code, out = _push(toy, "build", monkeypatch)  # new branch: pre-commit's from-ref is zero or empty
    assert code == 0 and len(reviews(fake)) == 1, out
    assert "[ID-15] json_writer re-checks the token" in out, out
    # negative control: a docs-only new branch runs no review
    git(toy, "checkout", "-q", "-b", "notes", "main")
    (toy / "README.md").write_text("docs only\n")
    commit_all(toy, "docs: a human's note", "README.md")
    code, out = _push(toy, "notes", monkeypatch)
    assert code == 0 and len(reviews(fake)) == 1 and "no review ran" in out, out
    # a branch with nothing new to the remote: no range, no review, never blocks
    git(toy, "branch", "same", "main")
    code, out = _push(toy, "same", monkeypatch)
    assert code == 0 and len(reviews(fake)) == 1, out


def test_a_clone_that_never_ran_setup_is_taught_and_the_push_goes_through(tmp_path, toy, fake, monkeypatch):  # noqa: F811
    _, base, sha = network_build(toy)
    _installed(tmp_path, toy)
    git(toy, "config", "--local", "--unset", "bh.bin")  # a fresh clone: the unversioned record is absent
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    code, out = _push(toy, "build", monkeypatch)
    assert code == 0 and not reviews(fake), out
    assert "bh was not found" in out and "run bh run once in this project from Claude Code" in out, out


def test_setup_re_records_the_plugin_path_and_replaces_an_older_entry(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    git(app, "init", "-q")
    (app / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    p = bhpresets.presets()["python"]
    bhpresets.write_precommit(app, p)
    cfg = app / ".pre-commit-config.yaml"
    old = cfg.read_text().replace(YAML(typ="safe").load(cfg.read_text())["repos"][0]["hooks"][-1]["entry"], OLD_ENTRY)
    cfg.write_text(old)
    assert bhpresets.write_precommit(app, p) == []  # nothing added, the plugin's own hook entry replaced
    hook = [h for r in YAML(typ="safe").load(cfg.read_text())["repos"] for h in r["hooks"] if h["id"] == "bh-review"][0]
    assert "bh.bin" in hook["entry"] and "echo old" not in hook["entry"]
    assert bhpresets.record_plugin_bin(app) is True and bhpresets.record_plugin_bin(app) is False
    git(app, "config", "--local", "bh.bin", "/old/cache/0.9/bin/bh")  # a plugin update moved its directory
    assert bhpresets.record_plugin_bin(app) is True
    assert git(app, "config", "--local", "--get", "bh.bin").strip() == str(bhpresets.BH_BIN)
