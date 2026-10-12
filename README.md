# Hanoi Optimal Transport Data

A small, reusable data package for allocating children to vaccination facilities and schools in Hanoi.

## Included data

- **Case 1:** 584 communes, estimated children under 5, 320 health facilities, and distance matrices.
- **Case 2:** a population raster for ages 5–14, 10,000 sample points, and 332 schools.
- **Interactive map:** [docs/index.html](docs/index.html).

> Population values are estimates. Facility capacities are unavailable. The demo uses synthetic equal capacities and is not an official result.

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

Output: `data/processed/case1/allocation_map.html`.

For road routes, Docker is required. In terminal 1:

~~~bash
bash scripts/start_osrm.sh
~~~

In terminal 2:

~~~bash
python scripts/make_map.py
~~~

### Run benchmark solvers

Real capacity is unavailable, so synthetic capacity must be explicitly enabled:

~~~bash
python scripts/run_benchmarks.py --synthetic-uniform-capacity
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
