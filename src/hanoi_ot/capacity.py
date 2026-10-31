"""Integer synthetic capacity handling for Case 1.

Capacities are whole children, never fractional people. The split keeps
the capacity total equal to the *floor* of total estimated demand, so
whole children are never stranded by rounding; only the fractional
modeled mass below one child can go unassigned (at most ~1 per commune
of modeled mass, in practice a rounding dust the demo log rounds away).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_REQUIRED_COLUMNS = ("facility_id", "capacity")


def largest_remainder_split(total: int, n: int) -> list[int]:
    """Split ``total`` into ``n`` integers whose sum is exactly ``total``.

    Every part gets ``total // n``; the first ``total % n`` parts get one
    more. Deterministic in index order.

    Args:
        total: Nonnegative amount to split.
        n: Number of parts (positive).

    Returns:
        List of ``n`` nonnegative integers summing to ``total``.

    Raises:
        ValueError: If ``n <= 0`` or ``total < 0``.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if total < 0:
        raise ValueError(f"total must be nonnegative, got {total}")
    base, remainder = divmod(total, n)
    return [base + (i < remainder) for i in range(n)]


def load_site_capacities(csv_path: Path) -> pd.Series:
    """Load ``sites_capacity.csv`` as an int Series indexed by str IDs.

    Args:
        csv_path: Path to a CSV with ``facility_id,capacity`` columns.

    Returns:
        Series of int64 capacities, index of string facility IDs.

    Raises:
        ValueError: On missing columns, duplicated IDs, non-integer or
            negative capacities, or missing values.
    """
    frame = pd.read_csv(csv_path, dtype={"facility_id": str})
    missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{csv_path}: missing columns {missing}")
    # Coerce first: non-numeric cells become NaN and hit the ValueError
    # below instead of blowing up the comparisons with a TypeError.
    capacity = pd.to_numeric(frame["capacity"], errors="coerce")
    if capacity.isna().any():
        raise ValueError(f"{csv_path}: capacity has missing or non-numeric values")
    if (capacity < 0).any():
        raise ValueError(f"{csv_path}: capacity has negative values")
    if not (capacity % 1 == 0).all():
        raise ValueError(f"{csv_path}: capacity must be integers, got fractions")
    if frame["facility_id"].duplicated().any():
        raise ValueError(f"{csv_path}: duplicated facility_id values")
    series = capacity.astype("int64")
    series.index = frame["facility_id"].astype(str)
    return series
