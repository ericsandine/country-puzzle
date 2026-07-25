#!/usr/bin/env python3
"""Export per-piece STLs (base + label bodies) for slicing in Bambu Studio.

For each generated country, runs OpenSCAD twice on scad/puzzle.scad:
  export/pieces/<ISO>_base.stl   (white filament)
  export/pieces/<ISO>_label.stl  (black filament)
Import both into Bambu Studio as one object ("Yes" to the split-object
prompt merges them), then assign filaments per body.

Usage:
  python3 scripts/export_pieces.py             # all countries
  python3 scripts/export_pieces.py FRA DEU     # specific countries
"""

import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = pathlib.Path(__file__).resolve().parent.parent
OPENSCAD = "/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD"
PUZZLE = REPO / "scad" / "puzzle.scad"
OUT = REPO / "export" / "pieces"


def export_one(iso: str, part: str) -> tuple[str, bool, str]:
    out = OUT / f"{iso}_{part}.stl"
    proc = subprocess.run(
        [OPENSCAD, "-o", str(out),
         "-D", f'SHOW="{iso}"', "-D", f'PART="{part}"', str(PUZZLE)],
        capture_output=True, text=True,
    )
    if part == "label" and "top level object is empty" in proc.stderr:
        # Piece too small for any label — legitimately has no black body.
        out.unlink(missing_ok=True)
        return f"{iso}_{part}", True, ""
    ok = proc.returncode == 0 and out.exists() and out.stat().st_size > 100
    return f"{iso}_{part}", ok, proc.stderr.strip().splitlines()[-1] if not ok else ""


def main() -> None:
    countries = sys.argv[1:] or sorted(
        p.stem for p in (REPO / "scad" / "countries").glob("*.scad")
        if p.stem != "index"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(iso, part) for iso in countries for part in ("base", "label")]
    failed = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (name, ok, err) in enumerate(
            pool.map(lambda j: export_one(*j), jobs), 1
        ):
            if not ok:
                failed.append((name, err))
            print(f"\r{i}/{len(jobs)} exported", end="", flush=True)
    print()
    if failed:
        print(f"{len(failed)} FAILED:")
        for name, err in failed:
            print(f"  {name}: {err}")
        sys.exit(1)
    print(f"OK — {len(countries)} pieces in {OUT}")


if __name__ == "__main__":
    main()
