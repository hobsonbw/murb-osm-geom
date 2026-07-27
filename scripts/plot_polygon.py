"""Quick preview of a single WKT polygon.

Usage:
    python scripts/plot_polygon.py [wkt_file] [output_png]

Defaults: reads tmp_poly.wkt, writes data/outputs/polygon_preview.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely import wkt
from shapely.geometry import Polygon


def main() -> None:
    wkt_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tmp_poly.wkt")
    out_png = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/outputs/polygon_preview.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)

    geom = wkt.loads(wkt_file.read_text().strip())

    fig, ax = plt.subplots(figsize=(8, 8))
    ext = list(geom.exterior.coords)
    xs, ys = zip(*ext)

    # Build a compound Path so holes render as true courtyards.
    verts = list(ext) + [(0.0, 0.0)]
    codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(ext) - 1) + [MplPath.CLOSEPOLY]
    for interior in geom.interiors:
        ic = list(interior.coords)
        verts += ic + [(0.0, 0.0)]
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ic) - 1) + [MplPath.CLOSEPOLY]

    patch = PathPatch(MplPath(verts, codes),
                      facecolor="#7aa6d6", edgecolor="#123",
                      lw=1.2, alpha=0.7)
    ax.add_patch(patch)

    ax.plot(xs, ys, "o", color="#c0392b", ms=3,
            label=f"exterior verts ({len(ext)-1})")
    for interior in geom.interiors:
        ix, iy = zip(*interior.coords)
        ax.plot(ix, iy, "s", color="#27ae60", ms=3,
                label=f"hole verts ({len(interior.coords)-1})")

    mrr = geom.minimum_rotated_rectangle
    mx, my = zip(*mrr.exterior.coords)
    ax.plot(mx, my, "--", color="#333", lw=1, label="min rotated rect")

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("X (m, EPSG:3978)")
    ax.set_ylabel("Y (m, EPSG:3978)")
    court = sum(Polygon(r).area for r in geom.interiors)
    ax.set_title(
        f"Building footprint\n"
        f"area={geom.area:.0f} m^2   perim={geom.length:.0f} m   "
        f"courtyard={court:.0f} m^2   holes={len(list(geom.interiors))}"
    )
    ax.legend(loc="lower right", fontsize=8)

    plt.savefig(out_png, dpi=140, bbox_inches="tight")
    print(f"Wrote {out_png}")
    print(f"Exterior vertices: {len(ext) - 1}")
    print(f"Interior rings:    {len(list(geom.interiors))}")
    print(f"Area:              {geom.area:.2f} m^2")
    print(f"Perimeter:         {geom.length:.2f} m")
    print(f"Courtyard area:    {court:.2f} m^2")


if __name__ == "__main__":
    main()
