"""Local OSRM driving distances and routes; no geographic fallback."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from .distances import DistanceError


class RoadRoutingError(DistanceError):
    """Invalid road-routing input, unreachable route, or OSRM failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RoadRoutingError("OSRM redirects are not allowed; use a local endpoint directly")


def _base_url(value: str) -> str:
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
        valid = (
            url.scheme in ("http", "https")
            and url.hostname in ("localhost", "127.0.0.1", "::1")
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and (port is None or 0 < port <= 65535)
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise RoadRoutingError("OSRM base_url must be a local HTTP(S) endpoint: localhost, 127.0.0.1, or ::1")
    return value.rstrip("/")


def _coordinates(lat, lon, label: str) -> list[list[float]]:
    try:
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RoadRoutingError(f"{label}: coordinates must be numeric") from exc
    if lat.ndim != 1 or lat.shape != lon.shape or not lat.size:
        raise RoadRoutingError(f"{label}: coordinates must be nonempty matching vectors")
    if not np.isfinite(lat).all() or not np.isfinite(lon).all():
        raise RoadRoutingError(f"{label}: coordinates must be finite")
    if (np.abs(lat) > 90).any() or (np.abs(lon) > 180).any():
        raise RoadRoutingError(f"{label}: latitude/longitude outside valid ranges")
    return np.column_stack((lat, lon)).tolist()


def _frame(frame: pd.DataFrame, id_col: str, lat_col: str, lon_col: str):
    for col in (id_col, lat_col, lon_col):
        if col not in frame.columns:
            raise RoadRoutingError(f"Missing column '{col}'")
    ids = frame[id_col].astype(str)
    if frame.empty or frame[id_col].isna().any() or ids.str.strip().eq("").any() or not ids.is_unique:
        raise RoadRoutingError(f"{id_col}: IDs must be nonempty, nonnull, and unique")
    return ids, _coordinates(frame[lat_col], frame[lon_col], id_col)


def _request(base: str, service: str, coordinates: list[list[float]], params: dict):
    locations = ";".join(f"{lon},{lat}" for lat, lon in coordinates)
    url = f"{base}/{service}/v1/driving/{locations}?{urllib.parse.urlencode(params)}"
    # Disable environment proxies and redirects: local-only requests stay local.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(url, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        raise RoadRoutingError(f"OSRM {service} request failed (timeout/network/HTTP): {exc}") from exc
    except (ValueError, UnicodeError) as exc:
        raise RoadRoutingError(f"OSRM {service} returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != "Ok":
        detail = payload.get("message", payload.get("code")) if isinstance(payload, dict) else "invalid response"
        raise RoadRoutingError(f"OSRM {service} failed: {detail}")
    return payload


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_road_distance_matrix(
    population: pd.DataFrame, facilities: pd.DataFrame, base_url: str
) -> pd.DataFrame:
    """Return directed commune-to-facility driving distances in km.

    Each table request uses at most 100 coordinates. Unreachable pairs fail
    explicitly; distances are never substituted with a geographic baseline.
    """
    base = _base_url(base_url)
    origins_ids, origins = _frame(population, "commune_id", "centroid_lat", "centroid_lon")
    dest_ids, destinations = _frame(facilities, "facility_id", "latitude", "longitude")
    matrix = np.empty((len(origins), len(destinations)))
    for i in range(0, len(origins), 50):
        sources = origins[i:i + 50]
        for j in range(0, len(destinations), 50):
            targets = destinations[j:j + 50]
            payload = _request(base, "table", sources + targets, {
                "sources": ";".join(map(str, range(len(sources)))),
                "destinations": ";".join(map(str, range(len(sources), len(sources) + len(targets)))),
                "annotations": "distance",
            })
            rows = payload.get("distances")
            if not isinstance(rows, list) or len(rows) != len(sources) or any(
                not isinstance(row, list) or len(row) != len(targets) for row in rows
            ):
                raise RoadRoutingError("OSRM table returned an invalid distance matrix shape")
            for row in rows:
                for value in row:
                    if value is None:
                        raise RoadRoutingError("OSRM table contains an unreachable origin/destination pair (null distance)")
                    if not _number(value) or value < 0:
                        raise RoadRoutingError("OSRM table distances must be finite nonnegative numbers")
            matrix[i:i + len(sources), j:j + len(targets)] = np.asarray(rows) / 1000
    result = pd.DataFrame(matrix, index=origins_ids, columns=dest_ids)
    result.index.name = "commune_id"
    return result


def route_coordinates(
    origin_lat, origin_lon, dest_lat, dest_lon, base_url: str
) -> list[list[float]]:
    """Return the directed driving route as [latitude, longitude] points."""
    base = _base_url(base_url)
    points = _coordinates([origin_lat, dest_lat], [origin_lon, dest_lon], "route")
    payload = _request(base, "route", points, {"overview": "full", "geometries": "geojson"})
    try:
        geometry = payload["routes"][0]["geometry"]
        coordinates = geometry["coordinates"]
        if geometry["type"] != "LineString" or not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError
        if any(not isinstance(point, list) or len(point) != 2 or not all(_number(v) for v in point) for point in coordinates):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RoadRoutingError("OSRM route returned invalid GeoJSON route geometry") from exc
    return _coordinates([p[1] for p in coordinates], [p[0] for p in coordinates], "OSRM route")
