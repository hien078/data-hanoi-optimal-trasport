"""Presentation helpers for the interactive map (sizing, colors).

Marker AREA is proportional to capacity, so the radius scales with the
square root; a floor keeps the smallest marker visible.
"""

from __future__ import annotations

import math

_MARKER_FLOOR_PX = 3.0
_MARKER_MAX_EXTRA_PX = 6.0

# Six OSM facility categories on the Case 1 map, "Unknown" catching the
# facilities with no type tag. Color-blind-friendly qualitative palette.
FACILITY_TYPE_COLORS: dict[str, str] = {
    "hospital": "#e41a1c",   # red
    "clinic": "#ff7f00",     # orange
    "pharmacy": "#377eb8",   # blue
    "dentist": "#4daf4a",   # green
    "doctors": "#984ea3",   # purple
    "Unknown": "#999999",   # grey
}


def facility_color(facility_type: str) -> str:
    """Hex color for a facility type.

    Args:
        facility_type: One of the keys of ``FACILITY_TYPE_COLORS``
            (``"Unknown"`` for missing OSM type tags).

    Returns:
        Hex color string.

    Raises:
        ValueError: If the type is not in the palette. A regenerated
            ``facilities.csv`` may carry new OSM types; the fix is to
            add the type to ``FACILITY_TYPE_COLORS``, so the error says so.
    """
    try:
        return FACILITY_TYPE_COLORS[facility_type]
    except KeyError:
        raise ValueError(
            f"unknown facility_type {facility_type!r}: "
            "add it to hanoi_ot.map_style.FACILITY_TYPE_COLORS"
        ) from None


def capacity_radius(cap: float, max_cap: float) -> float:
    """Leaflet marker radius in pixels for a facility capacity.

    ``3 + 6 * sqrt(cap / max_cap)``: area proportional to capacity with a
    3px floor so the smallest capacity stays visible.

    Args:
        cap: This facility's capacity (children).
        max_cap: Largest capacity among facilities on this map.

    Returns:
        Radius in pixels: at least 3; exactly 9 when ``cap == max_cap``.
        Values above ``max_cap`` grow past 9 — callers pass the true
        column maximum, and capacities are validated non-negative.
    """
    if max_cap <= 0:
        return _MARKER_FLOOR_PX
    return _MARKER_FLOOR_PX + _MARKER_MAX_EXTRA_PX * math.sqrt(cap / max_cap)
