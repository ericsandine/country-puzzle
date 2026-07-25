// puzzle.scad — main entry point for the world-map country puzzle.
//
// Preview:  open this file in OpenSCAD.
// Export:   openscad -o export/<name>.stl -D 'PART="base"' scad/puzzle.scad
//
// Country polygon data is generated into scad/countries/ by
// scripts/generate_countries.py (Natural Earth GeoJSON → Mercator mm).

include <piece.scad>

// ---- Map parameters ----
MAP_WIDTH = 800;   // full world width in mm (drives generator scale)
PART = "all";      // "all" | "base" | "label" — for per-color export

// ---- Demo piece (placeholder until scad/countries/ is generated) ----
// A rough, recognizable placeholder outline so the pipeline can be tested
// end to end before real country data exists.
DEMO_POINTS = [
    [0, 0], [40, -5], [55, 10], [60, 35], [45, 45],
    [30, 40], [20, 48], [8, 42], [-5, 30], [-8, 12]
];

piece(
    name       = "DEMOLAND",
    points     = DEMO_POINTS,
    label_pos  = [26, 20],
    label_size = 6,
    part       = PART
);
