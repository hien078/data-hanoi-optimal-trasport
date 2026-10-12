"""Scenario 2: sample synthetic children from four age/sex rasters."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import Affine
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as transform_geometry
from shapely.prepared import prep


class Scenario2Error(ValueError):
    """Raised for missing, ambiguous, or incompatible Scenario 2 input."""


@dataclass(frozen=True)
class PopulationGrid:
    weights: np.ndarray
    transform: Affine
    crs: CRS


def _tokens(path: Path) -> list[str]:
    return [x for x in re.split(r"[^a-z0-9]+", path.stem.lower()) if x]


def _key(path: Path) -> tuple[str, int] | None:
    tokens = _tokens(path)
    sex_hits = set()
    if any(x in tokens for x in ("f", "female", "females", "girl", "girls")):
        sex_hits.add("f")
    if any(x in tokens for x in ("m", "male", "males", "boy", "boys")):
        sex_hits.add("m")
    age_hits = {age for age in (5, 10) if str(age) in tokens}
    if len(sex_hits) == len(age_hits) == 1:
        return sex_hits.pop(), age_hits.pop()
    return None


def discover_rasters(directory: str | Path) -> dict[tuple[str, int], Path]:
    """Find exactly one GeoTIFF for each (f,5), (f,10), (m,5), (m,10)."""
    root = Path(directory)
    found: dict[tuple[str, int], list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".tif", ".tiff"}:
            key = _key(path)
            if key:
                found.setdefault(key, []).append(path)
    expected = {(sex, age) for sex in ("f", "m") for age in (5, 10)}
    bad = {key: paths for key, paths in found.items() if len(paths) != 1}
    if set(found) != expected or bad:
        detail = {str(k): [str(p) for p in v] for k, v in found.items()}
        raise Scenario2Error(f"Expected exactly four unique sex/age rasters; found {detail}")
    return {key: paths[0] for key, paths in found.items()}


def aggregate_rasters(paths: Mapping[tuple[str, int], str | Path]) -> PopulationGrid:
    """Validate alignment and sum all finite, unmasked, nonnegative bands."""
    expected = {(sex, age) for sex in ("f", "m") for age in (5, 10)}
    if set(paths) != expected:
        raise Scenario2Error(f"Raster keys must be {sorted(expected)}")
    total = None
    metadata = None
    for path in paths.values():
        with rasterio.open(path) as src:
            if src.crs is None:
                raise Scenario2Error(f"Raster has no CRS: {path}")
            current = (src.crs, src.transform, src.height, src.width)
            if metadata is None:
                metadata = current
                total = np.zeros((src.height, src.width), dtype=np.float64)
            elif current != metadata:
                raise Scenario2Error(f"Raster is not aligned: {path}")
            data = src.read(masked=True).astype(np.float64)
            valid = (~np.ma.getmaskarray(data)) & np.isfinite(data.data) & (data.data >= 0)
            total += np.where(valid, data.data, 0).sum(axis=0)
    assert total is not None and metadata is not None
    if not np.isfinite(total).all() or total.sum() <= 0:
        raise Scenario2Error("Rasters contain no positive valid population")
    return PopulationGrid(total, metadata[1], CRS.from_user_input(metadata[0]))


def _boundary_geometry(boundary, raster_crs: CRS, boundary_crs=None) -> BaseGeometry | None:
    if boundary is None:
        return None
    if isinstance(boundary, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if boundary.crs is None:
            raise Scenario2Error("Boundary has no CRS")
        geom = boundary.to_crs(raster_crs).geometry.union_all()
    elif isinstance(boundary, BaseGeometry):
        geom = boundary
        if boundary_crs is not None and CRS.from_user_input(boundary_crs) != raster_crs:
            tx = Transformer.from_crs(boundary_crs, raster_crs, always_xy=True)
            geom = transform_geometry(tx.transform, geom)
    else:
        raise TypeError("boundary must be a Shapely geometry or GeoPandas object")
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty:
        raise Scenario2Error("Boundary is empty")
    return geom


def sample_children(
    source: str | Path | Mapping[tuple[str, int], str | Path],
    n: int,
    *,
    seed: int = 0,
    boundary=None,
    boundary_crs=None,
) -> gpd.GeoDataFrame:
    """Sample weighted cells, then uniform coordinates within cells."""
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 0:
        raise ValueError("n must be a nonnegative integer")
    paths = discover_rasters(source) if isinstance(source, (str, Path)) else source
    grid = aggregate_rasters(paths)
    geom = _boundary_geometry(boundary, grid.crs, boundary_crs)
    weights = grid.weights.copy()
    if geom is not None:
        rows, cols = np.nonzero(weights > 0)
        keep = np.zeros(len(rows), dtype=bool)
        for i, (row, col) in enumerate(zip(rows, cols)):
            corners = [grid.transform * (col + x, row + y) for x, y in ((0,0),(1,0),(1,1),(0,1))]
            keep[i] = geom.intersects(Polygon(corners))
        mask = np.zeros(weights.shape, dtype=bool)
        mask[rows[keep], cols[keep]] = True
        weights[~mask] = 0
    flat = weights.ravel()
    if flat.sum() <= 0:
        raise Scenario2Error("Boundary contains no positive population cells")
    if n == 0:
        return gpd.GeoDataFrame({"x": [], "y": []}, geometry=[], crs=grid.crs)
    rng = np.random.default_rng(seed)
    prepared = prep(geom) if geom is not None else None
    points: list[Point] = []
    limit = max(10_000, n * 1_000)
    for _ in range(limit):
        index = rng.choice(flat.size, p=flat / flat.sum())
        row, col = divmod(int(index), weights.shape[1])
        x, y = grid.transform * (col + rng.random(), row + rng.random())
        point = Point(x, y)
        if prepared is None or prepared.covers(point):
            points.append(point)
            if len(points) == n:
                break
    if len(points) != n:
        raise Scenario2Error("Could not sample enough points inside boundary")
    return gpd.GeoDataFrame(
        {"x": [p.x for p in points], "y": [p.y for p in points]},
        geometry=points,
        crs=grid.crs,
    )
