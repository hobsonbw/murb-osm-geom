"""Extract and estimate building height / storey information from OSM tags.

Adds columns:
    height_m         - parsed OSM `height` tag (metres, float or NaN)
    height_est_m     - best available height (explicit or from levels)
    height_source    - explicit_height | building_levels | estimated | none
    levels           - parsed OSM `building:levels` (int or NaN)
    levels_est       - best available levels (explicit or from height)
    levels_source    - explicit_levels | from_height | estimated | none
"""

from __future__ import annotations

import re
from typing import Any

import geopandas as gpd
import numpy as np


_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


def _parse_height(value: Any) -> float:
    """Parse OSM height strings like '12', '12.5', '12 m', '~10', '40 ft'."""
    if value is None:
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        v = float(value)
        return v if v > 0 else np.nan
    s = str(value).strip().lower()
    if not s or s in {"nan", "none"}:
        return np.nan
    m = _NUM_RE.search(s)
    if not m:
        return np.nan
    try:
        v = float(m.group(0))
    except ValueError:
        return np.nan
    if "ft" in s or "'" in s:  # feet -> metres
        v *= 0.3048
    return v if v > 0 else np.nan


def _parse_int(value: Any) -> float:
    """Parse integer-ish OSM tags into a float (NaN on failure) for pandas."""
    if value is None:
        return np.nan
    if isinstance(value, (int, np.integer)):
        return float(value)
    if isinstance(value, float):
        return value if not np.isnan(value) else np.nan
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return np.nan
    m = _NUM_RE.search(s)
    if not m:
        return np.nan
    try:
        return float(int(float(m.group(0))))
    except ValueError:
        return np.nan


def estimate_heights(
    gdf: gpd.GeoDataFrame,
    settings: dict[str, Any],
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf

    ff = float(settings["height"]["floor_to_floor_m"])
    sh = float(settings["height"]["storey_from_height_m"])

    for col in ("height", "roof:height", "building:levels"):
        if col not in gdf.columns:
            gdf[col] = None

    gdf = gdf.copy()

    # ---- Parse raw tags --------------------------------------------------
    gdf["height_m"] = gdf["height"].apply(_parse_height)
    roof_h = gdf["roof:height"].apply(_parse_height)
    gdf["levels"] = gdf["building:levels"].apply(_parse_int)

    # ---- Height estimation ------------------------------------------------
    height_est = np.full(len(gdf), np.nan)
    height_source = np.array(["none"] * len(gdf), dtype=object)

    # explicit_height (add roof height if separately tagged)
    m_explicit = gdf["height_m"].notna()
    height_est[m_explicit] = gdf.loc[m_explicit, "height_m"].to_numpy()
    # Roof height, when tagged separately, adds to structural height.
    m_roof = m_explicit & roof_h.notna()
    height_est[m_roof] = height_est[m_roof] + roof_h[m_roof].to_numpy()
    height_source[m_explicit] = "explicit_height"

    # building_levels
    m_from_levels = (~m_explicit) & gdf["levels"].notna()
    height_est[m_from_levels] = gdf.loc[m_from_levels, "levels"].to_numpy() * ff
    height_source[m_from_levels] = "building_levels"

    gdf["height_est_m"] = height_est
    gdf["height_source"] = height_source

    # ---- Levels estimation ------------------------------------------------
    levels_est = np.full(len(gdf), np.nan)
    levels_source = np.array(["none"] * len(gdf), dtype=object)

    m_expl_lvl = gdf["levels"].notna()
    levels_est[m_expl_lvl] = gdf.loc[m_expl_lvl, "levels"].to_numpy()
    levels_source[m_expl_lvl] = "explicit_levels"

    m_from_h = (~m_expl_lvl) & gdf["height_m"].notna()
    if m_from_h.any():
        est = np.round(gdf.loc[m_from_h, "height_m"].to_numpy() / sh)
        est = np.clip(est, 1, None)
        levels_est[m_from_h] = est
        levels_source[m_from_h] = "from_height"

    gdf["levels_est"] = levels_est
    gdf["levels_source"] = levels_source

    return gdf
