"""CSV files, with one encoding policy.

Every CSV Painter writes is UTF-8 with a BOM (so Excel shows accented names
correctly) and is written atomically. Reading accepts files with or
without a BOM.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from painter.storage.atomic import atomic_write

ENCODING = "utf-8-sig"

CsvError = csv.Error


def write_csv(path: Path, columns: Sequence[str], rows: Iterable) -> Path:
    """Write a header and rows. Rows are dicts keyed by column (missing keys
    are left blank, unknown keys are an error) or sequences in column order."""
    rows = list(rows)
    with atomic_write(path, "w", newline="", encoding=ENCODING) as fh:
        if rows and not isinstance(rows[0], dict):
            w = csv.writer(fh)
            w.writerow(columns)
            w.writerows(rows)
        else:
            w = csv.DictWriter(fh, fieldnames=list(columns), restval="")
            w.writeheader()
            w.writerows(rows)
    return Path(path)


def read_table(path: Path) -> list[list[str]]:
    """Every row, header included, as lists of strings."""
    with open(path, newline="", encoding=ENCODING) as fh:
        return list(csv.reader(fh))


def read_records(path: Path) -> tuple[list[str], list[dict]]:
    """(column names, rows as dicts keyed by column name)."""
    with open(path, newline="", encoding=ENCODING) as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows
