"""The plugin's keyword library: one implementation per catalog key, written once from its passes_when.

GIVEN, WHEN, THEN map a catalog key to callable(ctx, **params). AMBIGUOUS(kind, key, params) names a row part
the catalog does not define well enough to implement without guessing; the row is then skipped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from given import GIVEN  # noqa: E402,F401
from support import CONTRACT, catalog_entry  # noqa: E402
from then import THEN  # noqa: E402,F401
from when import BEFORE_WHEN, WHEN  # noqa: E402,F401


def AMBIGUOUS(kind, key, params):
    if (kind, key) == ("then", "same_result"):
        named = catalog_entry("then", "same_result")["results"]
        if params.get("a") not in named or params.get("b") not in named:
            return "the result ids it compares (%s, %s) are named nowhere in the catalog" % (params.get("a"), params.get("b"))
        return None
    if (kind, key) == ("then", "threshold") and params.get("metric") not in {**CONTRACT["metrics"], **catalog_entry("then", "threshold")["metrics"]}:
        return "metric %s has no definition of how it is measured" % params.get("metric")
    return None
