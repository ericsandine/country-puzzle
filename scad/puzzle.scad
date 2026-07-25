// puzzle.scad — main entry point for the world-map country puzzle.
//
// Preview:  open this file in OpenSCAD.
// Export:   openscad -o export/<name>.stl -D 'PART="base"' scad/puzzle.scad
//
// Country polygon data is generated into scad/countries/ by
// scripts/generate_countries.py (Natural Earth GeoJSON → Mercator mm).

include <piece.scad>
include <countries/index.scad>

// ---- Map parameters ----
// NOTE: the actual scale is baked into scad/countries/ by the generator
// (MAP_WIDTH_MM in scripts/generate_countries.py). This constant is
// informational; change it there and regenerate.
MAP_WIDTH = 800;

PART = "all";   // "all" | "base" | "label" — for per-color export
SHOW = "all";   // "all" | an ADM0_A3 code like "FRA"

if (SHOW == "all")
    all_countries(PART);
else
    country(SHOW, PART);
