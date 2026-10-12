#!/usr/bin/env bash
# Local OSRM car routing. OSM data © OpenStreetMap contributors (ODbL).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw/osrm
image=ghcr.io/project-osrm/osrm-backend:v5.27.1
docker pull "$image"
if [ ! -f data/raw/osrm/vietnam.osm.pbf ]; then
  curl -fL --retry 2 -C - https://download.geofabrik.de/asia/vietnam-latest.osm.pbf -o data/raw/osrm/vietnam.osm.pbf.tmp
  mv data/raw/osrm/vietnam.osm.pbf.tmp data/raw/osrm/vietnam.osm.pbf
fi
# ponytail: entire Vietnam extract; crop with osmium when preprocessing resources become limiting.
if [ ! -f data/raw/osrm/.car-ch-ready ]; then
  docker run --rm -v "$PWD/data/raw/osrm:/data" "$image" osrm-extract -t 2 -p /opt/car.lua /data/vietnam.osm.pbf
  docker run --rm -v "$PWD/data/raw/osrm:/data" "$image" osrm-contract -t 2 /data/vietnam.osrm
  touch data/raw/osrm/.car-ch-ready
fi
# Foreground service; Ctrl+C stops it. Localhost only, never publicly exposed.
docker run --rm -p 127.0.0.1:5000:5000 -v "$PWD/data/raw/osrm:/data:ro" "$image" osrm-routed --algorithm ch --max-table-size 100 /data/vietnam.osrm
