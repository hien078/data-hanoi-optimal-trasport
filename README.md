# Hanoi Optimal Transport Data

A small, reusable data package for allocating children to vaccination facilities and schools in Hanoi.

## Included data

- **Case 1:** 584 communes, estimated children under 5, 320 health facilities, and distance matrices.
- **Case 2:** a population raster for ages 5–14, 10,000 sample points, and 332 schools.
- **Interactive map:** [docs/index.html](docs/index.html).

> Population values are estimates. Facility capacities are unavailable. The demo uses synthetic equal capacities and is not an official result.

## CSV file guide

All distances are in **kilometres**. IDs connect files: `commune_id` identifies a commune and `facility_id` identifies a facility.

| File | Purpose | Main fields / use |
|---|---|---|
| `data/processed/case1/population.csv` | Case 1 demand: one row per commune with the estimated number of children under 5. | Use `children_under_5` as demand. The centroid columns provide origin coordinates. |
| `data/processed/case1/facilities.csv` | Candidate health facilities for Case 1. | Contains names, types, and coordinates. `capacity` is empty because verified capacity is unavailable. |
| `data/processed/case1/sites_capacity.csv` | **Synthetic** integer capacities for Case 1 experiments only. | `facility_id`, `capacity` (integer), `capacity_source=synthetic`, `capacity_unit`. Same facility order as the distance matrix; the integer total preserves estimated demand (2,252–2,253 per facility). Not verified vaccination throughput. |
| `data/processed/case1/distance_matrix.csv` | Straight-line distance from every commune to every health facility. | Rows are communes and columns are facilities. Use as the baseline cost matrix. |
| `data/processed/case1/road_distance_matrix.csv` | OSRM road distance from every commune centroid to every health facility. | Same layout as the straight-line matrix. Use when realistic car-road distances are preferred. |
| `data/processed/case1/allocation_demo.csv` | Greedy example using synthetic equal facility capacities. | Contains commune–facility pairs, assigned children, and distance. It is not an official or optimal result. |
| `data/processed/case2/scenario2_education_facilities.csv` | Candidate schools for Case 2. | Contains school names, types, and coordinates. `capacity` is empty because verified seat counts are unavailable. |

Related non-CSV files:

- `hanoi_boundaries.geojson`: commune boundaries shared by both cases.
- `scenario2_sampled_children.geojson`: 10,000 reproducible sample locations for children aged 5–14.
- `scenario2_population_5_14_hanoi.tif`: age 5–14 population-density raster clipped to Hanoi.
- Metadata JSON files: sources, generation details, checksums, and limitations.

## Quick start

Python 3.11+ is required.

~~~bash
git clone https://github.com/seuldz2005/data-hanoi-optimal-trasport.git
cd data-hanoi-optimal-trasport
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
~~~

## Run the scripts

Run all commands from the repository root.

### Build Case 1 data

~~~bash
python scripts/run_pipeline.py
~~~

Fast test with small synthetic data:

~~~bash
python scripts/run_pipeline.py --synthetic
~~~

Add `--force-download` to download source files again.

### Build Case 2 data

~~~bash
python scripts/run_scenario2_data.py --sample-size 10000 --seed 42
~~~

This downloads large WorldPop source files and may take time.

### Create the interactive map

Using straight-line distances:

~~~bash
python scripts/make_map.py --haversine
~~~

Output: `data/processed/case1/allocation_map.html`. Facility markers are
sized by synthetic capacity (marker area ∝ capacity, radius `3+6√(cap/max)`);
with the current equal capacities all markers are near-identical, and the
sizing differentiates only once real or tiered capacities replace the
synthetic ones. The map reads capacities from `sites_capacity.csv`, and
colors each facility by its six OSM types with an on-map legend of live
counts.

For road routes, a local OSRM server is required.

#### Road routing setup (one-time per machine)

`start_osrm.sh` pulls `ghcr.io/project-osrm/osrm-backend:v5.27.1`, downloads
the Geofabrik Vietnam extract (~330 MB, git-ignored under `data/raw/osrm/`),
then runs `osrm-extract` and `osrm-contract`. Expect ~30 minutes once,
about 2 GB of disk, and roughly 7 GB peak RAM during extraction:

~~~bash
bash scripts/start_osrm.sh   # terminal 1: preprocessing, then serves on 127.0.0.1:5000
~~~

The script ends in the foreground running `osrm-routed` (CH, car profile,
localhost only); Ctrl+C stops it. Later sessions reuse the preprocessed files
in `data/raw/osrm/`, so restarting the server is a single command:

~~~bash
docker run --rm -p 127.0.0.1:5000:5000 -v "$PWD/data/raw/osrm:/data:ro" \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-routed --algorithm ch --max-table-size 100 /data/vietnam.osrm
~~~

Sanity-check the server before mapping (expect `"code":"Ok"`):

~~~bash
curl "http://127.0.0.1:5000/route/v1/driving/105.78,20.96;105.781,20.961?overview=false"
~~~

#### Build the road-distance map

With the server running (terminal 2):

~~~bash
python scripts/make_map.py
~~~

Road mode re-queries OSRM, so it **rebuilds** `road_distance_matrix.csv`,
`allocation_demo.csv`, and `allocation_map.html` (~3–5 minutes) and draws
each allocation line along the actual driving route. The straight-line
baseline stays available via `--haversine`; switch back by restoring the
previous `git` revision. To publish via GitHub Pages, copy the new
`allocation_map.html` over `docs/index.html` before committing.

### Run benchmark solvers

Real capacity is unavailable, so synthetic capacity must be explicitly enabled:

~~~bash
python scripts/run_benchmarks.py --synthetic-uniform-capacity
~~~

### Export synthetic capacity CSV

~~~bash
python3 scripts/export_synthetic_capacity.py
~~~

The three Case 1 model inputs are `distance_matrix.csv` (or
`road_distance_matrix.csv`), `population.csv` (`children_under_5`), and
`sites_capacity.csv` (`capacity`). Join by IDs, not row numbers.

Synthetic capacity splits the **floor** of total estimated demand across
facilities as **integers** (largest-remainder split: every facility gets
`total // n`, the first `total % n` facilities get one more), so capacities are
whole children and their sum stays equal to the floored demand — no fractional
mass left over from rounding. Capacities are still synthetic test values, not
observed children, vaccine doses, or daily/monthly throughput. No time period
is assumed. This is a balanced-allocation test scenario, not a real capacity
estimate. `facilities.csv` and its missing verified capacities remain unchanged.
Regenerate after changing population, facilities, or distance-matrix columns.

To benchmark this explicit synthetic scenario:

~~~bash
python scripts/run_benchmarks.py data/processed/case1/population.csv data/processed/case1/sites_capacity.csv data/processed/case1/distance_matrix.csv
~~~

## Publish the map with GitHub Pages

1. Push this folder to a GitHub repository.
2. Open **Settings → Pages**.
3. Choose **Deploy from a branch**.
4. Select `main` and `/docs`, then click **Save**.
5. Open `https://seuldz2005.github.io/data-hanoi-optimal-trasport/`.

The map uses online OpenStreetMap tiles, so viewers need internet access.

## Data sources and licenses

- Meta HRSL: CC BY 4.0
- WorldPop: WorldPop open-data terms
- OpenStreetMap/HOT: ODbL 1.0
- GADM boundaries: academic use only

Please cite the original providers and review their terms before redistribution or commercial use.

## References

1. **Meta High Resolution Settlement Layer (HRSL), children under five, 2020.** Humanitarian Data Exchange.
   https://data.humdata.org/dataset/vietnam-high-resolution-population-density-maps-demographic-estimates

2. **WorldPop age and sex structures, Vietnam, 2020.** WorldPop.
   https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020/2020/VNM/

3. **Vietnam health facilities.** Humanitarian OpenStreetMap Team and OpenStreetMap, distributed through the Humanitarian Data Exchange.
   https://data.humdata.org/dataset/hotosm_vnm_health_facilities

4. **Vietnam education facilities.** Humanitarian OpenStreetMap Team and OpenStreetMap, distributed through the Humanitarian Data Exchange.
   https://data.humdata.org/dataset/hotosm_vnm_education_facilities

5. **Vietnam road network.** OpenStreetMap extract provided by Geofabrik.
   https://download.geofabrik.de/asia/vietnam.html

6. **GADM 4.1 administrative boundaries for Vietnam, level 3.** GADM, University of California, Davis.
   https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_VNM_3.json.zip

7. **OpenStreetMap contributors.** Base-map tiles and geographic features.
   https://www.openstreetmap.org/copyright

Accessed October 2026.
