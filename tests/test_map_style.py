"""Tests for hanoi_ot.map_style: facility marker sizing by capacity."""

import pytest

from hanoi_ot.map_style import capacity_radius, FACILITY_TYPE_COLORS


def test_capacity_radius_endpoints():
    assert capacity_radius(0, 2253) == 3                    # floor, never invisible
    assert capacity_radius(2253, 2253) == pytest.approx(9)  # max capacity -> 9px


def test_capacity_radius_monotonic():
    lo, hi = capacity_radius(100, 1000), capacity_radius(400, 1000)
    assert lo < hi                                         # bigger capacity -> bigger marker


def test_capacity_radius_bad_max():
    assert capacity_radius(5, 0) == 3                      # max_cap <= 0 stays safe
    assert capacity_radius(5, -2) == 3


def test_colors_cover_six_types():
    assert set(FACILITY_TYPE_COLORS) == {
        "hospital", "clinic", "pharmacy", "dentist", "doctors", "Unknown",
    }
    assert len(set(FACILITY_TYPE_COLORS.values())) == 6   # six distinct colors


def test_colors_valid_hex():
    import re

    for v in FACILITY_TYPE_COLORS.values():
        assert re.fullmatch(r"#[0-9a-f]{6}", v)
