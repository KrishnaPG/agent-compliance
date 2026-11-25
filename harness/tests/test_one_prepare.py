"""One toolchain install for every measurement path (bhcore.prepare): the item measurement after a
merge (``measure_item``) installs from the lockfile exactly as the packet measurement
(``measure_ref``) does, so a build met by one is never unmet by the other for a missing package."""

import json

import bhcore
import bhinfer
import pytest
from test_toy import commit_all, toy  # noqa: F401  (the toy project fixture)

LOCK = "deps.lock"  # a lockfile row of our own: the real installs need the network


@pytest.fixture
def locked(toy, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bhinfer, "PREPARE", ((LOCK, "touch .bh-installed"),))
    cfgp = toy / ".brick-harness" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["commands"]["test"]["run"] = "test -f .bh-installed && " + cfg["commands"]["test"]["run"]
    cfg["commands"].pop("env_setup", None)  # no configured install: the lockfile row is the install
    cfgp.write_text(json.dumps(cfg, indent=1))
    (toy / LOCK).write_text("")
    commit_all(toy, "lockfile")
    return bhcore.Config(cfgp)


def test_the_item_measurement_installs_from_the_lockfile(locked):
    r = bhcore.measure(locked, [("csv-reader", "HEAD")])["items"]["csv-reader"]
    assert [x["name"] for x in r["runs"]][:2] == ["env_setup", "test"]
    assert not [e for e in r["errors"] if e.startswith("test:")]


def test_a_failed_install_is_one_env_setup_error_on_every_path(locked, monkeypatch):
    monkeypatch.setattr(bhinfer, "PREPARE", ((LOCK, "exit 7"),))
    r = bhcore.measure(locked, [("csv-reader", "HEAD")])["items"]["csv-reader"]
    assert r["status"] == "unmet" and r["errors"][0].startswith("env_setup: `exit 7` exit 7")
    res = bhcore.measure_ref(locked)
    assert [f["detail"] for f in res["facts"] if f["kind"] == "gap"][0] == "env_setup"
