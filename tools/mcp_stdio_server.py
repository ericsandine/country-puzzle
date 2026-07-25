"""Stdio MCP server exposing OpenSCAD render/export tools.

Upstream src/main.py targets an MCP API that never shipped in the official
python SDK (`from mcp import MCPServer` — no such class), so it cannot run.
This shim provides the OpenSCAD functionality we actually need over the
official SDK's FastMCP stdio transport.

Registered in the project's .mcp.json. The OpenSCAD binary is resolved from
$OPENSCAD_PATH, falling back to the macOS app bundle CLI.
"""

import os
import subprocess

from mcp.server.fastmcp import FastMCP

OPENSCAD = os.environ.get(
    "OPENSCAD_PATH",
    "/Applications/OpenSCAD-2021.01.app/Contents/MacOS/OpenSCAD",
)

mcp = FastMCP("openscad")


def _run(args: list[str], timeout: int = 300) -> str:
    proc = subprocess.run(
        [OPENSCAD, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSCAD failed (exit {proc.returncode}):\n{output}")
    return output


def _defines(defines: dict[str, str] | None) -> list[str]:
    # Values are passed verbatim: use '"base"' for strings, '4.2' for numbers.
    return [x for k, v in (defines or {}).items() for x in ("-D", f"{k}={v}")]


@mcp.tool()
def render_preview(
    scad_file: str,
    output_png: str,
    defines: dict[str, str] | None = None,
    imgsize: str = "1024,768",
    camera: str | None = None,
) -> str:
    """Render a .scad file to a PNG preview image.

    defines: OpenSCAD -D overrides, e.g. {"PART": '"label"', "MAP_WIDTH": "800"}
    camera: optional OpenSCAD --camera spec (translate_x,y,z,rot_x,y,z,dist);
    omitted → autocenter/viewall.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_png)), exist_ok=True)
    args = ["-o", output_png, f"--imgsize={imgsize}", *_defines(defines)]
    args += [f"--camera={camera}"] if camera else ["--autocenter", "--viewall"]
    log = _run([*args, scad_file])
    return f"Rendered {output_png}\n{log}"


@mcp.tool()
def export_model(
    scad_file: str,
    output_file: str,
    defines: dict[str, str] | None = None,
) -> str:
    """Export a .scad file to STL/3MF/AMF/OFF/CSG (format from extension).

    Use defines to select per-color bodies, e.g. {"PART": '"base"'}.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    log = _run(["-o", output_file, *_defines(defines), scad_file], timeout=1800)
    size = os.path.getsize(output_file)
    return f"Exported {output_file} ({size} bytes)\n{log}"


@mcp.tool()
def check_scad(scad_file: str, defines: dict[str, str] | None = None) -> str:
    """Syntax/render-check a .scad file without producing a model.

    Compiles to a throwaway CSG term tree; returns OpenSCAD warnings/errors.
    """
    out = os.path.join("/tmp", "openscad_check.term")
    log = _run(["-o", out, *_defines(defines), scad_file])
    return log or "OK — no warnings"


@mcp.tool()
def openscad_version() -> str:
    """Report the OpenSCAD binary path and version in use."""
    proc = subprocess.run([OPENSCAD, "--version"], capture_output=True, text=True)
    return f"{OPENSCAD}\n{(proc.stdout + proc.stderr).strip()}"


if __name__ == "__main__":
    mcp.run()
