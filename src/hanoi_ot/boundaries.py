"""Administrative boundary loading and Hanoi extraction.

Loads commune-level boundaries (GADM 4.1 level-3 by default; COD-AB 2025
only reaches province level), extracts Hanoi, validates geometries,
normalizes CRS, and saves canonical-column boundaries for the study area.

Canonical output columns: commune_id, commune_name, district_name,
province_name (+ source-specific columns preserved).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from .config import get_logger, load_config, output_path
from .validation import assert_no_empty_geometries

log = get_logger("boundaries")

GEO_SUFFIXES = (".geojson", ".json", ".gpkg", ".shp", ".parquet")


class BoundaryError(RuntimeError):
    """Raised when boundary data cannot be loaded or matched to Hanoi."""


def _find_vector_file(directory: Path) -> Path:
    """Find the first loadable vector file in a directory (recursively).

    Args:
        directory: Directory to search.

    Returns:
        Path to the first matching file.

    Raises:
        BoundaryError: If no vector file is found.
    """
    candidates = sorted(
        p for p in directory.rglob("*") if p.suffix.lower() in GEO_SUFFIXES and p.is_file()
    )
    if not candidates:
        raise BoundaryError(f"No vector file ({GEO_SUFFIXES}) found under {directory}")
    return candidates[0]


def load_admin_boundaries(directory: Path) -> gpd.GeoDataFrame:
    """Load Vietnam commune-level boundaries from an extracted directory.

    Args:
        directory: Directory containing the boundary vector file.

    Returns:
        GeoDataFrame of commune polygons (Vietnam-wide).

    Raises:
        BoundaryError: On missing file, empty frame, missing geometry, no CRS.
    """
    path = _find_vector_file(directory)
    log.info("Loading boundaries: %s", path.name)
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise BoundaryError(f"Boundary file is empty: {path}")
    if "geometry" not in gdf.columns:
        raise BoundaryError(f"No geometry column in {path}")
    if gdf.crs is None:
        raise BoundaryError(f"Boundary file has no CRS defined: {path}")
    return gdf


def extract_hanoi(gdf: gpd.GeoDataFrame, province_col: str) -> gpd.GeoDataFrame:
    """Extract Hanoi rows by province name (space-insensitive match).

    Args:
        gdf: Vietnam-wide commune frame.
        province_col: Column holding the province name.

    Returns:
        GeoDataFrame of Hanoi communes.

    Raises:
        BoundaryError: If Hanoi is not found.
    """
    cfg = load_config()
    variants = {v.replace(" ", "").lower() for v in cfg["project"]["hanoi_name_variants"]}
    if province_col not in gdf.columns:
        raise BoundaryError(
            f"Province column '{province_col}' missing. Available: {list(gdf.columns)}"
        )
    norm = gdf[province_col].astype(str).str.replace(" ", "", regex=False).str.lower()
    hits = gdf[norm.isin(variants)]
    if hits.empty:
        sample = sorted(gdf[province_col].astype(str).unique())[:10]
        raise BoundaryError(
            f"Hanoi not found in '{province_col}'. Name sample: {sample}"
        )
    log.info("Hanoi: %d commune polygons", len(hits))
    return hits.copy()


def clean_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop empty geometries and repair invalid ones (on a copy).

    Args:
        gdf: Input frame.

    Returns:
        Cleaned copy with valid, non-empty geometries.
    """
    out = gdf.copy()
    n_empty = out.geometry.isna().sum() + (out.geometry.is_empty).sum()
    if n_empty:
        log.warning("Dropping %d empty/missing geometries", int(n_empty))
        out = out[~out.geometry.isna() & ~out.geometry.is_empty]
    invalid = ~out.geometry.is_valid
    if invalid.any():
        log.warning("Repairing %d invalid geometries with make_valid", int(invalid.sum()))
        out.loc[invalid, "geometry"] = out.loc[invalid, "geometry"].make_valid()
    return out


def to_working_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject to the configured working CRS (EPSG:4326).

    Args:
        gdf: Input frame (any CRS).

    Returns:
        Reprojected frame.

    Raises:
        BoundaryError: If CRS is missing.
    """
    cfg = load_config()
    target = cfg["crs"]["working"]
    if gdf.crs is None:
        raise BoundaryError("Input GeoDataFrame has no CRS")
    if gdf.crs.to_epsg() == 4326:
        return gdf
    log.info("Reprojecting %s -> %s", gdf.crs, target)
    return gdf.to_crs(target)


def hanoi_communes(boundaries_dir: Path) -> gpd.GeoDataFrame:
    """Full pipeline: load communes, extract Hanoi, clean, canonicalize.

    Args:
        boundaries_dir: Extracted boundary download directory.

    Returns:
        Hanoi commune boundaries in EPSG:4326 with canonical columns:
        commune_id, commune_name, district_name, province_name.
    """
    cfg = load_config()
    cols: dict[str, str] = cfg["sources"]["admin_boundaries"]["columns"]
    gdf = load_admin_boundaries(boundaries_dir)
    hanoi = extract_hanoi(gdf, cols["province_name"])
    hanoi = clean_geometries(hanoi)
    hanoi = to_working_crs(hanoi)
    # Canonical columns; source columns preserved alongside.
    hanoi["commune_id"] = hanoi[cols["commune_id"]].astype(str)
    hanoi["commune_name"] = hanoi[cols["commune_name"]].astype(str)
    hanoi["district_name"] = hanoi[cols["district_name"]].astype(str)
    hanoi["province_name"] = hanoi[cols["province_name"]].astype(str)
    assert_no_empty_geometries(hanoi, context="hanoi boundaries")
    return hanoi


def save_boundaries(gdf: gpd.GeoDataFrame) -> Path:
    """Save Hanoi boundaries to the configured GeoJSON output.

    Args:
        gdf: Hanoi commune boundaries.

    Returns:
        Path to the written file.
    """
    out = output_path("boundaries")
    gdf.to_file(out, driver="GeoJSON")
    log.info("Saved %d boundary features -> %s", len(gdf), out)
    return out


def commune_centroids(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Compute centroids in lat/lon (projected to avoid distortion).

    Args:
        gdf: Commune boundaries (any CRS).

    Returns:
        Frame with ``centroid_lat`` / ``centroid_lon`` columns added.
    """
    cfg = load_config()
    proj = cfg["crs"]["projected"]
    pts = gdf.to_crs(proj).geometry.centroid.to_crs("EPSG:4326")
    out = gdf.copy()
    out["centroid_lon"] = pts.x
    out["centroid_lat"] = pts.y
    return out


def geometry_union(gdf: gpd.GeoDataFrame) -> BaseGeometry:
    """Dissolve all Hanoi commune geometries into one multipolygon.

    Args:
        gdf: Hanoi boundaries.

    Returns:
        Unified geometry (for raster clipping / point filtering).
    """
    return gdf.geometry.union_all()
