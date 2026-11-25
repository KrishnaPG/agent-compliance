#!/bin/sh
# Run the acceptance rows against a plugin tree: acceptance/run.sh <tree> [pytest args, e.g. -k b1_ --junitxml=run.xml]
# Add --snapshot-update only by hand, to approve a reviewed snapshot.
# The interpreter and packages come from harness/run_tests.py's PEP 723 header, the same for every machine.
tree=$1; shift
cd "$(dirname "$0")/../.." || exit 2
PYTHONPATH=harness/lib exec uv run --script --managed-python harness/run_tests.py -p atdd_engine.plugin -p no:cacheprovider --snapshot-warn-unused docs/atdd/criteria --tree "$tree" "$@"
