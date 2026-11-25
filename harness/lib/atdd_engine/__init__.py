"""Keyword-driven acceptance test generator (generic: catalog + rows + keyword library -> pytest + manifest).

The engine knows no project. A project supplies a closed catalog, criteria rows and a keyword library (a
package exposing GIVEN, WHEN and THEN dicts of key -> callable(ctx, **params), optionally AMBIGUOUS(kind, key,
params) -> reason or None). See generate.py for the generator and plugin.py for the pytest side.
"""

from .runtime import Ctx, FixtureError, KeywordError, Missing  # noqa: F401
