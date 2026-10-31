#!/usr/bin/env python3
"""Export explicitly synthetic Case 1 capacities; never modify real facility data."""
import csv
import sys
from decimal import Decimal, localcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hanoi_ot.capacity import largest_remainder_split  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1] / "data/processed/case1"
    with (root / "population.csv").open(newline="") as stream:
        demand = [Decimal(row["children_under_5"]) for row in csv.DictReader(stream)]
    with (root / "facilities.csv").open(newline="") as stream:
        ids = [row["facility_id"] for row in csv.DictReader(stream)]
    if not demand or any(not value.is_finite() or value < 0 for value in demand):
        raise ValueError("Demand must be nonempty, finite and nonnegative")
    if not ids or any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Facility IDs must be nonempty and unique")
    with (root / "distance_matrix.csv").open(newline="") as stream:
        if next(csv.reader(stream))[1:] != ids:
            raise ValueError("Facility order differs from distance matrix")
    with localcontext() as context:
        context.prec = 50
        total = sum(demand)
        if total <= 0:
            raise ValueError("Total demand must be positive")
        # ponytail: uniform test allocation only; replace with verified capacities for real use.
        # Whole children only: floor the total so capacity never exceeds demand,
        # then split exactly (largest remainder) so the sum is preserved.
        total_children = int(total)
        capacities = largest_remainder_split(total_children, len(ids))
        assert all(value >= 0 for value in capacities) and sum(capacities) == total_children
        output = root / "sites_capacity.csv"
        with output.open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["facility_id", "capacity", "capacity_source", "capacity_unit"])
            writer.writerows((fid, value, "synthetic", "children_equivalent_per_model_allocation")
                            for fid, value in zip(ids, capacities))
        print(f"{output.name}: {len(ids)} synthetic integer capacities; total={total_children}")


if __name__ == "__main__":
    main()
