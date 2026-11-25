"""Keyword-driven acceptance tests (generic: catalog + rows + keyword library, collected by pytest).

The engine knows no project. A project supplies a closed catalog, criteria rows and a keyword library (a
package exposing GIVEN, WHEN and THEN dicts of key -> callable(ctx, **params), optionally AMBIGUOUS(kind, key,
params) -> reason or None). See plugin.py: pytest collects the rows directly, one test per row.
"""

from .runtime import Ctx, FixtureError, KeywordError, Missing  # noqa: F401
