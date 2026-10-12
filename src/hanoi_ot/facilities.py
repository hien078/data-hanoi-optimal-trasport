"""Health facility processing (HOT/OSM export).

Loads OSM-derived health facility points, filters to Hanoi, deduplicates,
validates coordinates, and exports the standardized facilities CSV.
Capacity is recorded as MISSING unless a verified source exists.

IMPORTANT: OSM health facilities are crowd-sourced points of interest.
They are NOT verified vaccination sites. See docs/assumptions.md.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry

from .config import get_logger, load_config, output_path

log = get_logger("facilities")

GEO_SUFFIXES = (".geojson", ".json", ".gpkg", ".shp")


class FacilityError(RuntimeError):
    """Raised when facility data cannot be loaded or is unusable."""


def _find_vector_file(directory: Path) -> Path:
    """Find the first loadable vector file under a directory.

    Args:
        directory: Extracted facilities download directory.

    Returns:
        Path to the vector file.

    Raises:
        FacilityError: If none found.
    """
    candidates = sorted(
        p for p in directory.rglob("*") if p.suffix.lower() in GEO_SUFFIXES and p.is_file()
    )
    if not candidates:
        raise FacilityError(f"No vector file found under {directory}")
    return candidates[0]


def load_facilities(directory: Path) -> gpd.GeoDataFrame:
    """Load the raw HOT facilities export.

    Args:
        directory: Extracted facilities download directory.

    Returns:
        GeoDataFrame of facility points (Vietnam-wide).
    """
    path = _find_vector_file(directory)
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise FacilityError(f"Facility file is empty: {path}")
    log.info("Loaded %d raw facilities from %s", len(gdf), path.name)
    return gdf


def filter_to_hanoi(
    facilities: gpd.GeoDataFrame, hanoi_geom: BaseGeometry
) -> gpd.GeoDataFrame:
    """Keep only facilities whose points fall inside the Hanoi boundary.

    Args:
        facilities: Facility points (EPSG:4326).
        hanoi_geom: Unified Hanoi polygon/multipolygon (EPSG:4326).

    Returns:
        Filtered GeoDataFrame.
    """
    if facilities.crs is None:
        raise FacilityError("Facilities have no CRS")
    pts = facilities.to_crs("EPSG:4326")
    inside = pts.geometry.within(hanoi_geom)
    out = pts[inside].copy()
    log.info("Facilities inside Hanoi: %d / %d", len(out), len(facilities))
    return out


def deduplicate(facilities: gpd.GeoDataFrame, id_col: str = "osm_id") -> gpd.GeoDataFrame:
    """Remove duplicate facilities by OSM id, keeping the first occurrence.

    Cautious by design: logs what is dropped, never merges rows.

    Args:
        facilities: Input facilities.
        id_col: Column holding the OSM identifier.

    Returns:
        Deduplicated GeoDataFrame.
    """
    if id_col not in facilities.columns:
        raise FacilityError(
            f"OSM id column '{id_col}' missing. Columns: {list(facilities.columns)}"
        )
    n0 = len(facilities)
    out = facilities.drop_duplicates(subset=[id_col], keep="first")
    if (dropped := n0 - len(out)):
        log.warning("Dropped %d duplicate osm_id rows (kept first)", dropped)
    return out


def validate_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with missing or invalid lat/lon.

    Args:
        df: Frame with ``latitude`` / ``longitude`` columns.

    Returns:
        Filtered frame.

    Raises:
        FacilityError: If all rows are invalid.
    """
    ok = (
        df["latitude"].notna()
        & df["longitude"].notna()
        & df["latitude"].between(-90, 90)
        & df["longitude"].between(-180, 180)
        & ~((df["latitude"] == 0) & (df["longitude"] == 0))
    )
    bad = (~ok).sum()
    if bad:
        log.warning("Dropping %d facilities with missing/invalid coordinates", int(bad))
    out = df[ok]
    if out.empty:
        raise FacilityError("No facilities with valid coordinates remain")
    return out


def normalize_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize facility type/category into a small controlled vocabulary.

    Args:
        df: Frame with raw category columns (``amenity`` / ``healthcare``).

    Returns:
        Frame with ``facility_type`` column (lowercase, trimmed).
    """
    out = df.copy()
    raw = None
    for col in ("amenity", "healthcare", "facility_type"):
        if col in out.columns:
            raw = out[col]
            break
    if raw is None:
        log.warning("No category column found; facility_type='unknown'")
        out["facility_type"] = "unknown"
    else:
        out["facility_type"] = (
            raw.astype(str).str.strip().str.lower().replace({"nan": "unknown", "none": "unknown"})
        )
    return out


def build_facilities(
    facilities_dir: Path, hanoi_geom: BaseGeometry
) -> pd.DataFrame:
    """Full facilities pipeline: load -> filter -> dedupe -> schema.

    Capacity is always NaN (missing) here; synthetic capacities are a
    separate, explicit function.

    Args:
        facilities_dir: Extracted HOT facilities download directory.
        hanoi_geom: Unified Hanoi boundary geometry.

    Returns:
        DataFrame with columns: facility_id, facility_name, facility_type,
        latitude, longitude, capacity, capacity_source, source.
    """
    gdf = load_facilities(facilities_dir)
    gdf = filter_to_hanoi(gdf, hanoi_geom)
    gdf = deduplicate(gdf)

    name = gdf["name"] if "name" in gdf.columns else pd.Series(["unknown"] * len(gdf), index=gdf.index)
    df = pd.DataFrame(
        {
            "facility_id": gdf["osm_id"].astype(str).values,
            "facility_name": name.astype(str).str.strip().replace({"": "unnamed", "nan": "unnamed"}).values,
            "latitude": gdf.geometry.y.values,
            "longitude": gdf.geometry.x.values,
        }
    )
    # Normalize category from OSM amenity/healthcare tags.
    cat = None
    for col in ("amenity", "healthcare"):
        if col in gdf.columns:
            cat = gdf[col]
            break
    if cat is None:
        df["facility_type"] = "unknown"
    else:
        df["facility_type"] = (
            cat.astype(str).str.strip().str.lower()
            .replace({"nan": "unknown", "none": "unknown", "": "unknown"}).values
        )
    df = validate_coordinates(df)
    df["capacity"] = np.nan  # NEVER invented; see docs/assumptions.md
    df["capacity_source"] = "missing"
    df["source"] = "HOT OSM health facilities export (ODbL) via HDX"
    return df[
        [
            "facility_id", "facility_name", "facility_type",
            "latitude", "longitude", "capacity", "capacity_source", "source",
        ]
    ]


def synthetic_capacities(
    df: pd.DataFrame, default_value: int | None = None, seed: int = 42
) -> pd.DataFrame:
    """SYNTHETIC CAPACITY GENERATOR - FOR TESTING ONLY.

    Fills the ``capacity`` column with synthetic values and labels them
    explicitly as ``synthetic`` in ``capacity_source``. The result must
    never be presented as real observations.

    Args:
        df: Facilities frame (capacity column ignored/overwritten).
        default_value: Constant capacity; if None, draws uniform 200..2000.
        seed: RNG seed for reproducibility.

    Returns:
        Copy of ``df`` with synthetic capacities, clearly labeled.
    """
    cfg = load_config()
    if default_value is None:
        default_value = cfg["facilities"]["synthetic_capacity"]["default_value"]
    rng = np.random.default_rng(seed)
    out = df.copy()
    if default_value is not None:
        out["capacity"] = float(default_value)
    else:
        out["capacity"] = rng.uniform(200, 2000, size=len(out))
    out["capacity_source"] = "SYNTHETIC (testing only, not real data)"
    log.warning(
        "Applied SYNTHETIC capacities to %d facilities - never use as real data", len(out)
    )
    return out


def save_facilities(df: pd.DataFrame) -> Path:
    """Write the standardized facilities CSV.

    Args:
        df: Facilities frame.

    Returns:
        Path to the written CSV.
    """
    out = output_path("facilities")
    df.to_csv(out, index=False)
    log.info("Saved %d facilities -> %s", len(df), out)
    return out
