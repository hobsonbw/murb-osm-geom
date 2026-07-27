"""Identify likely MURBs from OSM building tags.

Rules produce a confidence in [0, 1] plus a human-readable reason string.
The thresholds/weights live in `config/settings.yaml` under `murb:`.

Output columns added: `building_type`, `murb_confidence`, `murb_reason`.
"""

from __future__ import annotations

import re
from typing import Any

import geopandas as gpd
import numpy as np

from .utils import get_logger


LOGGER = get_logger()

_INT_RE = re.compile(r"[-+]?\d+")


def _to_int(value: Any) -> int | None:
    """Parse a possibly-messy OSM integer tag like '3', ' 4 ', '5;6'."""
    if value is None:
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float):
        if np.isnan(value):
            return None
        return int(value)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    m = _INT_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def _score_row(row: Any, cfg: dict[str, Any]) -> tuple[float, str]:
    base_scores: dict[str, float] = cfg["base_scores"]
    boosts: dict[str, float] = cfg["boosts"]

    building = str(row.get("building", "") or "").strip().lower()
    levels = _to_int(row.get("building:levels"))
    flats = _to_int(row.get("building:flats"))
    housenumber = row.get("addr:housenumber")

    base = base_scores.get(building, 0.0)
    reasons = [f"building={building or 'unknown'}(base={base:.2f})"]

    score = base
    if levels is not None and levels >= 3:
        score += boosts.get("levels_ge_3", 0.0)
        reasons.append(f"levels={levels}(+{boosts.get('levels_ge_3', 0.0):.2f})")
        if levels >= 6:
            score += boosts.get("levels_ge_6", 0.0)
            reasons.append(f"levels>=6(+{boosts.get('levels_ge_6', 0.0):.2f})")
    if flats is not None and flats >= 3:
        score += boosts.get("flats_ge_3", 0.0)
        reasons.append(f"flats={flats}(+{boosts.get('flats_ge_3', 0.0):.2f})")
    if housenumber and str(housenumber).strip() not in {"", "nan", "None"}:
        score += boosts.get("has_addr_housenumber", 0.0)

    # If tag is generic 'residential' or 'yes' with strong levels/flats signal,
    # elevate slightly so pure levels-based detection is possible.
    if building in {"yes", ""} and (
        (levels is not None and levels >= 4) or (flats is not None and flats >= 4)
    ):
        score = max(score, 0.55)
        reasons.append("generic_tag_with_strong_levels(->0.55)")

    score = float(max(0.0, min(1.0, score)))
    return score, "; ".join(reasons)


def identify_murbs(
    gdf: gpd.GeoDataFrame,
    settings: dict[str, Any],
) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf

    cfg = settings["murb"]
    LOGGER.info("Scoring %d buildings for MURB likelihood", len(gdf))

    # Ensure the expected raw columns exist so `.get()` doesn't error later.
    for col in ("building", "building:levels", "building:flats", "addr:housenumber"):
        if col not in gdf.columns:
            gdf[col] = None

    scores: list[float] = []
    reasons: list[str] = []
    for row in gdf.to_dict(orient="records"):
        s, r = _score_row(row, cfg)
        scores.append(s)
        reasons.append(r)

    gdf = gdf.copy()
    gdf["building_type"] = gdf["building"].astype(str)
    gdf["murb_confidence"] = scores
    gdf["murb_reason"] = reasons

    threshold = float(cfg.get("min_confidence", 0.5))
    kept = gdf[gdf["murb_confidence"] >= threshold].copy()
    LOGGER.info(
        "Retained %d / %d buildings at murb_confidence >= %.2f",
        len(kept), len(gdf), threshold,
    )
    return kept.reset_index(drop=True)
