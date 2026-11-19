"""Throughput of one toy item on generated rows; writes {rows_per_s, p50_ms} as JSON.

Imports only the item it measures, so an item not built yet fails only its own bench.
"""

import argparse
import importlib
import json
import statistics
import time

ROWS = 20_000
TEXT = "id,name,city\n" + "".join(f'{i},"name {i}","city, {i % 50}"\n' for i in range(ROWS))


def job(item):
    if item == "csv-reader":
        read_rows = importlib.import_module("csv_reader").read_rows
        return lambda: read_rows(TEXT)
    if item == "json-writer":
        write_rows = importlib.import_module("json_writer").write_rows
        rows = [{"id": str(i), "name": f"name {i}", "city": f"city, {i % 50}"} for i in range(ROWS)]
        return lambda: write_rows(rows)
    convert = importlib.import_module("csv2json").convert
    return lambda: convert(TEXT)


ap = argparse.ArgumentParser()
ap.add_argument("--item", required=True, choices=["csv-reader", "json-writer", "csv2json"])
ap.add_argument("--out", required=True)
a = ap.parse_args()
run = job(a.item)
times = []
for _ in range(5):
    t0 = time.perf_counter()
    run()
    times.append(time.perf_counter() - t0)
p50 = statistics.median(times)
with open(a.out, "w") as f:
    json.dump({"rows": ROWS, "repeats": 5, "rows_per_s": ROWS / p50, "p50_ms": p50 * 1000}, f)
