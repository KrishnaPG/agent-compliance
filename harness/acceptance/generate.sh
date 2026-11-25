#!/bin/sh
# Regenerate (or `check`) the acceptance tests from the catalog and criteria rows. No agent edits the output.
cd "$(dirname "$0")/../.." || exit 2
PYTHONPATH=harness/lib exec python3 -m atdd_engine "${1:-generate}" \
  --catalog docs/atdd/catalog.yaml --criteria docs/atdd/criteria \
  --library harness/acceptance/keywords --fixtures harness/acceptance/fixtures \
  --out harness/acceptance/generated
