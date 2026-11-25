"""P5: a failed install teaches with the tool's own error line, whole, however long the output after it."""

import bhcore

UV = (
    "env_setup: `uv sync --locked` exit 1: Resolved 9 packages in 3ms\n"
    "error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided. To update the lockfile, run `uv lock`.\n"
    "  cause: Requirements for `toy==0.1.0` differ: dependencies: ['six'] vs []\n"
)


def test_the_error_line_is_quoted_whole_with_its_cause_after_it():
    assert bhcore._error_line(UV).startswith("error: The lockfile at `uv.lock` needs to be updated")


def test_output_with_no_error_line_gives_its_last_line():
    assert bhcore._error_line("step one\nnpm ERR! code 1\n") == "npm ERR! code 1"
