"""End-to-end pipeline orchestration.

Stages: download -> boundaries -> population -> facilities -> distances
-> validation -> outputs (incl. dataset_metadata.json).

Each stage is independently callable; ``run`` executes all with real
data, ``run_synthetic`` executes with the tiny synthetic fixture.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from . import __version__
from .boundaries import geometry_union, hanoi_communes, save_boundaries
from .config import REPO_ROOT, data_dir, get_logger, load_config, output_path
from .distances import build_distance_matrix, save_distance_matrix
from .download import download_source, sha256
from .facilities import build_facilities, save_facilities
from .population import build_population, save_population
from .validation import validate_outputs

log = get_logger("pipeline")


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot complete."""


def _stage_download() -> dict[str, Path]:
    """Download all configured sources; return their extract directories."""
    dirs = {}
    for key in ("admin_boundaries", "population_under5", "health_facilities"):
        dirs[key] = download_source(key)
    return dirs


def _write_metadata(
    summary: dict[str, Any],
    sources: dict[str, Any],
    raw_files: dict[str, Path],
) -> Path:
    """Write dataset_metadata.json describing every output.

    Args:
        summary: Validation summary (counts/totals).
        sources: Config ``sources`` block.
        raw_files: Raw archive path per source key (for checksums).

    Returns:
        Path to the metadata JSON.
    """
    cfg = load_config()
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline_version": __version__,
        "study_area": cfg["project"]["study_area"],
        "case": "Case 1 - children under five -> vaccination sites (MVP)",
        "outputs": {
            "boundaries": cfg["paths"]["outputs"]["boundaries"],
            "population": cfg["paths"]["outputs"]["population"],
            "facilities": cfg["paths"]["outputs"]["facilities"],
            "distance_matrix": cfg["paths"]["outputs"]["distance_matrix"],
        },
        "summary": summary,
        "sources": {
            k: {
                "dataset": v["dataset"],
                "provider": v["provider"],
                "license": v["license"],
                "file": v["file"],
                **({"sha256": sha256(raw_files[k])} if k in raw_files else {}),
            }
            for k, v in sources.items()
        },
        "population_unit": cfg["population"]["unit"],
        "population_year": cfg["sources"]["population_under5"]["year"],
        "distance_method": cfg["distance"]["method"],
        "distance_unit": cfg["distance"]["unit"],
        "balanced_ot_note": (
            "Balanced optimal transport requires sum(x) == sum(y). "
            "Facility capacities are MISSING (OSM has no capacity data), so "
            "this dataset is NOT yet ready for real-world capacity-"
            "constrained optimization. Use synthetic capacities (labeled) "
            "for method development only."
        ),
        "capacity_status": (
            "missing - no verified capacity source integrated yet"
            if not summary.get("capacity_available")
            else "present"
        ),
    }
    out = output_path("metadata")
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Metadata -> %s", out)
    return out


def run(force_download: bool = False) -> dict[str, Any]:
    """Run the full real-data pipeline.

    Args:
        force_download: Re-download sources even if present.

    Returns:
        Validation summary dict.

    Raises:
        PipelineError: If any stage fails (with cause chained).
    """
    cfg = load_config()
    try:
        dirs = _stage_download()
        raw_files = {
            k: data_dir("raw") / k / cfg["sources"][k]["file"]
            for k in ("admin_boundaries", "population_under5", "health_facilities")
        }
        log.info("Stage: boundaries")
        communes = hanoi_communes(dirs["admin_boundaries"])
        save_boundaries(communes)
        hanoi_geom = geometry_union(communes)

        log.info("Stage: population")
        population = build_population(dirs["population_under5"], communes)
        save_population(population)

        log.info("Stage: facilities")
        facilities = build_facilities(dirs["health_facilities"], hanoi_geom)
        save_facilities(facilities)

        log.info("Stage: distances")
        matrix = build_distance_matrix(population, facilities)
        save_distance_matrix(matrix)

        log.info("Stage: validation")
        summary = validate_outputs(
            population, facilities, matrix, communes,
            expected_year=cfg["sources"]["population_under5"]["year"],
            max_km=cfg["validation"]["max_haversine_distance_km"],
        )
        _write_metadata(summary, cfg["sources"], raw_files)
        log.info("Pipeline complete.")
        return summary
    except Exception as e:
        raise PipelineError(f"Pipeline failed: {e}") from e


def run_synthetic(fixture_dir: Path | None = None) -> dict[str, Any]:
    """Run the pipeline stages against the tiny synthetic fixture.

    Loads synthetic communes/facilities from ``tests/fixtures``, builds
    the distance matrix, validates, and writes outputs into
    ``data/processed`` with a ``synthetic_`` prefix avoided — instead the
    metadata records ``synthetic: true``.

    Args:
        fixture_dir: Directory with ``synthetic_boundaries.geojson`` and
            ``synthetic_facilities.csv``. Defaults to repo tests/fixtures.

    Returns:
        Validation summary dict.

    Raises:
        PipelineError: If fixture files are missing.
    """
    fdir = fixture_dir or (REPO_ROOT / "tests" / "fixtures")
    bnd_path = fdir / "synthetic_boundaries.geojson"
    fac_path = fdir / "synthetic_facilities.csv"
    if not bnd_path.exists() or not fac_path.exists():
        raise PipelineError(f"Synthetic fixtures missing in {fdir}")

    communes = gpd.read_file(bnd_path)
    facilities = pd.read_csv(fac_path)
    facilities["capacity_source"] = "SYNTHETIC (testing only, not real data)"

    population = pd.DataFrame(
        {
            "commune_id": communes["commune_id"],
            "commune_name": communes["commune_name"],
            "children_under_5": communes["children_under_5"].astype(float),
            "centroid_lat": communes["centroid_lat"],
            "centroid_lon": communes["centroid_lon"],
            "data_year": 2020,
            "source": "SYNTHETIC fixture (testing only)",
        }
    )
    matrix = build_distance_matrix(population, facilities)
    summary = validate_outputs(
        population, facilities, matrix, communes,
        expected_year=2020,
        max_km=10_000.0,  # synthetic coords may be far apart
    )
    summary["synthetic"] = True
    log.info("Synthetic run complete: %s", summary)
    return summary
