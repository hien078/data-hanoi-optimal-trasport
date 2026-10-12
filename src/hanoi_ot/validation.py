"""Data validation checks for all pipeline outputs.

Every check raises ``ValidationError`` with a precise, actionable message.
The pipeline calls these after each stage and before declaring outputs
model-ready.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import get_logger

log = get_logger("validation")


class ValidationError(RuntimeError):
    """Raised when a validation check fails."""


def _fail(msg: str) -> None:
    raise ValidationError(msg)


def check_ids(df: pd.DataFrame, id_col: str, context: str) -> None:
    """Check IDs are present, non-null, and unique.

    Args:
        df: Frame to check.
        id_col: ID column name.
        context: Human-readable context for error messages.

    Raises:
        ValidationError: On missing/duplicate IDs.
    """
    if id_col not in df.columns:
        _fail(f"[{context}] missing ID column '{id_col}'")
    n_null = df[id_col].isna().sum()
    if n_null:
        _fail(f"[{context}] {n_null} missing IDs in '{id_col}'")
    dups = df[id_col][df[id_col].duplicated()]
    if not dups.empty:
        _fail(
            f"[{context}] {dups.size} duplicate IDs in '{id_col}': "
            f"{sorted(dups.astype(str).unique())[:5]}..."
        )


def check_coordinates(
    df: pd.DataFrame, lat_col: str = "latitude", lon_col: str = "longitude",
    context: str = "facilities",
) -> None:
    """Check coordinates are present, finite, and in valid ranges.

    Args:
        df: Frame with coordinate columns.
        lat_col: Latitude column name.
        lon_col: Longitude column name.
        context: Context label for error messages.

    Raises:
        ValidationError: On missing/invalid coordinates.
    """
    for col in (lat_col, lon_col):
        if col not in df.columns:
            _fail(f"[{context}] missing coordinate column '{col}'")
        if df[col].isna().any():
            n = int(df[col].isna().sum())
            _fail(f"[{context}] {n} missing values in '{col}'")
        if not np.isfinite(df[col].to_numpy(float)).all():
            _fail(f"[{context}] non-finite values in '{col}'")
    if not df[lat_col].between(-90, 90).all():
        _fail(f"[{context}] latitude out of range [-90, 90]")
    if not df[lon_col].between(-180, 180).all():
        _fail(f"[{context}] longitude out of range [-180, 180]")


def check_non_negative(
    df: pd.DataFrame, col: str, context: str, allow_na: bool = False
) -> None:
    """Check a numeric column has no negative values.

    Args:
        df: Frame to check.
        col: Numeric column name.
        context: Context label.
        allow_na: If True, NaN is permitted (e.g. missing capacity).

    Raises:
        ValidationError: On negative values (or NaN when not allowed).
    """
    if col not in df.columns:
        _fail(f"[{context}] missing column '{col}'")
    vals = df[col].to_numpy(float)
    if not allow_na and np.isnan(vals).any():
        _fail(f"[{context}] NaN values in '{col}' not allowed here")
    if (vals < 0).any():
        n = int((vals < 0).sum())
        _fail(f"[{context}] {n} negative values in '{col}'")


def assert_no_empty_geometries(gdf: gpd.GeoDataFrame, context: str) -> None:
    """Check a GeoDataFrame has no empty/missing geometries.

    Args:
        gdf: Frame to check.
        context: Context label.

    Raises:
        ValidationError: On empty geometries.
    """
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        n = int(gdf.geometry.isna().sum() + gdf.geometry.is_empty.sum())
        _fail(f"[{context}] {n} empty/missing geometries")


def check_crs(gdf: gpd.GeoDataFrame, expected: str, context: str) -> None:
    """Check a GeoDataFrame is in the expected CRS.

    Args:
        gdf: Frame to check.
        expected: Expected CRS string (e.g. ``EPSG:4326``).
        context: Context label.

    Raises:
        ValidationError: On missing or mismatched CRS.
    """
    if gdf.crs is None:
        _fail(f"[{context}] CRS is missing (undefined)")
    if gdf.crs.to_epsg() != int(expected.split(":")[1]):
        _fail(f"[{context}] CRS mismatch: got {gdf.crs}, expected {expected}")


def check_distance_matrix(
    matrix: pd.DataFrame,
    population: pd.DataFrame,
    facilities: pd.DataFrame,
    max_km: float = 300.0,
) -> None:
    """Check matrix dimensions, index/column alignment, and value sanity.

    Args:
        matrix: Distance matrix (index=commune_id, columns=facility_id).
        population: Population frame (defines expected rows).
        facilities: Facilities frame (defines expected columns).
        max_km: Sanity bound for distances within the study area.

    Raises:
        ValidationError: On dimension mismatch, misalignment, missing
            values, or out-of-range distances.
    """
    expected_rows = population["commune_id"].astype(str).tolist()
    expected_cols = facilities["facility_id"].astype(str).tolist()
    if matrix.shape != (len(expected_rows), len(expected_cols)):
        _fail(
            f"[distance_matrix] shape {matrix.shape} != expected "
            f"({len(expected_rows)}, {len(expected_cols)})"
        )
    if matrix.index.astype(str).tolist() != expected_rows:
        _fail("[distance_matrix] row IDs do not match population commune_ids")
    if matrix.columns.astype(str).tolist() != expected_cols:
        _fail("[distance_matrix] column IDs do not match facility_ids")
    if matrix.isna().any().any():
        n = int(matrix.isna().sum().sum())
        _fail(f"[distance_matrix] {n} missing distances")
    if (matrix.to_numpy(float) < 0).any():
        _fail("[distance_matrix] negative distances")
    if (matrix.to_numpy(float) > max_km).any():
        _fail(
            f"[distance_matrix] distances exceed sanity bound {max_km} km "
            f"(max={matrix.to_numpy(float).max():.1f}) — check coordinates/CRS"
        )


def check_temporal_consistency(
    population: pd.DataFrame, data_year: int, context: str = "population"
) -> None:
    """Check the population frame carries a single, expected data year.

    Args:
        population: Population frame with ``data_year`` column.
        data_year: Expected year (from config).
        context: Context label.

    Raises:
        ValidationError: On missing column or mixed years.
    """
    if "data_year" not in population.columns:
        _fail(f"[{context}] missing 'data_year' column")
    years = population["data_year"].dropna().unique()
    if len(years) != 1:
        _fail(f"[{context}] mixed data years: {years.tolist()}")
    if int(years[0]) != data_year:
        _fail(f"[{context}] unexpected data year {years[0]}, expected {data_year}")


def check_capacity_labels(facilities: pd.DataFrame) -> None:
    """Check capacity values and their provenance labels are consistent.

    Real (verified) capacities must have a real ``capacity_source``;
    synthetic ones must be labeled synthetic; missing ones must be NaN
    with source 'missing'.

    Args:
        facilities: Facilities frame.

    Raises:
        ValidationError: On negative capacity, or capacity present
            without a provenance label.
    """
    if "capacity" not in facilities.columns or "capacity_source" not in facilities.columns:
        _fail("[facilities] capacity/capacity_source columns missing")
    check_non_negative(facilities, "capacity", "facilities", allow_na=True)
    has_cap = facilities["capacity"].notna()
    unlabeled = has_cap & facilities["capacity_source"].isna()
    if unlabeled.any():
        _fail(f"[facilities] {int(unlabeled.sum())} capacities without capacity_source")
    synthetic = facilities["capacity_source"].astype(str).str.contains("SYNTHETIC", case=False)
    if (synthetic & ~has_cap).any():
        _fail("[facilities] synthetic label on missing capacity — inconsistent")


def validate_outputs(
    population: pd.DataFrame,
    facilities: pd.DataFrame,
    matrix: pd.DataFrame,
    boundaries: gpd.GeoDataFrame,
    expected_year: int,
    max_km: float,
) -> dict[str, Any]:
    """Run the full output validation suite.

    Args:
        population: Population output frame.
        facilities: Facilities output frame.
        matrix: Distance matrix output.
        boundaries: Hanoi boundaries output.
        expected_year: Expected population data year.
        max_km: Distance sanity bound (km).

    Returns:
        Summary dict with counts and totals (for dataset_metadata.json).

    Raises:
        ValidationError: On any failed check.
    """
    check_ids(population, "commune_id", "population")
    check_coordinates(population, "centroid_lat", "centroid_lon", "population")
    check_non_negative(population, "children_under_5", "population")
    check_temporal_consistency(population, expected_year)
    check_ids(facilities, "facility_id", "facilities")
    check_coordinates(facilities, "latitude", "longitude", "facilities")
    check_capacity_labels(facilities)
    check_distance_matrix(matrix, population, facilities, max_km=max_km)
    assert_no_empty_geometries(boundaries, "boundaries")
    check_crs(boundaries, "EPSG:4326", "boundaries")

    summary: dict[str, Any] = {
        "n_communes": int(len(population)),
        "n_facilities": int(len(facilities)),
        "total_children_under_5": float(population["children_under_5"].sum()),
        "capacity_available": bool(facilities["capacity"].notna().any()),
        "matrix_shape": list(matrix.shape),
    }
    log.info("Validation passed: %s", summary)
    return summary
