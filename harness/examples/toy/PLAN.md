# Plan

## Build order

1. csv-reader: CSV text to row objects (contract in .brick-harness/contracts).
2. json-writer: row objects to a JSON array.
3. csv2json: the CLI that wires both; acceptance and KPI in [features](features.md#f1-csv2json-convert-a-csv-file-to-a-json-array-of-objects).

## Status

csv-reader and the csv2json wiring are written; json-writer is not built yet (its contract,
targets and tests are in place).
