#!/usr/bin/env python3
"""
Convert NYC City Council district boundaries (GeoJSON, EPSG:4326) into
compact inline-SVG paths for the district map view.

Input:  council_districts.geojson (NYC ArcGIS FeatureServer export, 51
        features with property CounDist). Pass the path as argv[1]; defaults
        to the file sitting next to this script.
Output: ../data/districts_map.json
        { "viewBox": "0 0 800 900",
          "districts": [ {"district": 1, "path": "M..Z", "cx": .., "cy": ..} ] }

Simplification: Douglas-Peucker per ring (tolerance in degrees), rings under
a minimum area dropped, coordinates projected with latitude-corrected
equirectangular scaling and rounded to 1 decimal. Keeps the whole file at a
few hundred KB.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "council_districts.geojson"
OUT = HERE.parent / "data" / "districts_map.json"

TOL = 0.0006          # Douglas-Peucker tolerance in degrees (~55 m)
MIN_RING_AREA = 3e-6  # drop slivers/tiny islands below this (sq. degrees)
WIDTH = 800.0


def simplify_ring(ring: list, tol: float) -> list:
    """Douglas-Peucker for a CLOSED ring (first point == last point).

    A closed ring's endpoints coincide, which degenerates the anchor segment
    and collapses everything; split at the vertex farthest from point 0 and
    simplify the two open arcs separately.
    """
    pts = ring[:-1] if ring[0] == ring[-1] else list(ring)
    if len(pts) < 4:
        return ring
    x0, y0 = pts[0]
    far = max(range(1, len(pts)),
              key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
    a = dp(pts[:far + 1], tol)
    b = dp(pts[far:] + [pts[0]], tol)
    return a + b[1:]


def dp(points: list, tol: float) -> list:
    """Iterative Douglas-Peucker for an open polyline."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        dmax, imax = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol:
            keep[imax] = True
            stack.append((a, imax))
            stack.append((imax, b))
    return [p for p, k in zip(points, keep) if k]


def ring_area(ring: list) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def main() -> None:
    gj = json.loads(SRC.read_text())
    feats = gj["features"]

    # Collect all coordinates for the projection bounds
    def rings_of(geom):
        if geom["type"] == "Polygon":
            return geom["coordinates"]
        return [r for poly in geom["coordinates"] for r in poly]

    all_pts = [p for f in feats for r in rings_of(f["geometry"]) for p in r]
    lons = [p[0] for p in all_pts]
    lats = [p[1] for p in all_pts]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    lat_mid = math.radians((lat0 + lat1) / 2)
    aspect = ((lat1 - lat0)) / ((lon1 - lon0) * math.cos(lat_mid))
    height = WIDTH * aspect
    sx = WIDTH / (lon1 - lon0)
    sy = height / (lat1 - lat0)

    def proj(lon, lat):
        return round((lon - lon0) * sx, 1), round((lat1 - lat) * sy, 1)

    districts = []
    for f in feats:
        n = int(f["properties"]["CounDist"])
        parts = []
        areas = []
        centroids = []
        for ring in rings_of(f["geometry"]):
            a = ring_area(ring)
            if a < MIN_RING_AREA:
                continue
            simp = simplify_ring(ring, TOL)
            if len(simp) < 4:
                continue
            pts = [proj(x, y) for x, y in simp]
            d = "M" + " ".join(f"{x} {y}" for x, y in pts) + "Z"
            parts.append(d)
            areas.append(a)
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            centroids.append((cx, cy))
        # label anchor = centroid of the largest ring
        main_i = areas.index(max(areas))
        districts.append({
            "district": n,
            "path": "".join(parts),
            "cx": round(centroids[main_i][0], 1),
            "cy": round(centroids[main_i][1], 1),
        })

    districts.sort(key=lambda d: d["district"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "viewBox": f"0 0 {int(WIDTH)} {int(height) + 1}",
        "source": "NYC City Council Districts, NYC ArcGIS FeatureServer (EPSG:4326)",
        "districts": districts,
    }, separators=(",", ":")))
    size = OUT.stat().st_size
    print(f"Wrote {OUT}: {len(districts)} districts, {size/1024:.0f} KB")


if __name__ == "__main__":
    main()
