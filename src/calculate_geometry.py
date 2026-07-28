"""Compute geometry metrics for each building footprint.

All calculations assume `gdf` is in a projected CRS whose units are metres
(EPSG:3978 by default). See `preprocess.preprocess()`.

Adds columns:
    footprint_area_m2
    perimeter_m
    length_m, width_m, average_depth_m, aspect_ratio
    bbox_area_m2
    compactness             = 4*pi*A / P^2
    rectangularity          = A / bbox_area
    courtyard_area_m2       = sum of interior ring areas
    courtyard_ratio         = courtyard_area / (footprint + courtyard)
    vertex_count            = total exterior + interior vertices
    gross_floor_area_est_m2 = footprint * levels_est
"""

from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from skimage.draw import polygon as raster_polygon
from skimage.morphology import medial_axis

from .utils import get_logger


LOGGER = get_logger()

# Building depth calculation parameters
RASTER_RESOLUTION = 0.5
MIN_BRANCH_LENGTH = 10.0


def _min_rect_dims(geom: BaseGeometry) -> tuple[float, float]:
    """Return (length, width) of the minimum rotated rectangle in metres."""
    if geom is None or geom.is_empty:
        return (np.nan, np.nan)
    mrr = geom.minimum_rotated_rectangle
    if not hasattr(mrr, "exterior") or mrr.exterior is None:
        return (np.nan, np.nan)
    coords = list(mrr.exterior.coords)
    if len(coords) < 4:
        return (np.nan, np.nan)
    # Rectangle: 4 unique corners + repeated first. Edges 0-1 and 1-2 are
    # the two side lengths.
    def _dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
    e1 = _dist(coords[0], coords[1])
    e2 = _dist(coords[1], coords[2])
    length, width = max(e1, e2), min(e1, e2)
    return (length, width)


def _courtyard_area(geom: BaseGeometry) -> float:
    """Sum of interior (hole) ring areas across a (Multi)Polygon."""
    if geom is None or geom.is_empty:
        return 0.0
    if isinstance(geom, Polygon):
        return float(sum(Polygon(r).area for r in geom.interiors))
    if isinstance(geom, MultiPolygon):
        return float(sum(
            Polygon(r).area for p in geom.geoms for r in p.interiors
        ))
    return 0.0


def _vertex_count(geom: BaseGeometry) -> int:
    if geom is None or geom.is_empty:
        return 0
    if isinstance(geom, Polygon):
        n = len(geom.exterior.coords) - 1  # closed ring repeats first point
        for r in geom.interiors:
            n += len(r.coords) - 1
        return int(n)
    if isinstance(geom, MultiPolygon):
        return int(sum(_vertex_count(p) for p in geom.geoms))
    return 0


def _polygon_to_raster(poly: Polygon, resolution: float = 0.5, padding: int = 5) -> np.ndarray:
    """Convert a polygon to a binary raster for depth calculation."""
    minx, miny, maxx, maxy = poly.bounds
    width = int(np.ceil((maxx - minx) / resolution)) + 2 * padding
    height = int(np.ceil((maxy - miny) / resolution)) + 2 * padding
    raster = np.zeros((height, width), dtype=bool)

    coords = np.array(poly.exterior.coords)
    x = (coords[:, 0] - minx) / resolution + padding
    y = (coords[:, 1] - miny) / resolution + padding

    rr, cc = raster_polygon(y, x, raster.shape)
    raster[rr, cc] = True

    return raster


def _get_branches(binary: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    """Extract skeleton branches and distance transform for depth calculation."""
    skeleton, distance = medial_axis(binary, return_distance=True)

    kernel = np.ones((3, 3), dtype=int)
    neighbour_count = (
        ndimage.convolve(skeleton.astype(int), kernel, mode="constant")
        - skeleton.astype(int)
    )

    branch_nodes = skeleton & (neighbour_count > 2)
    segments = skeleton & (~branch_nodes)
    labels, n_labels = ndimage.label(segments)

    return labels, n_labels, distance


def _calculate_average_depth(
    geom: BaseGeometry,
    resolution: float = RASTER_RESOLUTION,
    min_branch_length: float = MIN_BRANCH_LENGTH,
) -> float:
    """Calculate average building depth using medial axis skeleton.
    
    Returns the weighted average depth across all significant skeleton branches,
    with fallback to simple area/perimeter estimate for degenerate cases.
    """
    if geom is None or geom.is_empty or not isinstance(geom, Polygon):
        return np.nan

    try:
        raster = _polygon_to_raster(geom, resolution=resolution)
        labels, n_labels, distance = _get_branches(raster)

        branch_lengths = []
        branch_depths = []

        for label_id in range(1, n_labels + 1):
            mask = labels == label_id
            branch_length = mask.sum() * resolution

            # Remove tiny skeleton spurs
            if branch_length < min_branch_length:
                continue

            depths = 2.0 * distance[mask] * resolution
            branch_lengths.append(branch_length)
            branch_depths.append(depths.mean())

        if len(branch_lengths) == 0:
            # Fallback: simple area/perimeter estimate
            return geom.area / max(geom.length / 4.0, 1.0)

        return float(np.average(branch_depths, weights=branch_lengths))

    except Exception:
        return np.nan


def calculate_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf

    LOGGER.info("Computing geometry metrics for %d buildings", len(gdf))
    gdf = gdf.copy()

    area = gdf.geometry.area
    perim = gdf.geometry.length

    gdf["footprint_area_m2"] = area
    gdf["perimeter_m"] = perim

    dims = gdf.geometry.apply(_min_rect_dims)
    gdf["length_m"] = [d[0] for d in dims]
    gdf["width_m"] = [d[1] for d in dims]

    # Average building depth using medial axis skeleton
    LOGGER.info("Computing average building depths")
    gdf["average_depth_m"] = gdf.geometry.apply(_calculate_average_depth)

    # Aspect ratio: length / width. Guard against zero-width degeneracies.
    with np.errstate(divide="ignore", invalid="ignore"):
        gdf["aspect_ratio"] = np.where(
            gdf["width_m"].to_numpy() > 0,
            gdf["length_m"].to_numpy() / gdf["width_m"].to_numpy(),
            np.nan,
        )

    gdf["bbox_area_m2"] = gdf["length_m"] * gdf["width_m"]

    with np.errstate(divide="ignore", invalid="ignore"):
        gdf["compactness"] = np.where(
            perim.to_numpy() > 0,
            (4.0 * math.pi * area.to_numpy()) / (perim.to_numpy() ** 2),
            np.nan,
        )
        gdf["rectangularity"] = np.where(
            gdf["bbox_area_m2"].to_numpy() > 0,
            area.to_numpy() / gdf["bbox_area_m2"].to_numpy(),
            np.nan,
        )

    courtyard = gdf.geometry.apply(_courtyard_area)
    gdf["courtyard_area_m2"] = courtyard
    total = area + courtyard
    with np.errstate(divide="ignore", invalid="ignore"):
        gdf["courtyard_ratio"] = np.where(
            total.to_numpy() > 0,
            courtyard.to_numpy() / total.to_numpy(),
            0.0,
        )

    gdf["vertex_count"] = gdf.geometry.apply(_vertex_count).astype("Int64")

    # Gross floor area estimate (needs levels_est produced upstream).
    if "levels_est" in gdf.columns:
        gdf["gross_floor_area_est_m2"] = gdf["footprint_area_m2"] * gdf["levels_est"]
    else:
        gdf["gross_floor_area_est_m2"] = np.nan

    return gdf
