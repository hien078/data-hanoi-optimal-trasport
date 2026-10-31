"""Whole-children integer handling for Case 1 (capacity and demand).

Capacities are whole children, never fractional people. The split keeps
the capacity total equal to the *floor* of total estimated demand, so
whole children are never stranded by rounding; only the fractional
modeled mass below one child can go unassigned (at most ~1 per commune
of modeled mass, in practice a rounding dust the demo log rounds away).

Population demand follows the same rule: ``integerize_counts`` converts
the per-commune raster estimates to whole children while preserving
``floor(sum)``, so demand and capacity totals match exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
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


def integerize_counts(values: Sequence[float | Decimal]) -> list[int]:
    """Convert nonnegative estimates to whole counts, preserving ``floor(sum)``.

    Largest remainder: every value keeps its floor, and the leftover whole
    part of the total (``floor(sum) - sum(floors)``) is handed out one each
    to the values with the largest fractional part (ties to the lower
    index). The output sums to ``floor(sum(values))`` and every item
    differs from its input by less than 1. Deterministic. Decimal inputs
    are used exactly; floats go through their shortest repr.

    Args:
        values: Nonempty sequence of nonnegative finite estimates.

    Returns:
        List of nonnegative integers with the same length.

    Raises:
        ValueError: On empty input, negative values, or non-finite values.
    """
    if not values:
        raise ValueError("values must be nonempty")
    with localcontext() as ctx:
        ctx.prec = 50
        exact = [v if isinstance(v, Decimal) else Decimal(str(v)) for v in values]
        if any(not d.is_finite() or d < 0 for d in exact):
            raise ValueError("values must be finite and nonnegative")
        floors = [int(d) for d in exact]           # truncation == floor (>= 0)
        fracs = [d - f for d, f in zip(exact, floors)]
        target = int(sum(exact))                  # floor of the exact total
        leftover = target - sum(floors)
        if not 0 <= leftover <= len(floors):      # belt and braces
            raise ValueError("leftover outside [0, n]; inconsistent input")
        order = sorted(range(len(fracs)), key=lambda i: (-fracs[i], i))
        out = list(floors)
        for i in order[:leftover]:
            out[i] += 1
        return out


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
