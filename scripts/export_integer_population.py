#!/usr/bin/env python3
"""Rewrite population.csv ``children_under_5`` as whole children (integers).

The Meta HRSL raster sums to fractional estimates per commune. This step
converts them to whole counts with ``hanoi_ot.capacity.integerize_counts``
(largest remainder): every commune keeps its floor, and the leftover whole
children go to the communes with the largest fractional part. The total
becomes exactly ``floor(sum)`` = 720,720, equal to the synthetic capacity
total in ``sites_capacity.csv``.

Run after ``scripts/run_pipeline.py`` (which regenerates fractional
estimates) and before ``scripts/make_map.py`` (which refuses fractional
demand). Idempotent: whole inputs pass through unchanged.
"""
import csv
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hanoi_ot.capacity import integerize_counts  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1] / "data/processed/case1"
    path = root / "population.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not rows or not fieldnames or "children_under_5" not in fieldnames:
        raise ValueError("population.csv must have a header and a children_under_5 column")

    values = [Decimal(row["children_under_5"]) for row in rows]
    whole = integerize_counts(values)
    touched = sum(1 for v, n in zip(values, whole) if int(v) != n)
    raw_total = sum(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(fieldnames)
        for row, n in zip(rows, whole):
            row["children_under_5"] = str(n)
            writer.writerow([row[c] for c in fieldnames])
    note = " (already whole)" if touched == 0 else ""
    print(
        f"{path.name}: {len(rows)} communes; total {raw_total} -> {sum(whole)}; "
        f"{touched} communes rounded up{note}"
    )


if __name__ == "__main__":
    main()
