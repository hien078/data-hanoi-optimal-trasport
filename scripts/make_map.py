"""DEMO: allocation simulation + interactive HTML map.

Runs a greedy capacity-constrained assignment (children -> facilities)
using SYNTHETIC capacities (clearly labeled), then renders an interactive
folium map: commune choropleth (under-5 population), facility markers
(sized by assigned load), and assignment lines.

This is a data-usability DEMO, not the research OT solver.
Never present the synthetic capacities or this demo's allocation as real.

Usage:
    python scripts/make_map.py  # requires local OSRM, car profile
Output:
    data/processed/case1/allocation_demo.csv
    data/processed/case1/allocation_map.html
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hanoi_ot.config import REPO_ROOT, get_logger, output_path  # noqa: E402

log = get_logger("demo_map")

PROCESSED = REPO_ROOT / "data" / "processed"


def greedy_assignment(
    x: pd.Series, D: pd.DataFrame, y: pd.Series
) -> pd.DataFrame:
    """Greedy capacity-constrained assignment (mass-splitting allowed).

    Processes all (commune, facility) pairs by ascending distance; assigns
    min(remaining children, remaining capacity) to each pair. A simple
    heuristic demo of the structure the OT solver will formalize.

    Args:
        x: children per commune (index = commune_id).
        D: distance matrix (km).
        y: capacity per facility (index = facility_id).

    Returns:
        DataFrame: commune_id, facility_id, children_assigned, distance_km.
    """
    rem_x = x.astype(float).copy()
    rem_y = y.astype(float).copy()
    pairs = (
        D.stack()
        .rename("distance_km")
        .reset_index()
        .rename(columns={"level_0": "commune_id", "level_1": "facility_id"})
        .sort_values("distance_km")
    )
    out = []
    for r in pairs.itertuples(index=False):
        take = min(rem_x[r.commune_id], rem_y[r.facility_id])
        if take > 0:
            rem_x[r.commune_id] -= take
            rem_y[r.facility_id] -= take
            out.append((r.commune_id, r.facility_id, take, r.distance_km))
    alloc = pd.DataFrame(
        out, columns=["commune_id", "facility_id", "children_assigned", "distance_km"]
    )
    log.info(
        "Greedy demo: %d assignment pairs, unassigned children = %.0f",
        len(alloc), rem_x.sum(),
    )
    return alloc


def main(osrm_url: str | None = "http://127.0.0.1:5000") -> int:
    """Run the demo: assignment + map. Returns exit code."""
    pop = pd.read_csv(PROCESSED / "case1" / "population.csv")
    fac = pd.read_csv(PROCESSED / "case1" / "facilities.csv")
    fac["facility_name"] = fac["facility_name"].fillna("Cơ sở chưa có tên").map(lambda v: escape(str(v)))
    D = pd.read_csv(PROCESSED / "case1" / "distance_matrix.csv", index_col="commune_id") if osrm_url is None else None
    bnd = gpd.read_file(PROCESSED / "hanoi_boundaries.geojson")
    road = osrm_url is not None
    if road:
        from hanoi_ot.road_routes import build_road_distance_matrix, route_coordinates
        D = build_road_distance_matrix(pop, fac, osrm_url)
    distance_label = "đường bộ OSRM (ô tô; chưa kiểm chứng xe máy)" if road else "đường chim bay"

    x = pop.set_index("commune_id")["children_under_5"]
    # SYNTHETIC balanced capacities: equal split of total children.
    # Clearly labeled; never real data.
    total = float(x.sum())
    y = pd.Series(total / len(fac), index=fac["facility_id"].astype(str))

    alloc = greedy_assignment(x, D, y)
    # Fetch every allocated route before replacing any existing output.
    routes = {}
    if road:
        origins = pop.set_index("commune_id")
        destinations = fac.assign(facility_id=fac.facility_id.astype(str)).set_index("facility_id")
        for r in alloc.itertuples(index=False):
            c, f = origins.loc[r.commune_id], destinations.loc[r.facility_id]
            routes[r.commune_id, r.facility_id] = route_coordinates(
                c.centroid_lat, c.centroid_lon, f.latitude, f.longitude, osrm_url
            )

    # Per-facility load + per-commune primary facility (largest share).
    load = alloc.groupby("facility_id")["children_assigned"].sum()
    primary = (
        alloc.sort_values("children_assigned", ascending=False)
        .drop_duplicates("commune_id")
        .set_index("commune_id")["facility_id"]
    )
    fac["facility_id"] = fac["facility_id"].astype(str)
    fac["assigned_load"] = fac["facility_id"].map(load).fillna(0.0)
    pop["primary_facility"] = pop["commune_id"].map(primary)

    fac_gdf = gpd.GeoDataFrame(
        fac, geometry=gpd.points_from_xy(fac.longitude, fac.latitude), crs="EPSG:4326"
    )
    bnd = bnd.merge(pop[["commune_id", "children_under_5", "primary_facility"]], on="commune_id")
    # Browser map needs display geometry, not survey-level vertex density.
    bnd["geometry"] = bnd.geometry.simplify(0.0003, preserve_topology=True)

    # Fit the actual Hanoi boundary instead of using a guessed centre/zoom.
    min_lon, min_lat, max_lon, max_lat = bnd.total_bounds
    hanoi_bounds = [[min_lat, min_lon], [max_lat, max_lon]]
    # Public OpenStreetMap tiles require no API key.
    m = folium.Map(
        tiles=None,
        control_scale=True,
        max_bounds=True,
        min_zoom=8,
    )
    folium.TileLayer(
        tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name="Nền bản đồ OpenStreetMap",
        max_zoom=19,
    ).add_to(m)
    m.fit_bounds(hanoi_bounds, padding=(12, 12))
    m.options["maxBounds"] = hanoi_bounds
    m.options["maxBoundsViscosity"] = 1.0

    # Independent overlays let users filter each information class.
    population_layer = folium.FeatureGroup(
        name="Map 1 · Dân số trẻ dưới 5 tuổi (2020)", show=True
    ).add_to(m)
    centroid_layer = folium.FeatureGroup(
        name="Map 1 · Tâm xã/phường", show=False
    ).add_to(m)

    # Choropleth: under-5 population per commune.
    ch = folium.Choropleth(
        geo_data=bnd.to_json(),
        data=pop,
        columns=["commune_id", "children_under_5"],
        key_on="feature.properties.commune_id",
        fill_color="YlOrRd",
        fill_opacity=0.6,
        line_opacity=0.3,
        legend_name="Children under 5 (Meta HRSL 2020, estimated)",
    )
    ch.geojson.add_to(population_layer)
    ch.color_scale.add_to(m)
    ch.geojson.add_child(
        folium.GeoJsonTooltip(
            ["commune_name", "children_under_5", "primary_facility"],
            aliases=["Xã/phường", "Trẻ dưới 5 tuổi (ước tính)", "Cơ sở chính (mô phỏng)"],
            localize=True,
            sticky=False,
        )
    )

    # Commune centroids are optional because 584 labels would clutter the map.
    for r in pop.itertuples(index=False):
        folium.CircleMarker(
            [r.centroid_lat, r.centroid_lon], radius=2, weight=1,
            color="#555", fill=True, fill_opacity=0.7,
            tooltip=f"{r.commune_name}: {r.children_under_5:,.0f} trẻ dưới 5 tuổi",
        ).add_to(centroid_layer)

    route_layers = {}
    for is_primary in (True, False):
        for band in ("Dưới 5 km", "5 đến dưới 10 km", "Từ 10 km"):
            label = "chính" if is_primary else "phụ"
            route_layers[is_primary, band] = folium.FeatureGroup(
                name=f"Map 1 · Tuyến {label} · {band} ({distance_label})", show=False
            ).add_to(m)

    # Assignment lines: commune centroid -> facility.
    pts = pop.set_index("commune_id")[["centroid_lat", "centroid_lon"]]
    fac_xy = fac_gdf.set_index("facility_id")[["latitude", "longitude"]]
    for r in alloc.itertuples(index=False):
        is_primary = primary.get(r.commune_id) == r.facility_id
        band = "Dưới 5 km" if r.distance_km < 5 else "5 đến dưới 10 km" if r.distance_km < 10 else "Từ 10 km"
        c = pts.loc[r.commune_id]
        f = fac_xy.loc[r.facility_id]
        folium.PolyLine(
            routes[r.commune_id, r.facility_id] if road else [[c.centroid_lat, c.centroid_lon], [f.latitude, f.longitude]],
            weight=1.5, color="#3182bd" if is_primary else "#ac5316", opacity=0.6,
            tooltip=f"{r.commune_id} → {r.facility_id}: {r.children_assigned:,.0f} trẻ; {r.distance_km:.1f} km ({distance_label})",
        ).add_to(route_layers[is_primary, band])

    # One switch per facility type: practical filtering without custom JS.
    facility_layers = {}
    for facility_type in sorted(fac_gdf["facility_type"].fillna("Không rõ").unique()):
        facility_layers[facility_type] = folium.FeatureGroup(
            name=f"Map 1 · Cơ sở — {facility_type}", show=True
        ).add_to(m)

    # Facility markers, sized by assigned demo load.
    for r in fac_gdf.itertuples(index=False):
        facility_type = r.facility_type if pd.notna(r.facility_type) else "Không rõ"
        folium.CircleMarker(
            [r.latitude, r.longitude],
            radius=3 + 6 * (r.assigned_load / max(fac_gdf["assigned_load"].max(), 1)),
            color="#08519c", fill=True, fill_opacity=0.8,
            popup=folium.Popup(
                f"<b>{r.facility_name}</b><br>Loại: {facility_type}"
                f"<br>Mã OSM: {r.facility_id}"
                f"<br>Tải phân bổ mô phỏng: {r.assigned_load:,.0f} trẻ"
                "<br><i>Công suất giả lập — không phải số liệu thực tế</i>"
            ),
            tooltip=f"{r.facility_name} ({facility_type})",
        ).add_to(facility_layers[facility_type])

    # --- Map 2 (Case 2): sampled children 5-14 + schools, same HTML file. ---
    children_layer = folium.FeatureGroup(
        name="Map 2 · Điểm trẻ 5–14 tuổi (mẫu 10.000, WorldPop 2020)", show=False
    ).add_to(m)
    school_layer = folium.FeatureGroup(
        name="Map 2 · Trường học (332, OSM)", show=False
    ).add_to(m)
    children_path = PROCESSED / "case2" / "scenario2_sampled_children.geojson"
    schools_path = PROCESSED / "case2" / "scenario2_education_facilities.csv"
    if children_path.exists():
        folium.GeoJson(
            json.dumps(json.load(open(children_path, encoding="utf-8"))),
            marker=folium.CircleMarker(radius=1.5, color="#7a0177", fill=True, fill_opacity=0.6, weight=0.5),
            tooltip="Điểm trẻ lấy mẫu (Monte Carlo, không phải trẻ thật)",
        ).add_to(children_layer)
    if schools_path.exists():
        schools = pd.read_csv(schools_path)
        for r in schools.itertuples(index=False):
            folium.CircleMarker(
                [r.latitude, r.longitude], radius=3, color="#238b45",
                fill=True, fill_opacity=0.8, weight=1,
                tooltip=f"{r.facility_name or 'Trường chưa có tên'} ({r.facility_type})",
            ).add_to(school_layer)

    folium.LayerControl(collapsed=False, position="topright").add_to(m)
    title = (
        "HÀ NỘI — Map 1: phân bổ trẻ dưới 5 tuổi đến cơ sở y tế; Map 2: điểm trẻ 5–14 tuổi và trường học. "
        f"Dân số: Meta HRSL/WorldPop 2020; ranh giới: GADM 2022; cơ sở: OpenStreetMap; khoảng cách: {distance_label}. "
        "Phân bổ greedy và công suất chia đều là giả lập, không phải kết quả OT. Chưa xác minh dịch vụ tiêm chủng."
    )
    m.get_root().html.add_child(
        folium.Element(
            f"<h4 style='position:fixed;top:10px;left:50px;right:340px;z-index:9999;"
            f"margin:0;background:rgba(255,255,255,.94);padding:8px 12px;"
            f"border-radius:4px;font:600 13px/1.35 sans-serif;box-shadow:0 1px 5px #888'>"
            f"{title}</h4>"
        )
    )

    guide = """
    <div style="position:fixed;left:10px;bottom:25px;z-index:9999;width:285px;
      background:rgba(255,255,255,.95);padding:10px 12px;border-radius:5px;
      box-shadow:0 1px 6px #777;font:12px/1.45 sans-serif">
      <b>Cách lọc lớp</b><br>
      1. Dùng bảng lớp góc trên phải.<br>
      2. <b>Map 1</b> (tiêm chủng): bật lớp dân số, lọc tuyến theo khoảng cách, bật/tắt từng loại cơ sở.<br>
      3. <b>Map 2</b> (trường học): bật lớp điểm trẻ 5–14 và lớp trường học.<br>
      4. Bật tâm xã/phường khi cần kiểm tra điểm xuất phát.<br>
      Di chuột để xem nhanh; nhấp cơ sở để xem tải mô phỏng.
    </div>
    """
    m.get_root().html.add_child(folium.Element(guide))

    m.get_root().header.add_child(folium.Element("""<title>Hà Nội — Mô phỏng phân bổ</title><style>
    .leaflet-control-layers {max-height:65vh;overflow:auto;max-width:310px}
    .leaflet-control-layers label {padding:3px 0}
    :focus-visible {outline:3px solid #b75e14}
    @media(max-width:700px) {h4 {left:10px!important;right:10px!important;font-size:11px!important} .leaflet-top {top:145px} .leaflet-control-layers {max-height:40vh;max-width:250px} body>div[style*="bottom:25px"] {display:none}}
    </style>"""))
    out_html = PROCESSED / "case1" / "allocation_map.html"
    # Render fully in memory: never truncate the visible map if rendering fails.
    html = m.get_root().render().replace("<html>", '<html lang="vi">')
    if len(html) < 100_000 or "</html>" not in html:
        raise RuntimeError("Generated map HTML is incomplete")
    tmp_html = out_html.with_suffix(".html.tmp")
    tmp_html.write_text(html, encoding="utf-8")
    tmp_html.replace(out_html)
    alloc.to_csv(PROCESSED / "case1" / "allocation_demo.csv", index=False)
    if road:
        D.to_csv(PROCESSED / "case1" / "road_distance_matrix.csv", index_label="commune_id")
    log.info("Map -> %s", out_html)
    log.info("Assignment -> %s", PROCESSED / "case1" / "allocation_demo.csv")
    print(f"OPEN: {out_html}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Allocation using local OSRM car road distances")
    parser.add_argument("--osrm-url", default="http://127.0.0.1:5000")
    parser.add_argument("--haversine", action="store_true", help="Explicit geographic baseline, not road routes")
    args = parser.parse_args()
    sys.exit(main(None if args.haversine else args.osrm_url))
