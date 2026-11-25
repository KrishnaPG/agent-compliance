#!/bin/sh
# Run the acceptance rows against a plugin tree: acceptance/run.sh <tree> [pytest args, e.g. -k b1_ --junitxml=run.xml]
# Add --snapshot-update only by hand, to approve a reviewed snapshot.
tree=$1; shift
cd "$(dirname "$0")/../.." || exit 2
PYTHONPATH=harness/lib exec python3 -m pytest -p atdd_engine.plugin -p no:cacheprovider --snapshot-warn-unused docs/atdd/criteria --tree "$tree" "$@"
