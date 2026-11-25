#!/usr/bin/env -S uv run --script --managed-python
# /// script
# requires-python = "==3.14.*"
# dependencies = [
#   "pytest==9.2.0",
#   "syrupy==7.0.3",
#   "check-jsonschema==0.39.0",
#   "PyYAML==6.0.4",
#   "jsonschema==4.26.0",
#   "junitparser==5.0.3",
#   "packaging==26.4",
#   "semver==3.1.1",
#   "mitmproxy==12.3.1",
#   "pathspec==1.1.1",
#   "sqlparse==0.6.1",
#   "tomlkit==0.15.3",
#   "ruamel.yaml==0.19.1",
# ]
# ///
"""The one entry of the plugin's own tests and acceptance rows: pytest under the pinned interpreter and packages.

  harness/run_tests.py [pytest args]          (run from harness/; `uv run --script` resolves the header)

Tools of the test and acceptance layers, pinned here and nowhere else; rows are collected by pytest itself
(lib/atdd_engine/plugin.py).
"""
import sys

import pytest

sys.exit(pytest.main(sys.argv[1:]))
