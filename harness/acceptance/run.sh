#!/bin/sh
# Run the acceptance rows against a plugin tree: acceptance/run.sh <tree> [pytest args, e.g. -k b1_ --junitxml=run.xml]
# Add --snapshot-update only by hand, to approve a reviewed snapshot.
# The interpreter and packages come from harness/run_tests.py's PEP 723 header, the same for every machine.
# R10: a builder account is outside the docker group, and the launch probe refuses one inside it. On
# a host whose account is in that group, the rows run as the same account with its supplementary
# groups dropped (util-linux `setpriv --clear-groups`, least privilege), with the environment kept.
if [ -z "$ATDD_GROUPS_CLEARED" ] && id -nG | tr ' ' '\n' | grep -qx docker && sudo -n true 2>/dev/null; then
  envfile=$(mktemp) && ATDD_GROUPS_CLEARED=1 && export ATDD_GROUPS_CLEARED && export -p > "$envfile"
  exec sudo -n setpriv --reuid="$(id -u)" --regid="$(id -g)" --clear-groups \
    /bin/sh -c '. "$1"; shift; exec /bin/sh "$@"' sh "$envfile" "$0" "$@"
fi
tree=$1; shift
cd "$(dirname "$0")/../.." || exit 2
PYTHONPATH=harness/lib exec uv run --script --no-config --managed-python harness/run_tests.py -p atdd_engine.plugin -p no:cacheprovider --snapshot-warn-unused docs/atdd/criteria --tree "$tree" "$@"
