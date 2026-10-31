"""Integer synthetic capacity handling for Case 1.

Capacities are whole children, never fractional people. Rounding must
preserve the total (capacity sum == estimated demand sum) so the greedy
demo allocation never strands children by an artifact of rounding.
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
    if frame["capacity"].isna().any():
        raise ValueError(f"{csv_path}: capacity has missing values")
    if (frame["capacity"] < 0).any():
        raise ValueError(f"{csv_path}: capacity has negative values")
    if not (frame["capacity"] % 1 == 0).all():
        raise ValueError(f"{csv_path}: capacity must be integers, got fractions")
    if frame["facility_id"].duplicated().any():
        raise ValueError(f"{csv_path}: duplicated facility_id values")
    series = frame["capacity"].astype("int64")
    series.index = frame["facility_id"].astype(str)
    return series
