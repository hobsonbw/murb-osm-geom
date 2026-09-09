"""Clean and standardise the raw OSM building layer.

Steps:
    * drop null / empty geometries
    * repair invalid polygons (buffer(0) fallback via `make_valid`)
    * keep only (Multi)Polygon geometries (OSM sometimes returns points/lines
      tagged with `building=*` for annotation nodes)
    * drop exact duplicates by osmid
    * project to the working (metric) CRS
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import make_valid

from .utils import ensure_dir, get_logger, resolve_path


LOGGER = get_logger()


def _osmid_column(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ensure a stable `osmid` column exists (osmnx v2 uses 'id' or index)."""
    if "osmid" in gdf.columns:
        return gdf
    for candidate in ("id", "osm_id"):
        if candidate in gdf.columns:
            gdf = gdf.rename(columns={candidate: "osmid"})
            return gdf
    # Fallback: synthesize from element_type + running index.
    et = gdf["element_type"] if "element_type" in gdf.columns else "unk"
    gdf = gdf.copy()
    gdf["osmid"] = [f"{t}/{i}" for i, t in enumerate(et)] if hasattr(et, "__iter__") \
        else list(range(len(gdf)))
    return gdf


def preprocess(gdf: gpd.GeoDataFrame, settings: dict[str, Any]) -> gpd.GeoDataFrame:
    if gdf.empty:
        LOGGER.warning("Preprocess called on empty GeoDataFrame")
        return gdf

    working_crs = settings["crs"]["working"]
    processed_dir = ensure_dir(resolve_path(settings["paths"]["processed_dir"]))

    n0 = len(gdf)
    gdf = _osmid_column(gdf)

    # Drop null / empty geometries.
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    LOGGER.info("Dropped %d null/empty geometries", n0 - len(gdf))

    # Keep only polygonal features.
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    dropped_non_poly = int((~poly_mask).sum())
    gdf = gdf[poly_mask].copy()
    if dropped_non_poly:
        LOGGER.info("Dropped %d non-polygon features", dropped_non_poly)

    # Repair invalid geometries.
    invalid = ~gdf.geometry.is_valid
    n_invalid = int(invalid.sum())
    if n_invalid:
        LOGGER.info("Repairing %d invalid geometries", n_invalid)
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].apply(make_valid)
        # make_valid can return GeometryCollection; keep only polygonal parts.
        gdf["geometry"] = gdf["geometry"].apply(_coerce_to_polygonal)
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    # Deduplicate by osmid, keeping the first occurrence (tile overlap safety).
    before = len(gdf)
    gdf = gdf.drop_duplicates(subset=["osmid"]).reset_index(drop=True)
    LOGGER.info("Removed %d duplicate osmids", before - len(gdf))

    # Project to working CRS for metric calculations.
    if gdf.crs is None:
        LOGGER.warning("Input CRS missing; assuming EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs(working_crs)
    LOGGER.info("Projected to %s; %d features remain", working_crs, len(gdf))

    basename = settings.get("run", {}).get("basename", "study_area")
    out_path = processed_dir / f"{basename}_buildings_clean.gpkg"
    # Persist a version with only geometry + osmid + raw tags of interest to
    # keep the cached file small enough for GDAL to write reliably.
    _persist_clean(gdf, out_path)
    LOGGER.info("Wrote %s", out_path)

    return gdf


def _coerce_to_polygonal(geom):
    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    # GeometryCollection: extract polygon parts.
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]
    flat: list[Polygon] = []
    for g in polys:
        if isinstance(g, MultiPolygon):
            flat.extend(g.geoms)
        else:
            flat.append(g)
    return MultiPolygon(flat)


def _persist_clean(gdf: gpd.GeoDataFrame, path) -> None:
    """Write a stringified copy of the cleaned dataset for reproducibility."""
    out = gdf.copy()
    for col in out.columns:
        if col == "geometry":
            continue
        if out[col].dtype == object:
            out[col] = out[col].astype(str)
    out.to_file(path, driver="GPKG")
