"""`builder_action`: the builder acts only inside a launch (R5). The keyword launches through the
program's one launch path and acts in that launch's clone under that launch's own settings file
(.brick-harness/launch/<clone>.settings.json); the launch's result JSON is the run's."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import when  # noqa: E402


def test_the_action_runs_in_the_launch_clone_under_its_settings(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    clone = repo / ".brick-harness" / "clones" / "item-abc-def"
    (clone / ".brick-harness" / "packets").mkdir(parents=True)
    (clone / ".brick-harness" / "packets" / "item.json").write_text("{}\n")
    settings = {"permissions": {"allow": ["Edit(*)"], "deny": []}}
    launched = []

    def launch(ctx, step, item=None, rerun=False):
        launched.append((step, item))
        (repo / ".brick-harness" / "launch").mkdir(parents=True, exist_ok=True)
        (repo / ".brick-harness" / "launch" / f"{clone.name}.settings.json").write_text(json.dumps(settings))
        return SimpleNamespace(stdout=json.dumps({"schema_version": "1", "command": "step", "jobs": [{"packet_sha256": "s"}]}), exit_code=0)

    monkeypatch.setattr(when, "when_program_step", launch)
    ctx = SimpleNamespace(state={"repo": repo, "packet": {"id": "item"}}, work=tmp_path)
    run = when.when_builder_action(ctx, "Edit", "edit", "clone_packet")
    assert launched == [("launch_builder", "item")]
    assert run.extra["refused"] is False and run.extra["changed"]
    assert run.json["jobs"][0]["packet_sha256"] == "s"
