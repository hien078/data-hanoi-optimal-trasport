"""Distance matrix computation.

MVP: Haversine (great-circle) distance in kilometers — a GEOGRAPHIC
BASELINE, not road travel distance. Road-network distances via
OSMnx/NetworkX are a planned extension (see docs/assumptions.md).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import get_logger, load_config, output_path

log = get_logger("distances")

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius


class DistanceError(RuntimeError):
    """Raised when distance inputs are invalid."""


def haversine_matrix(
    origin_lat: np.ndarray,
    origin_lon: np.ndarray,
    dest_lat: np.ndarray,
    dest_lon: np.ndarray,
    earth_radius_km: float = EARTH_RADIUS_KM,
) -> np.ndarray:
    """Pairwise Haversine distances between origins and destinations.

    Args:
        origin_lat: Origin latitudes, shape (n_origins,), degrees.
        origin_lon: Origin longitudes, shape (n_origins,), degrees.
        dest_lat: Destination latitudes, shape (n_dests,), degrees.
        dest_lon: Destination longitudes, shape (n_dests,), degrees.
        earth_radius_km: Sphere radius.

    Returns:
        Array of shape (n_origins, n_dests), kilometers.

    Raises:
        DistanceError: On shape mismatch or non-finite coordinates.
    """
    olat = np.asarray(origin_lat, dtype=float)
    olon = np.asarray(origin_lon, dtype=float)
    dlat = np.asarray(dest_lat, dtype=float)
    dlon = np.asarray(dest_lon, dtype=float)
    if olat.shape != olon.shape or olat.ndim != 1:
        raise DistanceError(f"Origin lat/lon shape mismatch: {olat.shape} vs {olon.shape}")
    if dlat.shape != dlon.shape or dlat.ndim != 1:
        raise DistanceError(f"Dest lat/lon shape mismatch: {dlat.shape} vs {dlon.shape}")
    for arr, label in ((olat, "origin_lat"), (olon, "origin_lon"), (dlat, "dest_lat"), (dlon, "dest_lon")):
        if not np.isfinite(arr).all():
            raise DistanceError(f"Non-finite values in {label}")

    phi1 = np.radians(olat)[:, None]
    phi2 = np.radians(dlat)[None, :]
    dphi = phi2 - phi1
    dlam = np.radians(dlon)[None, :] - np.radians(olon)[:, None]
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * earth_radius_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def build_distance_matrix(
    population: pd.DataFrame, facilities: pd.DataFrame
) -> pd.DataFrame:
    """Build the commune x facility Haversine distance matrix (km).

    Args:
        population: Population frame with ``commune_id``, ``centroid_lat``,
            ``centroid_lon``.
        facilities: Facilities frame with ``facility_id``, ``latitude``,
            ``longitude``.

    Returns:
        DataFrame indexed by ``commune_id`` with one ``facility_id`` column
        per facility; values are kilometers.

    Raises:
        DistanceError: If required columns are missing.
    """
    for col in ("commune_id", "centroid_lat", "centroid_lon"):
        if col not in population.columns:
            raise DistanceError(f"Population frame missing column '{col}'")
    for col in ("facility_id", "latitude", "longitude"):
        if col not in facilities.columns:
            raise DistanceError(f"Facilities frame missing column '{col}'")

    cfg = load_config()
    radius = cfg["distance"]["earth_radius_km"]
    mat = haversine_matrix(
        population["centroid_lat"].to_numpy(float),
        population["centroid_lon"].to_numpy(float),
        facilities["latitude"].to_numpy(float),
        facilities["longitude"].to_numpy(float),
        earth_radius_km=radius,
    )
    df = pd.DataFrame(
        mat,
        index=population["commune_id"].astype(str),
        columns=facilities["facility_id"].astype(str),
    )
    df.index.name = "commune_id"
    log.info(
        "Distance matrix: %d communes x %d facilities (Haversine, km)",
        len(df), df.shape[1],
    )
    return df


def save_distance_matrix(df: pd.DataFrame) -> Path:
    """Write the distance matrix CSV (rows=communes, cols=facilities).

    Args:
        df: Distance matrix DataFrame.

    Returns:
        Path to the written CSV.
    """
    out = output_path("distance_matrix")
    df.to_csv(out, index=True, index_label="commune_id")
    log.info("Saved %dx%d matrix -> %s", *df.shape, out)
    return out
