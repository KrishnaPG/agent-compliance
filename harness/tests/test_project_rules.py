"""The project's own rules and the touched owners (section 6.6, QBC-112 and QBC-113), each with a
negative control (QBC-109). A project keeps its rules in standard files: agent instruction files
(AGENTS.md, CLAUDE.md) and decision records (Nygard, MADR); its owners in CODEOWNERS, import-linter
contracts, package exports and OpenAPI documents. The fixtures are generic."""

import bhcore
import bhorch
import bhreview
import bhrules
import pytest
from bhcore import Config
from test_bhorch import fake, orch, run  # noqa: F401  (fake is a fixture)
from test_review_rules import review_input, reviews
from test_rule_selection import conf, toy  # noqa: F401  (toy is a fixture)
from test_toy import commit_all, git

AGENTS = """This codebase is yours: design choices are the agent's call.

# Rules

- Run the tests before you push.
- Business values are policy, never a constant
  in code.
  - a sub-bullet only elaborates

```sh
make test
```
"""
NYGARD = """# 0007 One clock per record

**Decision.** The database is the one time authority; `src/json_writer.py` reads its instant.

**Do not.**
- Call a host clock in a product function.
- Write the clock module from `src/json_writer.py`.

**Why.** Two clocks order ties wrongly.
"""
MADR = """# Use one queue

## Status

Accepted

## Decision Outcome

Chosen option: "one queue", because it keeps ordering.

### Consequences

* Bad, because a second consumer must use the same queue.
"""
RETIRED = "# 0003 Old\n\n## Status\n\nSuperseded by 0007\n\n## Decision\n\nUse two clocks.\n"


def project(repo):
    (repo / "AGENTS.md").write_text(AGENTS)
    d = repo / "docs" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "0007-one-clock.md").write_text(NYGARD)
    (d / "0008-one-queue.md").write_text(MADR)
    (d / "0003-old.md").write_text(RETIRED)
    (repo / "docs" / "notes.md").write_text("- Not a rule file.\n")
    commit_all(repo, "the project's rules")
    return Config(conf(repo))


def lines_of(rules):
    return {r["id"]: r["text"] for r in rules}


def test_qbc_112_project_rules_from_standard_files(toy, capsys):  # noqa: F811
    cfg = project(toy)
    rows = bhrules.project_rule_rows(cfg)
    assert rows["PRJ-AGENTS-1"]["source"] == "AGENTS.md:1"  # a paragraph: the file's grant of authority
    assert rows["PRJ-AGENTS-3"]["text"] == "Business values are policy, never a constant in code."  # continuation joined
    assert not any("sub-bullet" in v["text"] or "make test" in v["text"] for v in rows.values())
    assert rows["PRJ-0007-1"]["text"].startswith("The database is the one time authority")  # the decision line
    assert rows["PRJ-0007-2"] == {
        "text": "Do not call a host clock in a product function.", "full": "Do not call a host clock in a product function.",
        "source": "docs/decisions/0007-one-clock.md:6", "applies": ["always"], "within": "",
    }  # fmt: skip
    assert rows["PRJ-0007-3"]["applies"] == ["path:src/json_writer.py"]  # a path it names
    assert rows["PRJ-0008-1"]["text"].startswith("Chosen option:") and rows["PRJ-0008-2"]["text"].startswith("Bad, because")
    assert not [k for k in rows if k.startswith("PRJ-0003-")]  # a superseded record gives no rule
    assert not [v for v in rows.values() if "notes.md" in v["source"]]  # only standard files
    # the same selection, the same lines: the builder's packet and the review
    worker = lines_of(bhrules.packet_rules(cfg, {"id": "csv-reader", "path": "src/queue_worker.py"}, []))
    writer = lines_of(bhrules.packet_rules(cfg, {"id": "json-writer", "path": "src/json_writer.py"}, []))
    assert writer["PRJ-0007-3"].endswith("(docs/decisions/0007-one-clock.md:7)")  # named path touched: full line
    assert "PRJ-0007-3" in worker and worker["PRJ-0007-3"].endswith("(bh rule PRJ-0007-3)")  # ranks, never excludes
    assert "PRJ-0007-2" in worker  # always
    sel = bhrules.select_rules(cfg, {"id": "csv-reader"}, [], diff={}, base="HEAD", touched=["src/json_writer.py"])
    assert sel["named_by_diff"] == ["PRJ-0007-1", "PRJ-0007-3"] and "PRJ-0007-3" in sel["added_by_diff"]  # the diff names it: full line
    assert bh_rule(capsys, toy, "PRJ-0007-2") == (
        0, "PRJ-0007-2: Do not call a host clock in a product function.\nSource: docs/decisions/0007-one-clock.md:6\nApplies: always\n"
    )
    overlay = toy / "docs" / "agents" / "design-compliance.md"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("# Overlay\n\n## Check opt-outs\n\n- PRJ-0007-2 not-applicable: the product has no clock\n")
    assert "PRJ-0007-2" not in lines_of(bhrules.packet_rules(Config(conf(toy)), {"id": "csv-reader"}, []))  # the overlay opts out
    git(toy, "rm", "-q", "-r", "AGENTS.md", "docs/decisions")
    with pytest.raises(AssertionError):  # negative control: a project with no such files has no project rule
        assert "PRJ-AGENTS-1" in bhrules.project_rule_rows(Config(conf(toy)))


def bh_rule(capsys, repo, rid):
    code = bhorch.main(["rule", "--config", conf(repo), rid])
    return code, capsys.readouterr().out


OPENAPI = """openapi: 3.1.0
info: {title: t, version: '1'}
paths:
  /charges:
    post: {operationId: createCharge, x-owner: billing}
  /pages:
    get: {operationId: listPages, tags: [web]}
"""


def owners_repo(repo):
    """No root pyproject: nested projects in the PyPA src layout, CODEOWNERS, OpenAPI owners and an
    import-linter contract."""
    files = {
        "svc/billing/pyproject.toml": "[project]\nname = 'billing'\n",
        "svc/billing/src/billing/__init__.py": "__all__ = ['charge']\n",
        "svc/billing/src/billing/core.py": "def charge(): ...\n",
        "svc/web/src/web/__init__.py": "__all__ = ['serve']\n",
        "svc/web/src/web/app.py": "def serve(): ...\n",
        "api/openapi.yaml": OPENAPI,
        "CODEOWNERS": "svc/billing/ @pay-team\n",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)


def test_qbc_113_review_input_lists_the_touched_owners_and_interfaces(toy, fake):  # noqa: F811
    owners_repo(toy)
    base = commit_all(toy, "owners")
    got = bhreview.packet_owners(toy, ["svc/billing/src/billing/core.py"], 300)
    assert got == {"owners": ["@pay-team"], "interfaces": ["billing (@pay-team): charge"]}  # CODEOWNERS wins
    web = bhreview.packet_owners(toy, ["svc/web/src/web/app.py"], 300)
    assert web == {"owners": ["web"], "interfaces": ["web (web): serve", "api/openapi.yaml (web): listPages GET /pages"]}
    (toy / ".importlinter").write_text("[importlinter]\nroot_packages = web\n\n[importlinter:contract:one]\nname = one\ntype = independence\nmodules =\n    web.app_core\n")
    (toy / "svc/web/src/web/app_core").mkdir()
    (toy / "svc/web/src/web/app_core/__init__.py").write_text("__all__ = ['render']\n")
    assert bhreview.packet_owners(toy, ["svc/web/src/web/app_core/x.py"], 300)["owners"] == ["app_core"]  # an import-linter boundary
    # with no plan: bh review BASE..HEAD hands the reviewer the owners and interfaces its diff touches
    (toy / "svc/web/src/web/app.py").write_text("def serve():\n    return 'page'\n")
    commit_all(toy, "a change to web")
    fake.spec(outputs_seq={"harness-reviewer": [{"findings": []}]})
    res = run(orch(toy).phase_review(f"{base}..HEAD", None))
    assert res["reviewed"]
    given = review_input(reviews(fake)[-1])
    assert given["owners"] == ["app_core", "web"] and "web (web): serve" in given["interfaces"]
    prompt = (bhcore.PLUGIN_ROOT / "agents" / "harness-reviewer.md").read_text()
    assert "read it with Read, Grep or `git show` before you judge" in prompt  # the reviewer reads outside the diff
    with pytest.raises(AssertionError):  # negative control: before the owner index, a nested src layout had no owner
        assert bhreview.packet_owners(toy, ["docs/readme.md"], 300) == web
