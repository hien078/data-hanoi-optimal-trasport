"""Population raster processing (children under five, Meta HRSL).

Reads the Meta under-5 GeoTIFF, clips to Hanoi, aggregates estimated
children counts per commune, and exports the standardized population CSV.

Population values are ESTIMATED COUNTS per pixel (Meta HRSL, 2020),
summed per commune. They are model-based estimates, not census counts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rio_mask

from .boundaries import commune_centroids, geometry_union
from .config import get_logger, load_config, output_path

log = get_logger("population")


class PopulationError(RuntimeError):
    """Raised when the population raster is unusable or inconsistent."""


def _find_raster(directory: Path) -> Path:
    """Find the first GeoTIFF under a directory.

    Args:
        directory: Extracted population download directory.

    Returns:
        Path to the ``.tif`` file.

    Raises:
        PopulationError: If no raster is found.
    """
    tifs = sorted(p for p in directory.rglob("*.tif*") if p.is_file())
    if not tifs:
        raise PopulationError(f"No GeoTIFF found under {directory}")
    return tifs[0]


def inspect_raster(raster_path: Path) -> dict[str, Any]:
    """Validate raster metadata and return it (CRS, bounds, nodata, dtype).

    Args:
        raster_path: Path to the GeoTIFF.

    Returns:
        Metadata dict.

    Raises:
        PopulationError: If CRS is missing (cannot georeference).
    """
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            raise PopulationError(f"Raster has no CRS: {raster_path}")
        meta = {
            "crs": str(src.crs),
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
            "bounds": tuple(src.bounds),
            "res": src.res,
        }
    log.info(
        "Raster %s: crs=%s size=%dx%d dtype=%s nodata=%s res=%s",
        raster_path.name, meta["crs"], meta["width"], meta["height"],
        meta["dtype"], meta["nodata"], meta["res"],
    )
    return meta


def _sum_pixels_in_geom(
    src: rasterio.DatasetReader, geom: Any, nodata: float | None
) -> tuple[float, int]:
    """Sum valid pixel values inside one geometry (pixel-center rule).

    Args:
        src: Open raster dataset (band 1).
        geom: Shapely geometry in the raster's CRS.
        nodata: Raster nodata value.

    Returns:
        ``(sum_of_valid_values, n_nodata_pixels)``.
    """
    arr, _ = rio_mask(
        src, [geom], crop=True, all_touched=False, filled=True, indexes=1
    )
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    n_nodata = int((~valid).sum())
    total = float(arr[valid].sum())
    return total, n_nodata


def zonal_population(
    raster_path: Path, communes: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Aggregate raster population per commune polygon.

    Args:
        raster_path: Path to the under-5 population GeoTIFF.
        communes: Hanoi commune boundaries (EPSG:4326).

    Returns:
        DataFrame indexed by commune row order with ``children_under_5``
        and ``nodata_pixels`` columns.

    Raises:
        PopulationError: If the raster CRS cannot be projected to WGS84.
    """
    cfg = load_config()
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            raise PopulationError("Raster CRS missing")
        # Reproject commune geometries into the raster's CRS so the mask
        # is exact regardless of raster CRS (HRSL is 4326, but be safe).
        geoms = communes.to_crs(src.crs).geometry.tolist()
        rows = [_sum_pixels_in_geom(src, g, src.nodata) for g in geoms]
    totals = pd.DataFrame(rows, columns=["children_under_5", "nodata_pixels"])
    log.info(
        "Zonal stats: %d communes, total under-5 = %.0f, nodata pixels = %d",
        len(totals), totals["children_under_5"].sum(), totals["nodata_pixels"].sum(),
    )
    return totals


def build_population(
    pop_dir: Path, communes: gpd.GeoDataFrame
) -> pd.DataFrame:
    """Full population pipeline: raster -> per-commune CSV schema.

    Args:
        pop_dir: Extracted Meta under-5 download directory.
        communes: Hanoi commune boundaries (EPSG:4326).

    Returns:
        DataFrame with columns: commune_id, commune_name, children_under_5,
        centroid_lat, centroid_lon, data_year, source.
    """
    cfg = load_config()
    raster = _find_raster(pop_dir)
    inspect_raster(raster)
    totals = zonal_population(raster, communes)

    pts = commune_centroids(communes)
    df = pd.DataFrame(
        {
            "commune_id": communes["commune_id"].astype(str).values,
            "commune_name": communes["commune_name"].astype(str).values,
            "children_under_5": totals["children_under_5"].values,
            "centroid_lat": pts["centroid_lat"].values,
            "centroid_lon": pts["centroid_lon"].values,
        }
    )
    df["data_year"] = cfg["sources"]["population_under5"]["year"]
    df["source"] = "Meta HRSL under-5 2020 (CC-BY 4.0) via HDX"
    return df


def save_population(df: pd.DataFrame) -> Path:
    """Write the standardized population CSV.

    Args:
        df: Population frame (see ``build_population``).

    Returns:
        Path to the written CSV.
    """
    out = output_path("population")
    df.to_csv(out, index=False)
    log.info("Saved %d commune rows -> %s", len(df), out)
    return out
