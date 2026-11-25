"""`builder_action` runs the plugin's tool hooks as Claude Code does (hooks.json: the matcher is a regex
on the tool name, the event JSON on stdin): a PreToolUse deny refuses an Edit or Write `by: hook`
before the permission rules see it, and a Bash call's PostToolUse hooks get its tool_response, so
their notes are the row's hook output."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import when  # noqa: E402

DENY = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[SG-01] protected"}}


def plugin_tree(tmp_path: Path) -> Path:
    """A tree whose PreToolUse hook on Edit|Write denies, and whose PostToolUse hook on Bash echoes
    the tool_response it was given as its note."""
    tree = tmp_path / "plugin"
    (tree / "hooks").mkdir(parents=True)
    (tree / "hooks" / "deny.sh").write_text(f"cat > /dev/null\necho '{json.dumps(DENY)}'\n")
    (tree / "hooks" / "note.py").write_text(
        "import json, sys\nd = json.load(sys.stdin)\n"
        "print(json.dumps({'hookSpecificOutput': {'hookEventName': d['hook_event_name'], 'additionalContext': d['tool_response']['stderr']}}))\n"
    )
    hooks = {
        "PreToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/deny.sh"'}]}],
        "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": f'{sys.executable} "${{CLAUDE_PLUGIN_ROOT}}/hooks/note.py"'}]}],
    }
    (tree / "hooks" / "hooks.json").write_text(json.dumps({"hooks": hooks}))
    return tree


def launched(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    repo = tmp_path / "repo"
    clone = repo / ".brick-harness" / "clones" / "item-abc-def"
    (clone / "tests" / "acceptance").mkdir(parents=True)
    (clone / "tests" / "acceptance" / "test_a.py").write_text("def test_a(): pass\n")

    def launch(ctx, step, item=None, rerun=False):
        (repo / ".brick-harness" / "launch").mkdir(parents=True, exist_ok=True)
        (repo / ".brick-harness" / "launch" / f"{clone.name}.settings.json").write_text(json.dumps({"permissions": {"allow": ["Edit(*)"], "deny": []}}))
        return SimpleNamespace(stdout="{}", exit_code=0)

    monkeypatch.setattr(when, "when_program_step", launch)
    (tmp_path / "kept.json").write_text("{}\n")  # the orchestrator's kept packet
    pk = {"id": "item", "orchestrator": tmp_path / "kept.json"}
    return SimpleNamespace(state={"repo": repo, "packet": pk, "env": dict(os.environ)}, work=tmp_path, tree=plugin_tree(tmp_path))


def test_a_pretooluse_deny_refuses_the_edit_by_hook_and_leaves_the_file(tmp_path, monkeypatch):
    ctx = launched(tmp_path, monkeypatch)
    run = when.when_builder_action(ctx, "Edit", "edit", "acceptance_test")
    assert (run.extra["refused"], run.extra["by"], run.extra["changed"]) == (True, "hook", False)
    assert run.extra["message"] == "[SG-01] protected" and run.extra["hook_json"] == [DENY]


def test_a_bash_calls_posttooluse_hooks_get_its_tool_response(tmp_path, monkeypatch):
    ctx = launched(tmp_path, monkeypatch)
    clone = tmp_path / "repo" / ".brick-harness" / "clones" / "item-abc-def"
    outs, deny = when._tool_hooks(ctx, "PostToolUse", "Bash", clone, {"command": "rm x"}, {"stdout": "", "stderr": "rm: Read-only file system"})
    assert deny is None and outs[0]["hookSpecificOutput"]["additionalContext"] == "rm: Read-only file system"
    assert when._tool_hooks(ctx, "PostToolUse", "Edit", clone, {"file_path": "x"}) == ([], None)  # the matcher is a regex on the tool name


def test_file_tool_rules_match_as_claude_code_anchors_them(tmp_path):
    """Edit rules cover Write; a bare pattern is relative to the working directory, so `Edit(*)`
    allows a write in the clone and never one outside it (dontAsk then denies it)."""
    clone = tmp_path / "clone"
    assert when._pattern_match("Edit(*)", "Write", str(clone / "src" / "a.py"), clone)
    assert not when._pattern_match("Edit(*)", "Write", str(tmp_path / "outside" / "t.txt"), clone)
    assert not when._pattern_match("Write(*)", "Write", str(clone / "a.py"), clone)
    assert when._pattern_match(f"Edit(/{tmp_path}/outside/*)", "Write", str(tmp_path / "outside" / "t.txt"), clone)

