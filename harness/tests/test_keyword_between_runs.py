"""bh `between_runs`: the plant lands after the first run and before the second; $measure_out follows the config."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "acceptance" / "keywords"))
import given  # noqa: E402
import when  # noqa: E402
from then import subst  # noqa: E402


def test_the_plant_is_applied_between_the_two_runs(monkeypatch):
    events = []
    monkeypatch.setattr(when, "execute", lambda ctx, argv, stdin="", env_extra=None: events.append("run") or SimpleNamespace(first=None))
    monkeypatch.setattr(when, "digests", lambda ctx: {})
    monkeypatch.setattr(given, "given_planted", lambda ctx, plant, **kw: events.append((plant, kw["where"])))
    ctx = SimpleNamespace(state={})
    when._run_many(ctx, ["bh"], 1, True, between_runs={"planted": "p", "where": "plan_commit"})
    assert events == ["run", ("p", "plan_commit"), "run"]


def test_without_between_runs_both_runs_see_identical_inputs(monkeypatch):
    events = []
    monkeypatch.setattr(when, "execute", lambda ctx, argv, stdin="", env_extra=None: events.append("run") or SimpleNamespace(first=None))
    monkeypatch.setattr(when, "digests", lambda ctx: {})
    when._run_many(SimpleNamespace(state={}), ["bh"], 1, True)
    assert events == ["run", "run"]


def test_measure_out_is_the_default_unless_the_config_sets_it(tmp_path):
    ctx = SimpleNamespace(state={"repo": tmp_path})
    assert subst(ctx, "$measure_out/*/*-*") == ".brick-harness/out/*/*-*"
    (tmp_path / ".brick-harness").mkdir()
    (tmp_path / ".brick-harness" / "config.json").write_text(json.dumps({"paths": {"measure_out": "build/o"}}))
    assert subst(ctx, "$measure_out/x") == "build/o/x"
