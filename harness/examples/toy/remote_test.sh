#!/bin/sh
# Stand-in for a test command that runs elsewhere (another host, a VM, a CI runner) and
# copies its JUnit XML back to {out}. Here "elsewhere" is a separate work directory.
# Usage: sh remote_test.sh ITEM OUT
item=$1
out=$2
remote="$out.remote"
mkdir -p "$remote" "$out"
PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider "tests/$item" --junitxml "$remote/junit.xml"
code=$?
[ -n "$BH_SKIP_COPY" ] || cp "$remote/junit.xml" "$out/junit.xml"
exit $code
