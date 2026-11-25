"""The teaching for an edited lint or test table names the tables from the one protected list
(bhcore.LINT_TABLES, which the presets extend), never a hand-kept copy."""

import bhcore


def test_the_config_lesson_names_every_protected_table():
    prevent = bhcore._lesson("M", "pyproject.toml", [])[3]
    assert all(f"[tool.{t}*]" in prevent for t in bhcore.LINT_TABLES)
    assert len(bhcore._teach(*bhcore._lesson("M", "pyproject.toml", [])[:4])) <= 300
