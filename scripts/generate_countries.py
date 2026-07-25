#!/usr/bin/env python3
"""Generate OpenSCAD country polygon data from Natural Earth GeoJSON.

Pipeline:
  1. Download (once) Natural Earth admin-0 countries GeoJSON into data/raw/.
  2. Project every country outline with Web-Mercator, scale so the whole
     map is MAP_WIDTH_MM wide.
  3. Simplify polygons to a printable vertex count, drop slivers below
     MIN_AREA_MM2, keep the largest ring(s) per country.
  4. Compute a label anchor (pole of inaccessibility) and a label size that
     fits the outline.
  5. Emit one .scad file per country into scad/countries/, plus an
     index (scad/countries/index.scad) that includes them all.

Usage:
  python3 scripts/generate_countries.py            # full run
  python3 scripts/generate_countries.py --country FRA  # single country

Status: SKELETON — download/projection/emit to be implemented next.
"""

import argparse
import json
import math
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw"
OUT = REPO / "scad" / "countries"

# Natural Earth 1:50m admin-0 countries (via the geojson mirror)
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)

MAP_WIDTH_MM = 800.0   # keep in sync with MAP_WIDTH in scad/puzzle.scad
LAT_CLIP = 85.0        # Mercator blows up at the poles; standard clip
MIN_AREA_MM2 = 25.0    # drop islands/slivers smaller than this


def mercator(lon_deg: float, lat_deg: float) -> tuple[float, float]:
    """Web-Mercator projection to map millimetres (x: [-W/2, W/2])."""
    lat = max(-LAT_CLIP, min(LAT_CLIP, lat_deg))
    x = lon_deg / 360.0 * MAP_WIDTH_MM
    y = (
        math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        / (2 * math.pi)
        * MAP_WIDTH_MM
    )
    return x, y


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="ISO A3 code — generate only this country")
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    raise SystemExit(
        "Skeleton only — projection helper ready, download/emit not yet implemented."
    )


if __name__ == "__main__":
    main()
