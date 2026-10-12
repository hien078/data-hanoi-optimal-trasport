"""Build Scenario 2 data products from WorldPop and HOT OSM sources."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import Point

from hanoi_ot.boundaries import geometry_union, hanoi_communes, save_boundaries
from hanoi_ot.config import data_dir, load_config
from hanoi_ot.download import download_source, sha256
from hanoi_ot.facilities import build_facilities
from hanoi_ot.scenario2 import discover_rasters


def download(url: str, path: Path, force: bool = False) -> Path:
    """Download one raw TIFF atomically; preserve completed files."""
    if path.exists() and path.stat().st_size and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    # WorldPop ignores range requests; restart partial downloads, retry transient errors.
    partial.unlink(missing_ok=True)
    subprocess.run([
        "curl", "--fail", "--location", "--retry", "5", "--retry-all-errors",
        "--output", str(partial), url,
    ], check=True)
    partial.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Scenario 2 data outputs")
    parser.add_argument("--sample-size", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args(argv)
    if args.sample_size < 0:
        parser.error("--sample-size must be nonnegative")

    cfg = load_config()
    raw = data_dir("raw") / "population_5_14" / "extracted"
    base = cfg["sources"]["population_5_14"]["base_url"].rstrip("/")
    names = [f"vnm_{sex}_{age}_2020.tif" for sex in ("f", "m") for age in (5, 10)]
    rasters = [download(f"{base}/{name}", raw / name, args.force_download) for name in names]

    admin_dir = download_source("admin_boundaries", force=args.force_download)
    education_dir = download_source("education_facilities", force=args.force_download)
    communes = hanoi_communes(admin_dir)
    save_boundaries(communes)
    boundary = geometry_union(communes)

    paths = discover_rasters(raw)
    processed = data_dir("processed") / "case2"
    aggregate_path = processed / "scenario2_population_5_14_hanoi.tif"
    first = next(iter(paths.values()))
    with rasterio.open(first) as src:
        hanoi_projected = communes.to_crs(src.crs)
        shapes = [hanoi_projected.geometry.union_all().__geo_interface__]
        profile = src.profile.copy()
        # Read only Hanoi's bounding window, avoiding a national aggregate output.
        window = rasterio.windows.from_bounds(*hanoi_projected.total_bounds, transform=src.transform)
        window = window.round_offsets().round_lengths()
        rows, cols = int(window.height), int(window.width)
        total = None
        for path in paths.values():
            with rasterio.open(path) as item:
                arr = item.read(1, window=window, masked=True).astype("float64")
                valid = (~arr.mask) & (arr.data >= 0)
                values = arr.data * valid
                total = values if total is None else total + values
        out_transform = rasterio.windows.transform(window, src.transform)
        inside = geometry_mask(shapes, out_shape=(rows, cols), transform=out_transform, invert=True)
        total[~inside] = 0
        profile.update(height=rows, width=cols, transform=out_transform, count=1, dtype="float32", nodata=-9999, compress="deflate")
        with rasterio.open(aggregate_path, "w", **profile) as dst:
            dst.write(total.astype("float32"), 1)

    if total is None or not np.isfinite(total).all() or total.sum() <= 0:
        raise RuntimeError("Scenario 2 raster clip contains no valid positive population")
    rng = np.random.default_rng(args.seed)
    flat = total.ravel()
    indices = rng.choice(flat.size, size=args.sample_size, p=flat / flat.sum())
    rr, cc = np.divmod(indices, total.shape[1])
    xy = [out_transform * (int(c) + rng.random(), int(r) + rng.random()) for r, c in zip(rr, cc)]
    projected_boundary = hanoi_projected.geometry.union_all()
    # Boundary cells may straddle Hanoi; resample only rejected points.
    for i in range(len(xy)):
        attempts = 0
        while not projected_boundary.covers(Point(*xy[i])):
            index = int(rng.choice(flat.size, p=flat / flat.sum()))
            r, c = divmod(index, total.shape[1])
            xy[i] = out_transform * (c + rng.random(), r + rng.random())
            attempts += 1
            if attempts > 10_000:
                raise RuntimeError("Could not sample points inside Hanoi boundary")
    children = gpd.GeoDataFrame({"x": [p[0] for p in xy], "y": [p[1] for p in xy]}, geometry=[Point(*p) for p in xy], crs=src.crs).to_crs("EPSG:4326")
    children.insert(0, "child_id", [f"child_{i:07d}" for i in range(len(children))])
    children["sample_seed"] = args.seed
    sample_path = processed / "scenario2_sampled_children.geojson"
    children.to_file(sample_path, driver="GeoJSON")

    schools = build_facilities(education_dir, boundary)
    schools["source"] = "HOT OSM education facilities export (ODbL) via HDX"
    school_path = processed / "scenario2_education_facilities.csv"
    schools.to_csv(school_path, index=False)

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case": "Scenario 2 - children aged 5 to 14 and education facilities",
        "sample": {"size": len(children), "seed": args.seed, "method": "cell probability proportional to count; uniform point inside selected cell; reject outside Hanoi"},
        "summary": {"hanoi_grid_total": float(total.sum()), "education_facilities": len(schools)},
        "outputs": {"population_raster": aggregate_path.name, "sampled_children": sample_path.name, "education_facilities": school_path.name},
        "sources": {"worldpop": {"year": 2020, "resolution": "approximately 100 m", "files": [{"name": p.name, "sha256": sha256(p)} for p in rasters]}, "education_facilities": {"provider": "HOT/OSM", "license": "ODbL 1.0"}, "boundaries": {"provider": "GADM 4.1", "license": "academic use only"}},
        "limitations": ["OSM school capacities are unavailable; capacity remains missing.", "Samples are Monte Carlo draws from modeled raster counts, not observed individual children.", "GADM boundary vintage differs from WorldPop 2020."],
    }
    metadata_path = processed / "scenario2_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
