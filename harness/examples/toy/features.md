# Features

## F1 csv2json: convert a CSV file to a JSON array of objects

- Acceptance: a CSV with a header row and N data rows becomes a JSON array of N objects
  keyed by the header; quoted fields with commas and newlines survive; an empty file
  gives `[]`.
- KPIs: all acceptance tests pass; at least 20,000 rows/s end to end on one core
  (stated by the toy's owner as the need; measured by `bench.py`).
