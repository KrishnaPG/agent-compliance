"""Rule selection scoped to what a change touches (section 6.6): QBC-116, stack facts from every
lock file and manifest, per package, and the imports of each touched file; QBC-117, a fix commit
is a defect. Each with a negative control (QBC-109). The fixture is a monorepo of two packages:
``pkgs/broker`` locks a broker client, ``pkgs/web`` a terminal library; neither file imports one,
so only the package's own dependency files can select the messaging rules."""

import json
import tomllib
from pathlib import Path

import bhcore
import bhorch
import bhpacket
import bhrules
import pytest
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_review_rules import review_input, reviews
from test_toy import commit_all, copy_toy, git
from test_work_tracking import cfg_edit, plan_edit

PLUGIN = Path(__file__).resolve().parents[2]
HOUSE = tomllib.loads((PLUGIN / "catalog" / "rules.toml").read_text())["house"]
MESSAGING = {k for k, v in HOUSE.items() if v["applies"] == ["messaging"]}
DEFECT = {k for k, v in HOUSE.items() if v["applies"] == ["defect"]}


def lock(*pkgs):
    return "version = 1\n" + "".join(f'\n[[package]]\nname = "{n}"\nversion = "{v}"\n' for n, v in pkgs)


@pytest.fixture
def mono(tmp_path):
    repo = tmp_path / "mono"
    copy_toy(repo)
    for name, deps, locked in (("broker", [], [("nats-py", "2.9.0")]), ("web", ["rich>=13"], [("rich", "13.9.4")])):
        d = repo / "pkgs" / name
        d.mkdir(parents=True)
        (d / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "1"\ndependencies = {json.dumps(deps)}\n')
        (d / "uv.lock").write_text(lock((name, "1"), *locked))  # the broker client is only in the lock file
        (d / "app.py").write_text("def handle(msg):\n    return msg\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "toy")
    cfg_edit(repo, standards={}, review={"triggers": ["pkgs/**"]})  # no paths.lockfiles: found with no setup (G6)
    return repo


def conf(repo):
    return str(repo / ".brick-harness" / "config.json")


def change(repo, base, path, subject, text="def handle(msg):\n    return msg or None\n"):
    """A commit on a new branch from ``base`` that changes ``path``; returns its sha."""
    git(repo, "checkout", "-q", "-B", f"c{abs(hash((path, subject))) % 10**6}", base)
    (repo / path).write_text(text)
    return commit_all(repo, subject).strip()


def selected(repo, base, sha):
    sel = json.loads(bhrules.rules_cmd(conf(repo), None, diff=[base, sha]))
    return sel, {r["id"] for r in sel["chosen"] + sel["more"]}


def test_qbc_116_a_sub_package_lock_file_selects_its_rules_for_that_package_only(mono, fake):  # noqa: F811
    base = git(mono, "rev-parse", "HEAD").strip()
    broker = change(mono, base, "pkgs/broker/app.py", "feat(broker): pass the message through")
    sel, ids = selected(mono, base, broker)
    assert "HO-01" in ids and MESSAGING <= ids  # the sub-package's lock file, read with no setup
    assert any("pkgs/broker/uv.lock" in e for e in sel["tags"]["stack"]["messaging"])
    web = change(mono, base, "pkgs/web/app.py", "feat(web): pass the message through")
    sel, ids = selected(mono, base, web)
    assert not ids & MESSAGING and "messaging" not in sel["tags"]["stack"]  # negative control: another package
    assert "HO-01" in {r["id"] for r in bhrules.project_rules(bhcore.Config(conf(mono)))}  # only a whole-project job takes all

    # the review judges exactly these lines: the touched package's, at most packet_rules in full
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": []}, {"findings": []}]})
    cfg = bhcore.Config(conf(mono))
    rows = bhrules.rule_rows(cfg)
    for sha, has in ((broker, True), (web, False)):
        git(mono, "checkout", "-q", sha)
        res = run(orch(mono).phase_review(f"{base}..{sha}", None))
        assert res["reviewed"] and ("HO-01" in res["rules"]) is has
        given = review_input(reviews(fake)[-1])["rules"]
        full = [r for r in given if r["message"] != bhrules.title(rows, r["id"])]
        assert len(full) <= cfg.limit("packet_rules") and (len(given) > len(full)) is has  # QBC-105 (iv) on the whole input

    # an item's packet: the stack of the package its path is in
    plan_edit(mono, "bricks.json", lambda d: (d["bricks"][0].update(path="pkgs/broker/"), d["bricks"][1].update(path="pkgs/web/app.py")))
    ids = {i: {r["id"] for r in bhpacket.plan_packet(bhcore.Config(conf(mono)), i)["verifier"]["rules"]} for i in ("csv-reader", "json-writer")}
    assert "HO-01" in ids["csv-reader"] and "HO-01" not in ids["json-writer"]

    # a touched file's imports, whole: a body edit of a file that already uses a broker
    head = git(mono, "rev-parse", "HEAD").strip()
    uses = change(mono, head, "pkgs/web/app.py", "feat(web): consume", "import nats\n\n\ndef handle(msg):\n    return msg\n")
    edit = change(mono, uses, "pkgs/web/app.py", "feat(web): consume more", "import nats\n\n\ndef handle(msg):\n    return msg or None\n")
    assert "messaging" in bhrules.diff_tags(bhcore.Config(conf(mono)), uses, edit)
    plain = change(mono, head, "pkgs/web/app.py", "feat(web): plain", "def handle(msg):\n    return [msg]\n")
    assert "messaging" not in bhrules.diff_tags(bhcore.Config(conf(mono)), head, plain)  # negative control

    # negative control: without the lock file's entry the broker package selects no messaging rule
    git(mono, "checkout", "-q", "-B", "nolock", base)
    (mono / "pkgs" / "broker" / "uv.lock").write_text(lock(("broker", "1")))
    nolock = commit_all(mono, "chore(broker): drop the client").strip()
    again = change(mono, nolock, "pkgs/broker/app.py", "feat(broker): pass it on")
    assert not selected(mono, nolock, again)[1] & MESSAGING


def test_qbc_117_a_fix_commit_is_a_defect(mono):
    base = git(mono, "rev-parse", "HEAD").strip()
    cfg = bhcore.Config(conf(mono))
    for subject in ("fix(web): keep the message", "fix!: keep the message", "fix: keep the message"):
        sha = change(mono, base, "pkgs/web/app.py", subject)
        assert "defect" in bhrules.diff_tags(cfg, base, sha), subject
        assert DEFECT & set(selected(mono, base, sha)[1])  # the root-cause rule (NO-12) applies
    for subject in ("feat(web): fix the message", "fixup: keep it", "prefix: keep it", "docs: keep it\n\nfix: in the body"):
        sha = change(mono, base, "pkgs/web/app.py", subject)
        assert "defect" not in bhrules.diff_tags(cfg, base, sha), subject  # negative control
        assert not DEFECT & set(selected(mono, base, sha)[1]), subject
    assert "NO-12" in DEFECT
    sel = bhrules.select_rules(cfg, {"id": "d", "kind": "defect"}, [])
    assert "defect" in sel["tags"]["contract"]  # a defect item, with no commit yet
