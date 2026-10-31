"""Merge the road and straight-line folium maps into one toggle page.

Produces ``docs/index_compare.html``: both maps share one window and two
buttons switch between them, so the team can compare the OSRM road
allocation against the straight-line baseline without opening two
5-13 MB files side by side.

Inputs are two independent folium exports. Typical flow::

    # 1) straight-line baseline
    python scripts/make_map.py --haversine
    cp data/processed/case1/allocation_map.html /tmp/haversine.html
    # 2) road map (needs OSRM running, see README)
    python scripts/make_map.py
    # 3) merge (use the freshly built road map, or docs/index.html)
    python scripts/build_compare_page.py \
        --road data/processed/case1/allocation_map.html \
        --haversine /tmp/haversine.html \
        --out docs/index_compare.html

The merge is plain text surgery on the two HTML exports:

- each map's layer-control sync (``.leaflet-control-layers-overlays``) is
  scoped to its own pane so the two Leaflet maps do not fight over one
  selector;
- the road map keeps its position in the document, the haversine map is
  appended after it and hidden behind ``display:none``;
- switching calls ``invalidateSize()`` so Leaflet re-measures the pane.

Folium randomises element ids on every export, so the merge is done by
structural markers ("var map_<hex> = L.map(", "Keep Leaflet's inputs and
events handlers") rather than by id.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCOPE = "document.querySelector('.leaflet-control-layers-overlays')"


def script_blocks(html: str) -> list[str]:
    """Return the body of every inline <script> block."""
    return [m.group(1) for m in re.finditer(r"<script>(.*?)</script>", html, re.S)]


def map_var(html: str) -> str:
    m = re.search(r"var (map_[0-9a-f]+) = L\.map\(", html)
    if not m:
        sys.exit("error: no folium map variable found (is this a folium export?)")
    return m.group(1)


def map_div(html: str, var: str) -> str:
    m = re.search(
        r'<div class="folium-map" id="map_' + var[4:] + r'"[^>]*>\s*</div>', html
    )
    if not m:
        sys.exit(f"error: div for {var} not found")
    return m.group(0)


def scope_sync(script: str, pane_id: str) -> str:
    """Point the layer-control sync at one pane instead of the whole document."""
    return script.replace(
        SCOPE,
        f"document.getElementById('{pane_id}').querySelector"
        "('.leaflet-control-layers-overlays')",
        1,
    )


def merge(road_html: str, hav_html: str) -> str:
    road_var, hav_var = map_var(road_html), map_var(hav_html)

    # Haversine pieces to graft in: its map div, its init script, and its
    # layer-control sync (same script when folium puts both in one block).
    hav_div = map_div(hav_html, hav_var)
    hav_scripts = script_blocks(hav_html)
    hav_init = next(s for s in hav_scripts if f"var {hav_var} = L.map(" in s)
    hav_sync = next(s for s in hav_scripts if "Keep Leaflet's inputs and events" in s)
    hav_init = scope_sync(hav_init, "pane-hav")
    hav_sync = scope_sync(hav_sync, "pane-hav")

    # Road pieces: keep the road init where it is, but scope its sync too.
    road_sync = next(s for s in script_blocks(road_html)
                     if "Keep Leaflet's inputs and events" in s)
    merged = road_html.replace(road_sync, scope_sync(road_sync, "pane-road"), 1)

    # Wrap the two map divs in panes; haversine starts hidden.
    road_div = map_div(merged, road_var)
    panes = (
        f'<div id="pane-road" class="pane">{road_div}</div>\n'
        f'<div id="pane-hav" class="pane" style="display:none">{hav_div}</div>'
    )
    merged = merged.replace(road_div, panes, 1)

    css = """<style>
#pane-road, #pane-hav {position:absolute; top:0; left:0; right:0; bottom:0;}
#switchbar {position:fixed; bottom:14px; left:50%; transform:translateX(-50%);
  z-index:10000; display:flex; gap:8px; font:600 13px sans-serif;}
.switchbtn {background:rgba(255,255,255,.95); border:2px solid #b75e14;
  border-radius:6px; padding:8px 14px; cursor:pointer; box-shadow:0 1px 6px #777;}
.switchbtn.active {background:#b75e14; color:#fff;}
@media(max-width:700px){#switchbar{bottom:8px; font-size:11px}}
</style>
<div id="switchbar">
<button class="switchbtn active" data-pane="road"
  onclick="showPane('road')">Road distance (OSRM)</button>
<button class="switchbtn" data-pane="hav"
  onclick="showPane('hav')">Straight-line (haversine)</button>
</div>"""
    merged = merged.replace("</body>", css + "\n</body>", 1)

    switch_js = f"""<script>
function showPane(which) {{
  var pr = document.getElementById('pane-road'), ph = document.getElementById('pane-hav');
  pr.style.display = which === 'road' ? 'block' : 'none';
  ph.style.display = which === 'hav' ? 'block' : 'none';
  var mv = which === 'road' ? {road_var} : {hav_var};
  setTimeout(function () {{ mv.invalidateSize(); }}, 60);
  document.querySelectorAll('.switchbtn').forEach(function (b) {{
    b.classList.toggle('active', b.getAttribute('data-pane') === which);
  }});
}}
</script>
"""
    # One insertion when folium merged init + sync into a single script,
    # otherwise keep both (avoid initialising the same map twice).
    if hav_init == hav_sync:
        insert = f"<script>\n{scope_sync(hav_init, 'pane-hav')}\n</script>\n"
    else:
        insert = (
            f"<script>\n{hav_init}\n</script>\n"
            f"<script>\n{hav_sync}\n</script>\n"
        )
    merged = merged.replace("</body>", insert + switch_js + "</body>", 1)
    return merged


def verify(out: str) -> None:
    checks = {
        "two map variables": len(re.findall(r"var map_[0-9a-f]+ = L\.map\(", out)) == 2,
        "both panes present": out.count('id="pane-road"') == 1
        and out.count('id="pane-hav"') == 1,
        "both syncs scoped": "getElementById('pane-road').querySelector" in out
        and "getElementById('pane-hav').querySelector" in out,
        "ends with </html>": out.rstrip().endswith("</html>"),
        "two switch buttons": out.count("class=\"switchbtn") == 2,
    }
    for name, ok in checks.items():
        print(f"  {name}: {'OK' if ok else 'FAIL'}")
    if not all(checks.values()):
        sys.exit("verification failed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--road", required=True, help="road-distance folium export")
    ap.add_argument("--haversine", required=True, help="straight-line folium export")
    ap.add_argument("--out", default="docs/index_compare.html", help="output page")
    args = ap.parse_args()

    road = Path(args.road).read_text(encoding="utf-8")
    hav = Path(args.haversine).read_text(encoding="utf-8")
    out_html = merge(road, hav)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out_html, encoding="utf-8")

    print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    verify(out_html)


if __name__ == "__main__":
    main()
