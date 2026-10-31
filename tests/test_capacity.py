"""Tests for hanoi_ot.capacity: integer synthetic capacities."""

from pathlib import Path

import pandas as pd
import pytest

from hanoi_ot.capacity import largest_remainder_split, load_site_capacities


def test_largest_remainder_split_preserves_total():
    parts = largest_remainder_split(720_720, 320)
    assert len(parts) == 320
    assert sum(parts) == 720_720
    assert all(isinstance(p, int) and p > 0 for p in parts)
    assert set(parts) == {2252, 2253}          # 240x2252 + 80x2253


def test_split_rejects_bad_input():
    for total, n in [(-1, 3), (10, 0), (10, -2)]:
        with pytest.raises(ValueError):
            largest_remainder_split(total, n)


def test_load_site_capacities_returns_str_indexed_ints(tmp_path: Path):
    p = tmp_path / "cap.csv"
    p.write_text("facility_id,capacity\n6185334967,2252\nx2,2253\n", encoding="utf-8")
    s = load_site_capacities(p)
    assert list(s.index) == ["6185334967", "x2"]     # strings, not int-cast
    assert s.dtype.kind == "i"
    assert s.sum() == 4505


@pytest.mark.parametrize(
    "content",
    [
        "facility_id,capacity\n6185334967,n/a\n",       # non-numeric cell
        "facility_id,capacity\n6185334967,\n",          # missing value
        "facility_id,capacity\n6185334967,-5\n",       # negative
        "facility_id,capacity\n6185334967,2252.5\n",   # fractional
        "facility_id,capacity\nx,1\nx,2\n",             # duplicated ids
        "foo,bar\n1,2\n",                              # missing columns
    ],
)
def test_load_site_capacities_rejects_bad_files(tmp_path: Path, content: str):
    p = tmp_path / "bad.csv"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_site_capacities(p)
