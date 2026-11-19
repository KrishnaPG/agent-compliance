"""csv-reader brick: CSV text -> list of row dicts keyed by the header."""

import csv
import io


def read_rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))
