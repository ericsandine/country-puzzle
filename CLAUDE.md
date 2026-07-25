# Country Puzzle — project notes

3D-printable world-map jigsaw: one piece per country, white base, country name
embossed on top in black. Mercator projection. Designed in OpenSCAD, sliced in
Bambu Studio.

## Key facts

- OpenSCAD CLI: `/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD`
  (no `openscad` on PATH).
- Export per-color bodies via `-D 'PART="base"'` / `-D 'PART="label"'` on
  `scad/puzzle.scad`; merge as one object with two filaments in Bambu Studio.
- Map scale lives in two places: `MAP_WIDTH` in `scad/puzzle.scad` and
  `MAP_WIDTH_MM` in `scripts/generate_countries.py` — keep them in sync.
- Country data is generated, never hand-edited: `scad/countries/` comes from
  `scripts/generate_countries.py` (Natural Earth 50m admin-0 GeoJSON).
- `tools/OpenSCAD-MCP-Server/` is a vendored clone with its own venv
  (gitignored). Its upstream requirements are broken (git-pinned MCP SDK);
  we install a trimmed dependency set instead.

## Print parameters (scad/piece.scad)

- Base 4 mm white, label raised 0.8 mm black (4 × 0.2 mm layers).
- Minimum label text size 4 mm for printability.

## Country data pipeline

- Regenerate: `.venv/bin/python scripts/generate_countries.py` (repo venv with
  shapely; Natural Earth GeoJSON auto-downloads to `data/raw/`).
- Select what to render with `-D 'SHOW="FRA"'` (ADM0_A3 code) or `SHOW="all"`.
- At 800 mm map width only 135/242 countries clear the 25 mm² floor; scale
  and small-country strategy are open design questions.
- OpenCSG preview (F5/PNG default) shows z-fighting artifacts on the
  label-clip intersection — use `--render` to judge real geometry.

## Commands

```sh
# Preview render (PNG) of current puzzle.scad
/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD \
  -o export/preview.png --autocenter --viewall scad/puzzle.scad

# Export bodies for slicing
/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD \
  -o export/piece_base.stl -D 'PART="base"' scad/puzzle.scad
```
