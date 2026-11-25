"""QBC-16: the project's one test entry runs the lint. The presets close the inferred `test` recipe
with the preset's lint line (no second recipe), once; a project with no recipe gets one."""

import bhpresets

PY = bhpresets.presets()["python"]


def test_the_test_recipe_ends_with_the_lint_once(tmp_path):
    (tmp_path / "justfile").write_text("fmt:\n    ruff format\n\ntest:\n  uv run --frozen pytest -q\n\nother:\n  true\n")
    assert bhpresets.write_recipe(tmp_path, PY) == PY["lint"]
    body = (tmp_path / "justfile").read_text().split("test:\n")[1].split("\n\n")[0].splitlines()
    assert body == ["  uv run --frozen pytest -q", f"  {PY['lint']}"]
    assert bhpresets.write_recipe(tmp_path, PY) is None  # a second run changes nothing


def test_a_project_without_a_recipe_gets_one_entry(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "p"\nversion = "0"\n[tool.pytest.ini_options]\n')
    bhpresets.write_recipe(tmp_path, PY)
    assert (tmp_path / "justfile").read_text() == f"test:\n    {PY['run']} pytest\n    {PY['lint']}\n"
