#!/usr/bin/env python3
"""Generate OpenSCAD country polygon data from Natural Earth GeoJSON.

Pipeline:
  1. Read Natural Earth admin-0 countries GeoJSON from data/raw/
     (downloaded automatically on first run).
  2. Project every country outline with Web-Mercator, scaled so the whole
     map is MAP_WIDTH_MM wide.
  3. Keep the largest landmass polygon per country (v1: islands dropped),
     simplify to a printable vertex count, drop countries below MIN_AREA_MM2.
  4. Compute a label anchor (pole of inaccessibility) and a label size that
     fits the outline (piece.scad enforces the 4 mm printability floor).
  5. Emit one .scad module per country into scad/countries/ plus an
     index.scad with a name-dispatch module and an all_countries() module.

Run with the repo venv:  .venv/bin/python scripts/generate_countries.py
Options:
  --country FRA   generate a single country (by ADM0_A3 code)
  --report        print per-country stats without writing files
"""

import argparse
import json
import math
import pathlib
import sys
import urllib.request
import warnings

# Degenerate (collinear) polygons make oriented_envelope emit NaNs; the
# NaN angle is guarded in candidate_angles, silence the noise.
warnings.filterwarnings("ignore", message=".*oriented_envelope.*")

from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import polylabel

REPO = pathlib.Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw" / "ne_50m_admin_0_countries.geojson"
OUT = REPO / "scad" / "countries"

NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)

MAP_WIDTH_MM = 800.0    # keep in sync with MAP_WIDTH in scad/puzzle.scad
LAT_CLIP = 85.0         # Mercator blows up at the poles; standard clip
MIN_AREA_MM2 = 25.0     # skip countries smaller than this on the map
SIMPLIFY_TOL_MM = 0.15  # polygon simplification tolerance
LABEL_MIN = 4.0         # matches MIN_LABEL_SIZE in scad/piece.scad
LABEL_MAX = 12.0
CHAR_W = 0.62           # approx glyph advance / text size, Liberation Sans Bold


def mercator(lon_deg: float, lat_deg: float) -> tuple[float, float]:
    """Web-Mercator projection to map millimetres (x in [-W/2, W/2])."""
    lat = max(-LAT_CLIP, min(LAT_CLIP, lat_deg))
    x = lon_deg / 360.0 * MAP_WIDTH_MM
    y = (
        math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        / (2 * math.pi)
        * MAP_WIDTH_MM
    )
    return x, y


def project_polygon(rings: list) -> Polygon:
    """GeoJSON polygon coordinate rings (lon/lat) → shapely Polygon in map mm."""
    shell, *holes = [[mercator(lon, lat) for lon, lat in ring] for ring in rings]
    return Polygon(shell, holes)


def largest_landmass(geometry: dict) -> tuple[Polygon, float]:
    """Largest projected polygon of a (Multi)Polygon and the area share dropped."""
    if geometry["type"] == "Polygon":
        polys = [project_polygon(geometry["coordinates"])]
    elif geometry["type"] == "MultiPolygon":
        polys = [project_polygon(rings) for rings in geometry["coordinates"]]
    else:
        raise ValueError(f"Unsupported geometry: {geometry['type']}")
    polys = [p if p.is_valid else p.buffer(0) for p in polys]
    polys = [p for p in polys if not p.is_empty]
    # buffer(0) can return MultiPolygons; flatten
    flat = []
    for p in polys:
        flat.extend(p.geoms if isinstance(p, MultiPolygon) else [p])
    total = sum(p.area for p in flat)
    best = max(flat, key=lambda p: p.area)
    return best, (1 - best.area / total) if total else 0.0


LABEL_MARGIN = 0.4   # keep text this far inside the outline (mm, absorbs
                     # piece clearance + font-metric approximation)
LINE_H = 1.15        # text box height / size (ascender + descender)


def candidate_angles(poly: Polygon) -> list[float]:
    """Label angles to try: horizontal, then the shape's dominant axis
    (long thin countries like Chile or Norway want rotated labels)."""
    rect = poly.minimum_rotated_rectangle
    (x0, y0), (x1, y1), (x2, y2) = list(rect.exterior.coords)[:3]
    a, b = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
    dx, dy = ((x1 - x0, y1 - y0) if a >= b else (x2 - x1, y2 - y1))
    angle = math.degrees(math.atan2(dy, dx))
    angle = (angle + 90) % 180 - 90  # normalize to (-90, 90]
    if not math.isfinite(angle) or abs(angle) < 10:
        return [0.0]
    return [0.0, angle]


def label_spec(
    poly: Polygon, names: list[str]
) -> tuple[tuple[float, float], str, float, float]:
    """Label anchor, text, size, rotation. Emitted text genuinely fits.

    Anchor = pole of inaccessibility. For each candidate name (longest
    first) and angle, binary-search the largest text size whose bounding box
    (CHAR_W * size * len wide, LINE_H * size tall, rotated about the anchor)
    is contained in the outline. First name that fits at LABEL_MIN wins;
    piece.scad renders the label unclipped, so overflow here would print as
    unsupported filament in air.
    """
    anchor = polylabel(poly, tolerance=0.5)
    inner = poly.buffer(-LABEL_MARGIN)
    if inner.is_empty:
        return (anchor.x, anchor.y), "", 0.0, 0.0

    def fits(text: str, angle: float, size: float) -> bool:
        w, h = CHAR_W * size * len(text), LINE_H * size
        rect = box(anchor.x - w / 2, anchor.y - h / 2,
                   anchor.x + w / 2, anchor.y + h / 2)
        return inner.contains(
            affinity.rotate(rect, angle, origin=(anchor.x, anchor.y))
        )

    def max_size(text: str, angle: float) -> float:
        if not fits(text, angle, LABEL_MIN):
            return 0.0
        lo, hi = LABEL_MIN, LABEL_MAX
        for _ in range(12):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits(text, angle, mid) else (lo, mid)
        return lo

    angles = candidate_angles(poly)
    for text in names:
        best = max(((max_size(text, a), a) for a in angles), key=lambda t: t[0])
        if best[0] > 0:
            return (anchor.x, anchor.y), text, best[0], best[1]
    return (anchor.x, anchor.y), "", 0.0, 0.0


def fmt_points(coords) -> str:
    return "[" + ", ".join(f"[{x:.2f}, {y:.2f}]" for x, y in coords) + "]"


def scad_module(
    iso: str, name: str, poly: Polygon, label_pos, label_size, label_rot
) -> str:
    """Emit one country module. Points concatenate all rings; paths index them."""
    points, paths, offset = [], [], 0
    for ring in [poly.exterior, *poly.interiors]:
        coords = list(ring.coords)[:-1]  # drop closing duplicate
        points.extend(coords)
        paths.append(list(range(offset, offset + len(coords))))
        offset += len(coords)
    name_scad = name.replace("\\", "\\\\").replace('"', '\\"')
    paths_scad = "[" + ", ".join(str(p) for p in paths) + "]"
    return f"""// Generated by scripts/generate_countries.py — DO NOT EDIT
module country_{iso}(part = "all") {{
    piece(
        name = "{name_scad}",
        points = {fmt_points(points)},
        paths = {paths_scad},
        label_pos = [{label_pos[0]:.2f}, {label_pos[1]:.2f}],
        label_size = {label_size:.2f},
        label_rot = {label_rot:.1f},
        part = part
    );
}}
"""


README = REPO / "README.md"
MARK_BEGIN = "<!-- BEGIN GENERATED: skipped-countries -->"
MARK_END = "<!-- END GENERATED: skipped-countries -->"


def update_readme(generated: list, skipped: list, tight_labels: list) -> None:
    """Rewrite the skipped-countries section of README.md between markers."""
    text = README.read_text()
    if MARK_BEGIN not in text or MARK_END not in text:
        print("README markers missing — skipped-countries section not updated",
              file=sys.stderr)
        return
    shortened = [t for t in tight_labels if t[2]]
    blank = [t for t in tight_labels if not t[2]]
    rows = "\n".join(
        f"| {iso} | {name} | {area:.1f} |"
        for iso, name, area in sorted(skipped, key=lambda s: -s[2])
    )
    section = (
        f"{MARK_BEGIN}\n"
        f"**{len(generated)} countries printable, {len(skipped)} skipped** "
        f"(below {MIN_AREA_MM2:.0f} mm² at {MAP_WIDTH_MM:.0f} mm map width). "
        f"Of the printable pieces, {len(generated) - len(tight_labels)} carry "
        f"their full name, {len(shortened)} a shortened label, and "
        f"{len(blank)} are blank (no readable text fits at the "
        f"{LABEL_MIN:.0f} mm printability floor): "
        f"{', '.join(iso for iso, *_ in blank)}.\n\n"
        f"Skipped countries:\n\n"
        f"| Code | Country | mm² on map |\n|---|---|---|\n{rows}\n"
        f"{MARK_END}"
    )
    head, rest = text.split(MARK_BEGIN, 1)
    _, tail = rest.split(MARK_END, 1)
    README.write_text(head + section + tail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="ADM0_A3 code — generate only this country")
    parser.add_argument("--report", action="store_true", help="stats only, no files")
    args = parser.parse_args()

    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {NE_URL} ...", file=sys.stderr)
        urllib.request.urlretrieve(NE_URL, RAW)

    features = json.loads(RAW.read_text())["features"]
    OUT.mkdir(parents=True, exist_ok=True)

    generated, skipped, tight_labels = [], [], []
    for feat in sorted(features, key=lambda f: f["properties"]["ADM0_A3"]):
        props = feat["properties"]
        iso = props["ADM0_A3"]
        name = props.get("NAME_EN") or props.get("NAME") or props.get("ADMIN")
        if args.country and iso != args.country:
            continue

        poly, dropped_share = largest_landmass(feat["geometry"])
        poly = poly.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)
        if poly.area < MIN_AREA_MM2:
            skipped.append((iso, name, poly.area))
            continue

        # Longest-to-shortest name ladder: full name, NE short name
        # ("Dem. Rep. Congo"), NE abbreviation ("D.R.C."), ISO code.
        ladder = []
        for cand in (name, props.get("NAME"), props.get("ABBREV"), iso):
            if cand and cand not in ladder:
                ladder.append(cand)
        label_pos, label_text, label_size, label_rot = label_spec(poly, ladder)
        if label_text != name:
            tight_labels.append((iso, name, label_text))

        n_pts = len(poly.exterior.coords) + sum(len(h.coords) for h in poly.interiors)
        generated.append((iso, name, poly.area, n_pts, dropped_share))
        if args.report:
            continue
        (OUT / f"{iso}.scad").write_text(
            scad_module(iso, label_text, poly, label_pos, label_size, label_rot)
        )

    if not args.report and not args.country:
        includes = "\n".join(f"include <{iso}.scad>" for iso, *_ in generated)
        dispatch = "\n    else ".join(
            f'if (iso == "{iso}") country_{iso}(part);' for iso, *_ in generated
        )
        calls = "\n    ".join(f"country_{iso}(part);" for iso, *_ in generated)
        (OUT / "index.scad").write_text(f"""\
// Generated by scripts/generate_countries.py — DO NOT EDIT
{includes}

module country(iso, part = "all") {{
    {dispatch}
    else echo(str("Unknown country code: ", iso));
}}

module all_countries(part = "all") {{
    {calls}
}}
""")

    if not args.report and not args.country:
        update_readme(generated, skipped, tight_labels)

    total_pts = sum(n for *_, n, _ in generated)
    print(f"Generated {len(generated)} countries, {total_pts} vertices total.")
    if skipped:
        print(f"\nSkipped {len(skipped)} below {MIN_AREA_MM2} mm² "
              f"(too small at {MAP_WIDTH_MM:.0f} mm map width):")
        for iso, name, area in sorted(skipped, key=lambda s: -s[2]):
            print(f"  {iso}  {name:<32} {area:6.1f} mm²")
    if tight_labels:
        shortened = [t for t in tight_labels if t[2]]
        blank = [t for t in tight_labels if not t[2]]
        print(f"\n{len(shortened)} pieces use a shortened label:")
        for iso, name, text in shortened:
            print(f'  {iso}  {name} -> "{text}"')
        print(f"\n{len(blank)} pieces too small for any label (blank):")
        for iso, name, _ in blank:
            print(f"  {iso}  {name}")
    if args.report:
        print("\nLargest islands dropped (share of country area):")
        worst = sorted(generated, key=lambda g: -g[4])[:15]
        for iso, name, _, _, share in worst:
            if share > 0.01:
                print(f"  {iso}  {name:<32} {share:5.1%}")


if __name__ == "__main__":
    main()
