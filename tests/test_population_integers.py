"""Tests for whole-children demand: integerize_counts + committed CSVs."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from hanoi_ot.capacity import integerize_counts, load_site_capacities

REPO = Path(__file__).resolve().parents[1]
CASE1 = REPO / "data" / "processed" / "case1"


def test_integerize_counts_preserves_floor_total():
    values = [1605.820458, 2451.052552, 1478.121018, 1543.6447]
    out = integerize_counts(values)
    assert all(isinstance(v, int) for v in out)
    assert sum(out) == 7078                          # floor(7078.638728)
    # Largest fractional part (0.82...) gets the single leftover child.
    assert out == [1606, 2451, 1478, 1543]


def test_integerize_counts_each_output_within_one():
    values = [0.13, 2.71, 99.5, 7.999]
    out = integerize_counts(values)
    for v, n in zip(values, out):
        assert abs(v - n) < 1
    assert sum(out) == 110                           # floor(110.339), floors sum 108, +2 leftovers


def test_integerize_counts_breaks_ties_by_index():
    assert integerize_counts([1.5, 1.5, 1.0]) == [2, 1, 1]
    assert integerize_counts([1.5, 1.5]) == [2, 1]   # floor(3.0)=3, floors sum 2, tie -> index 0


def test_integerize_counts_accepts_decimals_exactly():
    out = integerize_counts([Decimal("2.999999999999999999999"), Decimal("1.0")])
    assert out == [2, 1]                              # floor(3.999...) = 3, floors 2+1


def test_integerize_counts_is_deterministic():
    values = [3 + 0.1 * (i % 7) for i in range(50)]
    assert integerize_counts(values) == integerize_counts(values)


@pytest.mark.parametrize(
    "values",
    [
        [],                       # empty
        [1.0, -0.5],               # negative
        [1.0, float("nan")],      # non-finite
        [float("inf")],            # non-finite
    ],
)
def test_integerize_counts_rejects_bad_input(values):
    with pytest.raises(ValueError):
        integerize_counts(values)


def test_population_csv_is_whole_children():
    pop = pd.read_csv(CASE1 / "population.csv")
    demand = pop["children_under_5"]
    assert len(pop) == 584
    assert demand.dtype.kind == "i"                  # integers, not fractions
    assert int(demand.sum()) == 720_720              # floor of the raster total


def test_demand_total_matches_capacity_total():
    pop = pd.read_csv(CASE1 / "population.csv")
    caps = load_site_capacities(CASE1 / "sites_capacity.csv")
    assert int(pop["children_under_5"].sum()) == int(caps.sum())   # 720_720 == 720_720


def test_allocation_demo_assigns_whole_children():
    alloc = pd.read_csv(CASE1 / "allocation_demo.csv")
    assert alloc["children_assigned"].dtype.kind == "i"
    assert int(alloc["children_assigned"].sum()) == 720_720
