"""The plugin's own tools resolve under the plugin's pins, never under the host project's uv settings
(uv `--no-config`: https://docs.astral.sh/uv/reference/cli/#uv-run--no-config). A project that sets
`[tool.uv] exclude-newer` must not make `bh` unsatisfiable."""

import os
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="needs uv")
def test_bh_runs_in_a_project_whose_uv_config_excludes_every_recent_release(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "toy"\nversion = "0"\n\n[tool.uv]\nexclude-newer = "2000-01-01T00:00:00Z"\n'
    )
    # no UV_OFFLINE here: the pinned set must resolve (cache or index) whatever the project says
    p = subprocess.run(
        [str(PLUGIN / "bin" / "bh"), "rules"], cwd=tmp_path, capture_output=True, text=True, env=os.environ
    )
    assert p.returncode == 0, p.stderr[-600:]
    assert "exclude newer" not in p.stderr
