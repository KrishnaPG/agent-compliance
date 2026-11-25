"""python -m atdd_engine generate|check --catalog C --criteria DIR --library DIR --fixtures DIR --out DIR"""

from __future__ import annotations

import argparse
import sys

from . import generate as g


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "report":
        from pathlib import Path

        from . import report

        rp = argparse.ArgumentParser(prog="atdd_engine report")
        rp.add_argument("mode")
        rp.add_argument("--junit", required=True)
        rp.add_argument("--manifest", required=True)
        a = rp.parse_args(argv)
        print(report.render(report.outcomes(Path(a.junit), Path(a.manifest))), end="")
        return 0
    ap = argparse.ArgumentParser(prog="atdd_engine")
    ap.add_argument("mode", choices=["generate", "check"])
    for a in ("catalog", "criteria", "library", "fixtures", "out"):
        ap.add_argument("--" + a, required=True)
    a = ap.parse_args(argv)
    try:
        files = g.generate(a.catalog, a.criteria, a.library, a.fixtures, a.out)
    except g.Refusal as e:
        print(e, file=sys.stderr)
        return 2
    if a.mode == "check":
        report = g.check(files, a.out)
        for line in report:
            print(line, file=sys.stderr)
        return 1 if report else 0
    g.write(files, a.out)
    print(f"generated {len(files) - 3} test files, manifest.json, not_generated.json in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
