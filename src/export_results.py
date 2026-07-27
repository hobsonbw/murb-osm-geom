"""Export the final MURB geometry dataset to CSV, GeoPackage, and GeoJSON."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .utils import ensure_dir, get_logger, resolve_path


LOGGER = get_logger()


# Canonical output column order (matches requirements.md).
OUTPUT_COLUMNS: list[str] = [
    "osmid",
    "building_type",
    "murb_confidence",
    "murb_reason",
    "footprint_area_m2",
    "perimeter_m",
    "length_m",
    "width_m",
    "aspect_ratio",
    "height_m",
    "height_est_m",
    "height_source",
    "levels",
    "levels_est",
    "levels_source",
    "gross_floor_area_est_m2",
    "compactness",
    "rectangularity",
    "courtyard_area_m2",
    "courtyard_ratio",
    "vertex_count",
    "shape_class",
    "shape_confidence",
]


def _prepare(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = None
    ordered = OUTPUT_COLUMNS + ["geometry"]
    return out[ordered]


def export_results(
    gdf: gpd.GeoDataFrame,
    settings: dict[str, Any],
    basename: str = "ottawa_murbs",
) -> dict[str, Path]:
    outputs_dir = ensure_dir(resolve_path(settings["paths"]["outputs_dir"]))
    if gdf.empty:
        LOGGER.warning("No records to export; skipping output writes")
        return {}

    prepared = _prepare(gdf)
    csv_path = outputs_dir / f"{basename}.csv"
    gpkg_path = outputs_dir / f"{basename}.gpkg"
    geojson_path = outputs_dir / f"{basename}.geojson"

    # ---- CSV (drop geometry, keep WKT for portability) --------------------
    csv_frame = pd.DataFrame(prepared.drop(columns=["geometry"]))
    csv_frame["geometry_wkt"] = prepared.geometry.to_wkt()
    csv_frame.to_csv(csv_path, index=False)
    LOGGER.info("Wrote %s (%d rows)", csv_path, len(csv_frame))

    # ---- GeoPackage (working CRS) -----------------------------------------
    prepared.to_file(gpkg_path, driver="GPKG", layer=basename)
    LOGGER.info("Wrote %s", gpkg_path)

    # ---- GeoJSON (reprojected to WGS84 for portability) -------------------
    out_crs = settings["crs"].get("output_geojson", "EPSG:4326")
    prepared_wgs = prepared.to_crs(out_crs)
    prepared_wgs.to_file(geojson_path, driver="GeoJSON")
    LOGGER.info("Wrote %s", geojson_path)

    return {"csv": csv_path, "gpkg": gpkg_path, "geojson": geojson_path}
