#!/usr/bin/env python3
"""Pack puzzle pieces onto printer build plates and write one 3MF per plate.

Reads the per-piece STLs from export/pieces/ (run export_pieces.py first),
shelf-packs them into PLATE_MM x PLATE_MM layouts (90-degree rotation
allowed), and writes export/plates/plate_NN.3mf. Each 3MF holds two mesh
objects: "bases_white" and "labels_black" (all pieces on the plate merged).

Bambu Studio: File > Import, pick a plate file, answer YES to "load as a
single object with multiple parts", then assign white filament to the
bases part and black to the labels part.

Pieces larger than the usable plate area in every orientation are reported
and skipped.

Usage:  .venv/bin/python scripts/make_plates.py [--plate 256]
"""

import argparse
import pathlib
import sys
import zipfile

import numpy as np
import trimesh

REPO = pathlib.Path(__file__).resolve().parent.parent
PIECES = REPO / "export" / "pieces"
OUT = REPO / "export" / "plates"

PLATE_MM = 256.0   # Bambu P2S bed
MARGIN = 8.0       # keep-out border of the plate
GAP = 3.0          # spacing between pieces


def load_pieces() -> list[tuple[str, trimesh.Trimesh, trimesh.Trimesh | None]]:
    pieces = []
    for base_path in sorted(PIECES.glob("*_base.stl")):
        iso = base_path.stem[:3]
        base = trimesh.load(base_path)
        label_path = PIECES / f"{iso}_label.stl"
        label = trimesh.load(label_path) if label_path.exists() else None
        pieces.append((iso, base, label))
    return pieces


def pack(pieces, usable: float):
    """Shelf-pack pieces (sorted tall-first, normalized landscape).

    Returns (plates, oversize) where each plate is a list of
    (iso, rotate90, shift_x, shift_y) placements and oversize is the list
    of pieces that fit no orientation.
    """
    items, oversize = [], []
    for iso, base, label in pieces:
        (x0, y0, _), (x1, y1, _) = base.bounds
        w, h = x1 - x0, y1 - y0
        rot = h > w  # normalize to landscape
        nw, nh = (h, w) if rot else (w, h)
        if nw > usable:  # longest side must fit the (square) usable area
            oversize.append((iso, w, h))
            continue
        items.append((nh, nw, iso, rot))

    plates, current = [], []
    x = y = row_h = 0.0
    for nh, nw, iso, rot in sorted(items, reverse=True):
        if x + nw > usable:
            x, y, row_h = 0.0, y + row_h + GAP, 0.0
        if y + nh > usable:
            plates.append(current)
            current, x, y, row_h = [], 0.0, 0.0, 0.0
        current.append((iso, rot, x, y))
        x += nw + GAP
        row_h = max(row_h, nh)
    if current:
        plates.append(current)
    return plates, oversize


def placed_mesh(mesh, base_bounds_before, rot, px, py):
    """Copy of mesh moved so the (rotated) base bbox min lands at (px, py).

    The same rotation/translation must apply to base and label, so the
    shift is computed from the base's bounds, not the mesh's own.
    """
    m = mesh.copy()
    if rot:
        m.apply_transform(
            trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1])
        )
    (bx0, by0), (bx1, by1) = base_bounds_before
    if rot:  # bbox min after rotating base about z: (-by1, bx0)
        shift = (px - (-by1), py - bx0)
    else:
        shift = (px - bx0, py - by0)
    m.apply_translation([shift[0], shift[1], 0])
    return m


def write_3mf(path: pathlib.Path, objects: list[tuple[str, trimesh.Trimesh]]):
    """Minimal core-spec 3MF: one mesh object per (name, mesh)."""
    parts = []
    for oid, (name, mesh) in enumerate(objects, start=1):
        verts = "".join(
            f'<vertex x="{x:.3f}" y="{y:.3f}" z="{z:.3f}"/>'
            for x, y, z in mesh.vertices
        )
        tris = "".join(
            f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
            for a, b, c in mesh.faces
        )
        parts.append(
            f'<object id="{oid}" type="model" name="{name}">'
            f"<mesh><vertices>{verts}</vertices>"
            f"<triangles>{tris}</triangles></mesh></object>"
        )
    items = "".join(
        f'<item objectid="{i}"/>' for i in range(1, len(objects) + 1)
    )
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f"<resources>{''.join(parts)}</resources>"
        f"<build>{items}</build></model>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plate", type=float, default=PLATE_MM,
                        help="build plate side length in mm")
    args = parser.parse_args()
    usable = args.plate - 2 * MARGIN

    pieces = load_pieces()
    if not pieces:
        sys.exit("No pieces in export/pieces/ — run export_pieces.py first")
    by_iso = {iso: (base, label) for iso, base, label in pieces}

    plates, oversize = pack(pieces, usable)
    OUT.mkdir(parents=True, exist_ok=True)

    for n, placements in enumerate(plates, start=1):
        bases, labels = [], []
        for iso, rot, px, py in placements:
            base, label = by_iso[iso]
            bb = base.bounds[:, :2]
            bases.append(placed_mesh(base, bb, rot, px, py))
            if label is not None:
                labels.append(placed_mesh(label, bb, rot, px, py))
        # Center the layout so slicers that recenter still show it nicely
        merged = trimesh.util.concatenate(bases)
        cx, cy = merged.bounds[:, :2].mean(axis=0)
        objects = [("bases_white", merged)]
        if labels:
            objects.append(("labels_black", trimesh.util.concatenate(labels)))
        for _, m in objects:
            m.apply_translation([-cx, -cy, 0])
        write_3mf(OUT / f"plate_{n:02d}.3mf", objects)
        isos = ", ".join(iso for iso, *_ in placements)
        print(f"plate_{n:02d}.3mf: {len(placements)} pieces ({isos})")

    print(f"\n{len(plates)} plates for {sum(map(len, plates))} pieces "
          f"({args.plate:.0f} mm bed, {usable:.0f} mm usable).")
    for iso, w, h in oversize:
        print(f"OVERSIZE, not plated: {iso} ({w:.0f} x {h:.0f} mm)")


if __name__ == "__main__":
    main()
