"""Batch-plot every polygon in a MURB CSV, one PNG per osmid.

Usage:
    python scripts/plot_all_polygons.py [csv_path] [out_dir]

Defaults: data/outputs/kingston_smoke_subset.csv -> data/outputs/polygon_plots/
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely import wkt
from shapely.geometry import MultiPolygon, Polygon


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(osmid: object) -> str:
    """Make an osmid safe for a Windows filename."""
    return _SAFE_CHARS.sub("_", str(osmid)).strip("_") or "unknown"


def _polygons(geom):
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return []


def _plot_one(geom, meta: dict, out_path: Path) -> None:
    parts = _polygons(geom)
    if not parts:
        return

    fig, ax = plt.subplots(figsize=(6, 6))

    verts: list[tuple[float, float]] = []
    codes: list[int] = []
    ext_pts: list[tuple[float, float]] = []
    int_pts: list[tuple[float, float]] = []
    for poly in parts:
        ext = list(poly.exterior.coords)
        ext_pts.extend(ext[:-1])
        verts += ext + [(0.0, 0.0)]
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ext) - 1) + [MplPath.CLOSEPOLY]
        for interior in poly.interiors:
            ic = list(interior.coords)
            int_pts.extend(ic[:-1])
            verts += ic + [(0.0, 0.0)]
            codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ic) - 1) + [MplPath.CLOSEPOLY]

    ax.add_patch(PathPatch(MplPath(verts, codes),
                           facecolor="#7aa6d6", edgecolor="#123",
                           lw=1.0, alpha=0.7))

    if ext_pts:
        xs, ys = zip(*ext_pts)
        ax.plot(xs, ys, "o", color="#c0392b", ms=2)
    if int_pts:
        ix, iy = zip(*int_pts)
        ax.plot(ix, iy, "s", color="#27ae60", ms=2)

    mrr = geom.minimum_rotated_rectangle
    if hasattr(mrr, "exterior") and mrr.exterior is not None:
        mx, my = zip(*mrr.exterior.coords)
        ax.plot(mx, my, "--", color="#333", lw=0.9)

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=7)

    title = (
        f"osmid={meta['osmid']}  |  {meta['shape_class']}\n"
        f"area={meta['footprint_area_m2']:.0f} m^2   "
        f"aspect={meta['aspect_ratio']:.2f}   "
        f"rect={meta['rectangularity']:.2f}   "
        f"court={meta['courtyard_area_m2']:.0f} m^2"
    )
    ax.set_title(title, fontsize=9)

    plt.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else Path("data/outputs/kingston_smoke_subset.csv")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 \
        else Path("data/outputs/polygon_plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} rows from {csv_path}")

    ok = 0
    skipped = 0
    for i, row in enumerate(df.itertuples(index=False), start=1):
        rec = row._asdict()
        wkt_str = rec.get("geometry_wkt")
        if not isinstance(wkt_str, str) or not wkt_str.strip():
            skipped += 1
            continue
        try:
            geom = wkt.loads(wkt_str)
        except Exception as err:  # noqa: BLE001
            print(f"  [skip] osmid={rec.get('osmid')} WKT parse failed: {err}")
            skipped += 1
            continue

        name = _safe_name(rec.get("osmid"))
        out_path = out_dir / f"{name}.png"
        _plot_one(geom, rec, out_path)
        ok += 1
        if i % 50 == 0:
            print(f"  ...{i}/{len(df)}")

    print(f"Done. Wrote {ok} PNGs to {out_dir} (skipped {skipped}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
