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
import subprocess
import sys
import tempfile
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor

# Degenerate (collinear) polygons make oriented_envelope emit NaNs; the
# NaN angle is guarded in candidate_angles, silence the noise.
warnings.filterwarnings("ignore", message=".*oriented_envelope.*")

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import polylabel, unary_union

REPO = pathlib.Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw" / "ne_50m_admin_0_countries.geojson"
OUT = REPO / "scad" / "countries"

NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_0_countries.geojson"
)

MAP_WIDTH_MM = 800.0    # keep in sync with MAP_WIDTH in scad/puzzle.scad
EXCLUDED = {"ATA"}      # design choice: no Antarctica (huge Mercator slab)

# Countries too big for the build plate, split at a vertical cut (map mm).
# Russia: 339 mm wide vs 240 mm usable bed; cut at ~90 E (Yenisei area),
# giving ~140 + ~200 mm halves. The halves join with dovetail tabs
# (west half tabs, east half sockets) and are glued after printing.
SPLITS = {"RUS": 90 / 360 * MAP_WIDTH_MM}
TAB_DEPTH = 7.0         # how far tabs reach into the east half
TAB_NECK = 6.0          # tab width at the cut line
TAB_HEAD = 10.0         # tab width at the far end (wider = dovetail lock)
TAB_MAX = 3             # tabs per cut
LAT_CLIP = 85.0         # Mercator blows up at the poles; standard clip
MIN_AREA_MM2 = 25.0     # skip countries smaller than this on the map
SIMPLIFY_TOL_MM = 0.15  # polygon simplification tolerance
LABEL_MIN = 3.0         # matches MIN_LABEL_SIZE in scad/piece.scad.
                        # Liberation Sans Bold stem = 0.20 x size, so 3 mm
                        # text has 0.6 mm strokes — comfortably above the
                        # ~0.34 mm Arachne single-wall floor of a 0.4 mm
                        # nozzle. Legibility is fine: black-on-white reads
                        # by contrast, not shadow.
LABEL_MAX = 7.0         # cap for visual uniformity: labels are ISO codes,
                        # big countries shouldn't shout
LABEL_FONT = "Liberation Sans:style=Bold"  # keep in sync with scad/piece.scad
OPENSCAD = "/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD"
METRICS_CACHE = REPO / "data" / "text_metrics.json"
MEASURE_SIZE = 10.0     # metrics are measured at this text size and scaled


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
                     # the piece clearance inset)


def _measure_one(text: str) -> tuple[str, list[float]]:
    """True rendered bbox of `text`: OpenSCAD extrudes it exactly as
    piece.scad will, exported as OFF (trivial to parse). Returns
    [width, height, center_dx, center_dy] at MEASURE_SIZE, relative to the
    halign/valign=center anchor."""
    with tempfile.TemporaryDirectory() as tmp:
        scad = pathlib.Path(tmp) / "t.scad"
        off = pathlib.Path(tmp) / "t.off"
        scad.write_text(
            f'linear_extrude(height=1) text("{text}", size={MEASURE_SIZE}, '
            f'font="{LABEL_FONT}", halign="center", valign="center");'
        )
        subprocess.run([OPENSCAD, "-o", str(off), str(scad)],
                       capture_output=True, check=True)
        tokens = off.read_text().split()
        nv = int(tokens[1])
        xs = [float(tokens[4 + i * 3]) for i in range(nv)]
        ys = [float(tokens[5 + i * 3]) for i in range(nv)]
    return text, [max(xs) - min(xs), max(ys) - min(ys),
                  (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2]


def measure_texts(texts: list[str]) -> dict[str, list[float]]:
    """Measured text metrics for all `texts`, cached in data/text_metrics.json."""
    cache = json.loads(METRICS_CACHE.read_text()) if METRICS_CACHE.exists() else {}
    missing = sorted(set(texts) - set(cache))
    if missing:
        print(f"Measuring {len(missing)} label texts with OpenSCAD ...",
              file=sys.stderr)
        with ThreadPoolExecutor(max_workers=8) as pool:
            cache.update(pool.map(_measure_one, missing))
        METRICS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        METRICS_CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    return cache


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


def _largest(geom) -> Polygon:
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area)
    return geom


def split_with_tabs(poly: Polygon, cut_x: float) -> list[tuple[str, Polygon]]:
    """Split poly at vertical line x=cut_x into west/east halves joined by
    dovetail tabs: tabs union onto the west half and are subtracted from the
    east half (exact shapes — the global piece CLEARANCE inset provides the
    0.3 mm assembly/glue gap, same as any neighboring pieces)."""
    minx, miny, maxx, maxy = poly.bounds
    west = poly.intersection(box(minx - 1, miny - 1, cut_x, maxy + 1))
    east = poly.intersection(box(cut_x, miny - 1, maxx + 1, maxy + 1))

    cut = poly.intersection(LineString([(cut_x, miny - 1), (cut_x, maxy + 1)]))
    segs = [cut] if isinstance(cut, LineString) else list(cut.geoms)
    segs = sorted(
        (s for s in segs if s.length >= TAB_HEAD + 8), key=lambda s: -s.length
    )
    # Distribute TAB_MAX tabs across the land segments of the cut,
    # proportionally to segment length (one long segment gets several).
    tabs, total = [], sum(s.length for s in segs)
    for seg in segs:
        n = max(1, round(TAB_MAX * seg.length / total)) if total else 0
        for i in range(n):
            if len(tabs) >= TAB_MAX:
                break
            cy = seg.interpolate((i + 1) / (n + 1), normalized=True).y
            tab = Polygon([
                (cut_x - 0.5, cy - TAB_NECK / 2),
                (cut_x + TAB_DEPTH, cy - TAB_HEAD / 2),
                (cut_x + TAB_DEPTH, cy + TAB_HEAD / 2),
                (cut_x - 0.5, cy + TAB_NECK / 2),
            ])
            if poly.contains(tab):  # tab must sit fully on land
                tabs.append(tab)
    if not tabs:
        print("WARNING: no dovetail tabs fit on the cut line", file=sys.stderr)
    else:
        west = unary_union([west, *tabs])
        east = east.difference(unary_union(tabs))
    return [("W", _largest(west)), ("E", _largest(east))]


def label_spec(
    poly: Polygon, names: list[str], metrics: dict[str, list[float]]
) -> tuple[tuple[float, float], str, float, float]:
    """Label anchor, text, size, rotation. Emitted text genuinely fits.

    Anchor = pole of inaccessibility. For each candidate name (longest
    first) and angle, binary-search the largest text size whose MEASURED
    bounding box (true OpenSCAD render metrics, rotated about the anchor)
    is contained in the outline. First name that fits at LABEL_MIN wins;
    piece.scad renders the label unclipped, so overflow here would print as
    unsupported filament in air.
    """
    anchor = polylabel(poly, tolerance=0.5)
    inner = poly.buffer(-LABEL_MARGIN)
    if inner.is_empty:
        return (anchor.x, anchor.y), "", 0.0, 0.0

    def fits(text: str, angle: float, size: float) -> bool:
        w, h, dx, dy = (v * size / MEASURE_SIZE for v in metrics[text])
        cx, cy = anchor.x + dx, anchor.y + dy
        rect = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
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
    rows = "\n".join(
        f"| {iso} | {name} | {area:.1f} |"
        for iso, name, area in sorted(skipped, key=lambda s: -s[2])
    )
    section = (
        f"{MARK_BEGIN}\n"
        f"**{len(generated)} countries printable, {len(skipped)} skipped** "
        f"(below {MIN_AREA_MM2:.0f} mm² at {MAP_WIDTH_MM:.0f} mm map width), "
        f"plus excluded by design: {', '.join(sorted(EXCLUDED))}. "
        f"Pieces are labeled with their 3-letter code (see [KEY.md](KEY.md)); "
        f"{len(tight_labels)} pieces are too small even for that and are "
        f"blank: {', '.join(iso for iso, *_ in tight_labels)}.\n\n"
        f"Skipped countries:\n\n"
        f"| Code | Country | mm² on map |\n|---|---|---|\n{rows}\n"
        f"{MARK_END}"
    )
    head, rest = text.split(MARK_BEGIN, 1)
    _, tail = rest.split(MARK_END, 1)
    README.write_text(head + section + tail)


def write_key(generated: list, unlabeled: set) -> None:
    """Write KEY.md: the printable legend mapping piece codes to names."""
    rows = "\n".join(
        f"| {'—' if iso in unlabeled else iso} | {name} |"
        for iso, name, *_ in generated
    )
    (REPO / "KEY.md").write_text(
        "# Puzzle key\n\n"
        "Generated by scripts/generate_countries.py — DO NOT EDIT.\n\n"
        "Each puzzle piece is embossed with its 3-letter country code "
        "(Natural Earth ADM0_A3, mostly ISO 3166-1 alpha-3). Pieces marked "
        "— are too small to carry a code; identify them by shape and "
        "neighbors.\n\n"
        f"| Piece | Country |\n|---|---|\n{rows}\n"
    )


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
    metrics = measure_texts([
        f["properties"]["ADM0_A3"] for f in features
        if f["properties"]["ADM0_A3"] not in EXCLUDED
    ])

    generated, skipped, tight_labels = [], [], []
    unlabeled = set()
    for feat in sorted(features, key=lambda f: f["properties"]["ADM0_A3"]):
        props = feat["properties"]
        iso = props["ADM0_A3"]
        name = props.get("NAME_EN") or props.get("NAME") or props.get("ADMIN")
        if args.country and iso != args.country:
            continue
        if iso in EXCLUDED:
            continue

        poly, dropped_share = largest_landmass(feat["geometry"])
        poly = poly.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)
        if poly.area < MIN_AREA_MM2:
            skipped.append((iso, name, poly.area))
            continue

        if iso in SPLITS:
            # Oversize for the build plate: two dovetailed halves, glued
            # after printing. Only the east (larger) half carries the code.
            pieces_out = [
                (f"{iso}{sfx}", f"{name} ({'west' if sfx == 'W' else 'east'} half)",
                 part, [iso] if sfx == "E" else [])
                for sfx, part in split_with_tabs(poly, SPLITS[iso])
            ]
        else:
            pieces_out = [(iso, name, poly, [iso])]

        for piso, pname, ppoly, ladder in pieces_out:
            # Uniform labels: every piece carries its ISO code (KEY.md maps
            # codes to names), blank only when even 3 letters can't fit.
            label_pos, label_text, label_size, label_rot = label_spec(
                ppoly, ladder, metrics
            )
            if not label_text:
                unlabeled.add(piso)
                if ladder:
                    tight_labels.append((piso, pname, label_text))

            n_pts = len(ppoly.exterior.coords) + sum(
                len(h.coords) for h in ppoly.interiors
            )
            generated.append((piso, pname, ppoly.area, n_pts, dropped_share))
            if args.report:
                continue
            (OUT / f"{piso}.scad").write_text(
                scad_module(piso, label_text, ppoly, label_pos, label_size,
                            label_rot)
            )

    if not args.report and not args.country:
        keep = {iso for iso, *_ in generated} | {"index"}
        for stale in OUT.glob("*.scad"):
            if stale.stem not in keep:
                stale.unlink()
                print(f"Removed stale {stale.name}", file=sys.stderr)
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
        write_key(generated, unlabeled)

    total_pts = sum(n for *_, n, _ in generated)
    print(f"Generated {len(generated)} countries, {total_pts} vertices total.")
    if skipped:
        print(f"\nSkipped {len(skipped)} below {MIN_AREA_MM2} mm² "
              f"(too small at {MAP_WIDTH_MM:.0f} mm map width):")
        for iso, name, area in sorted(skipped, key=lambda s: -s[2]):
            print(f"  {iso}  {name:<32} {area:6.1f} mm²")
    if tight_labels:
        print(f"\n{len(tight_labels)} pieces too small even for the ISO code (blank):")
        for iso, name, _ in tight_labels:
            print(f"  {iso}  {name}")
    if args.report:
        print("\nLargest islands dropped (share of country area):")
        worst = sorted(generated, key=lambda g: -g[4])[:15]
        for iso, name, _, _, share in worst:
            if share > 0.01:
                print(f"  {iso}  {name:<32} {share:5.1%}")


if __name__ == "__main__":
    main()
