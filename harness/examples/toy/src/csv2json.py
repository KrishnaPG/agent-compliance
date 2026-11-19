"""csv2json: CSV file in, JSON array out (wires csv-reader and json-writer)."""

import sys

from csv_reader import read_rows
from json_writer import write_rows


def convert(text: str) -> str:
    return write_rows(read_rows(text))


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8", newline="") as f:
        sys.stdout.write(convert(f.read()) + "\n")
