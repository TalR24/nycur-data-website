#!/usr/bin/env python3
"""
Build compact inline-SVG paths for the 59 community districts, adapted from
civic_reference/nyc_council_legislation_trackers/pipeline/build_district_map.py
(same projection, ring-splitting Douglas-Peucker, and output shape).

Source: NYC Open Data "Community Districts" (5crt-au7u), boro_cd +
the_geom MultiPolygon, EPSG:4326. Fetched live; joint-interest areas
(parks, airports — boro_cd values whose district number exceeds the
borough's real board count) are dropped, leaving the 59 boards.

Output: ../data/cd_map.json
    { "viewBox": "0 0 800 H",
      "districts": [ {"cd": 101, "borough": "Manhattan", "number": 1,
                      "path": "M..Z", "cx": .., "cy": ..} ] }

Run from the member-tracker folder: python3 pipeline/build_cd_map.py
"""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache" / "community_districts_5crt.json"
OUT = HERE.parent / "data" / "cd_map.json"

TOL = 0.0007          # Douglas-Peucker tolerance in degrees (~65 m)
MIN_RING_AREA = 4e-6  # drop slivers/tiny islands below this (sq. degrees)
WIDTH = 800.0

BOROUGHS = {1: "Manhattan", 2: "Bronx", 3: "Brooklyn", 4: "Queens", 5: "Staten Island"}
BOARD_COUNTS = {1: 12, 2: 12, 3: 18, 4: 14, 5: 3}


def fetch() -> list[dict]:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    url = "https://data.cityofnewyork.us/resource/5crt-au7u.json?$limit=100"
    req = urllib.request.Request(url, headers={"User-Agent": "nycuriosity-cb-tracker"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        rows = json.load(resp)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(rows))
    return rows


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
    rows = fetch()
    feats = []
    for r in rows:
        cd = int(r["boro_cd"])
        boro, num = cd // 100, cd % 100
        if boro not in BOROUGHS or num > BOARD_COUNTS[boro]:
            continue  # joint-interest area (park, airport), not a board
        feats.append((cd, r["the_geom"]))
    if len(feats) != 59:
        raise SystemExit(f"expected 59 community districts, got {len(feats)}")

    def rings_of(geom):
        if geom["type"] == "Polygon":
            return geom["coordinates"]
        return [ring for poly in geom["coordinates"] for ring in poly]

    all_pts = [p for _, geom in feats for r in rings_of(geom) for p in r]
    lons = [p[0] for p in all_pts]
    lats = [p[1] for p in all_pts]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    lat_mid = math.radians((lat0 + lat1) / 2)
    aspect = (lat1 - lat0) / ((lon1 - lon0) * math.cos(lat_mid))
    height = WIDTH * aspect
    sx = WIDTH / (lon1 - lon0)
    sy = height / (lat1 - lat0)

    def proj(lon, lat):
        return round((lon - lon0) * sx, 1), round((lat1 - lat) * sy, 1)

    districts = []
    for cd, geom in feats:
        parts = []
        areas = []
        centroids = []
        for ring in rings_of(geom):
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
        main_i = areas.index(max(areas))
        districts.append({
            "cd": cd,
            "borough": BOROUGHS[cd // 100],
            "number": cd % 100,
            "path": "".join(parts),
            "cx": round(centroids[main_i][0], 1),
            "cy": round(centroids[main_i][1], 1),
        })

    districts.sort(key=lambda d: d["cd"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "viewBox": f"0 0 {int(WIDTH)} {int(height) + 1}",
        "source": "NYC Community Districts, NYC Open Data 5crt-au7u (EPSG:4326)",
        "districts": districts,
    }, separators=(",", ":")))
    size = OUT.stat().st_size
    print(f"Wrote {OUT}: {len(districts)} districts, {size/1024:.0f} KB")


if __name__ == "__main__":
    main()
