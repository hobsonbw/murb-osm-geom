"""Lightweight, rule-based shape classification.

Descriptive only - NOT an archetype assignment. Classes:
    Rectangle, Square, Slab, Tower, L, U, Courtyard, Irregular

Confidence is an approximate self-assessment based on how cleanly the
building's metrics fit the winning rule.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .utils import get_logger


LOGGER = get_logger()


def _classify_row(row: pd.Series, cfg: dict[str, Any]) -> tuple[str, float]:
    rect_hi = cfg["rectangularity_high"]
    rect_mid = cfg["rectangularity_mid"]
    sq_max = cfg["square_aspect_max"]
    slab_min = cfg["slab_aspect_min"]
    tower_lvls = cfg["tower_levels_min"]
    court_min = cfg["courtyard_ratio_min"]
    l_lo, l_hi = cfg["vertex_count_l_range"]
    u_lo, u_hi = cfg["vertex_count_u_range"]

    rect = row.get("rectangularity", np.nan)
    aspect = row.get("aspect_ratio", np.nan)
    court = row.get("courtyard_ratio", 0.0) or 0.0
    verts = row.get("vertex_count", np.nan)
    levels = row.get("levels_est", np.nan)

    # Courtyard beats everything else - it's a strong topological signal.
    if court >= court_min:
        conf = float(min(1.0, 0.6 + 2.0 * (court - court_min)))
        return ("Courtyard", conf)

    if np.isnan(rect) or np.isnan(aspect):
        return ("Irregular", 0.3)

    if rect >= rect_hi:
        # Highly rectangular footprint - decide sub-class by aspect + height.
        if aspect < sq_max:
            if not np.isnan(levels) and levels >= tower_lvls:
                return ("Tower", 0.85)
            return ("Square", 0.85)
        if aspect >= slab_min:
            return ("Slab", 0.85)
        return ("Rectangle", 0.9)

    if rect_mid <= rect < rect_hi and not np.isnan(verts):
        # Moderately rectangular with a modest vertex count = L or U.
        if l_lo <= verts <= l_hi:
            return ("L", 0.65)
        if u_lo <= verts <= u_hi:
            return ("U", 0.6)

    return ("Irregular", 0.4)


def classify_shapes(
    gdf: gpd.GeoDataFrame,
    settings: dict[str, Any],
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf

    LOGGER.info("Classifying shapes for %d buildings", len(gdf))
    cfg = settings["shape"]
    results = gdf.apply(lambda r: _classify_row(r, cfg), axis=1)

    gdf = gdf.copy()
    gdf["shape_class"] = [r[0] for r in results]
    gdf["shape_confidence"] = [r[1] for r in results]
    return gdf
