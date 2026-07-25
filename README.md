# Country Puzzle

A 3D-printable world map jigsaw puzzle. Every country is its own puzzle piece:

- **Base piece**: white filament, extruded from the country's Mercator-projected outline
- **Label**: the country name embossed on top in a contrasting color (black)
- **Projection**: Mercator, full world map
- **Design tool**: OpenSCAD (parametric, everything code-driven)
- **Slicing/printing**: Bambu Studio (multi-color via AMS or filament-change)

## Repository layout

```
country-puzzle/
├── scad/                    # OpenSCAD sources
│   ├── puzzle.scad          # Main entry point — renders pieces / the whole map
│   ├── piece.scad           # piece() module: outline extrusion + embossed label
│   └── countries/           # Generated per-country polygon data (.scad)
├── scripts/
│   └── generate_countries.py  # GeoJSON → Mercator-projected OpenSCAD polygons
├── data/                    # Source geodata (Natural Earth GeoJSON), gitignored raw
├── export/                  # STL/3MF exports for Bambu Studio (gitignored)
└── tools/
    └── OpenSCAD-MCP-Server/ # MCP server for OpenSCAD (vendored, own venv)
```

## Workflow

1. `scripts/generate_countries.py` converts country boundary GeoJSON (Natural Earth)
   into Mercator-projected 2D polygons as OpenSCAD data files in `scad/countries/`.
2. `scad/piece.scad` turns a polygon + name into a printable piece:
   base plate (white) + raised text (black), as two bodies so Bambu Studio can
   assign a filament to each.
3. `scad/puzzle.scad` composes pieces — render one piece, a continent, or the
   full map; export STL/3MF per piece or per print plate.
4. Slice in Bambu Studio; color the text bodies black, bases white.

## Print design notes

- Piece base thickness: 4 mm; label raised 0.8 mm (4 text layers at 0.2 mm).
- Alternative single-extruder trick: pause/filament-change at the text layer.
- Small countries will need a minimum-size floor or grouped pieces (TBD).

## OpenSCAD

Local install: `/Applications/OpenSCAD-2021.01.app` (CLI at
`/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD`).

## Setup: OpenSCAD MCP server

`tools/OpenSCAD-MCP-Server/` is a separate clone (gitignored — it keeps its
own `.git`):

```sh
git clone https://github.com/jhacksman/OpenSCAD-MCP-Server.git tools/OpenSCAD-MCP-Server
cd tools/OpenSCAD-MCP-Server
python3 -m venv venv
# upstream requirements.txt is broken (git-pinned MCP SDK); use PyPI mcp:
./venv/bin/pip install mcp fastapi uvicorn "pydantic>=2" python-multipart \
  pillow requests httpx python-dotenv pyyaml jinja2 numpy tqdm zeroconf \
  aiohttp trimesh
```
