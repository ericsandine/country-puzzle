// piece.scad — one puzzle piece: country outline base + embossed name label.
//
// Each piece is made of two bodies so Bambu Studio can assign a filament
// to each: base (white) and label (black). Export them separately (see
// puzzle.scad PART parameter) and merge into one object in Bambu Studio,
// or print single-color with a filament change at the label layer.

// ---- Global print parameters (mm) ----
BASE_THICKNESS = 4;    // white body height
LABEL_HEIGHT   = 0.8;  // raised text: 4 layers at 0.2 mm
LABEL_FONT     = "Liberation Sans:style=Bold";
MIN_LABEL_SIZE = 4;    // don't shrink text below this (printability floor)
CLEARANCE      = 0.15; // per-piece inset so adjacent pieces fit, not fuse

// A piece's polygon comes in map millimetres (already Mercator-projected
// and scaled by scripts/generate_countries.py).

// Country footprint, inset by CLEARANCE on all sides. Neighboring countries
// share border vertices in the source data, so each piece giving up
// CLEARANCE yields a 2*CLEARANCE joint gap. r-offset (not delta) keeps
// jagged coastline vertices from self-intersecting.
module footprint(points, paths = undef) {
    offset(r = -CLEARANCE)
        polygon(points = points, paths = paths);
}

// Base body: the country outline, extruded.
// points/paths as accepted by polygon().
module piece_base(points, paths = undef) {
    linear_extrude(height = BASE_THICKNESS)
        footprint(points, paths);
}

// Label body: country name centered at label_pos, sitting on top of the base.
// label_pos: [x, y] anchor in map mm (use polygon centroid / pole of
// inaccessibility from the generator). size: text height in mm.
// rot: optional rotation for long names in narrow countries.
module piece_label(name, label_pos, size = 6, rot = 0) {
    translate([label_pos[0], label_pos[1], BASE_THICKNESS])
        linear_extrude(height = LABEL_HEIGHT)
            rotate([0, 0, rot])
                text(name,
                     size = max(size, MIN_LABEL_SIZE),
                     font = LABEL_FONT,
                     halign = "center",
                     valign = "center");
}

// Complete piece. part = "all" | "base" | "label"
// (use "base"/"label" when exporting per-color STLs).
// The label is NOT clipped to the outline here: the generator only emits
// label text it has verified fits the piece (name → ISO code → blank),
// because text overflowing the outline would print as unsupported filament
// floating in air, and a runtime intersection() clip breaks OpenCSG
// previews (whole top renders black).
module piece(name, points, paths = undef, label_pos = [0, 0],
             label_size = 6, label_rot = 0, part = "all") {
    if (part == "all" || part == "base")
        color("white") piece_base(points, paths);
    if ((part == "all" || part == "label") && name != "" && label_size > 0)
        color("black") piece_label(name, label_pos, label_size, label_rot);
}
