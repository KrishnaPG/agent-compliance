"""field: a hook's output fields are Claude Code's, which it reads inside hookSpecificOutput."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import then  # noqa: E402


def ctx_with(doc):
    run = SimpleNamespace(kind="hook", extra={"hook_json": doc}, json=doc)
    return SimpleNamespace(last=run, state={})


def test_additional_context_is_found_inside_hook_specific_output():
    doc = {
        "facts": [],
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "x"},
    }
    out = then.source(ctx_with(doc), "hook_output")
    assert out["additionalContext"] == "x" and out["facts"] == []


def test_a_hook_that_adds_no_context_has_none():
    assert "additionalContext" not in then.source(ctx_with({"facts": []}), "hook_output")
