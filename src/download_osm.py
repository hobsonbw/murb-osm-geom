"""Download OSM building footprints for the study area.

Default acquisition uses OSMnx, which wraps the Overpass API. The city
boundary is fetched via `geocode_to_gdf`, then split into a coarse grid
of tiles so that individual Overpass queries stay within their timeout
budget. Tiles are cached to disk as GeoPackage layers to avoid repeat
downloads across runs.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import osmnx as ox
from osmnx._errors import InsufficientResponseError
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from .utils import ensure_dir, get_logger, resolve_path


LOGGER = get_logger()

BUILDING_TAGS: dict[str, bool | list[str]] = {"building": True}


def _cache_key(polygon: BaseGeometry) -> str:
    wkb = polygon.wkb
    return hashlib.md5(wkb).hexdigest()[:12]  # noqa: S324 - cache key only


def _configure_osmnx(timeout: int, overpass_url: str) -> None:
    # osmnx v2 uses settings module for these knobs.
    ox.settings.requests_timeout = timeout
    ox.settings.overpass_url = overpass_url
    ox.settings.use_cache = True
    ox.settings.log_console = False


def get_boundary(city: str) -> gpd.GeoDataFrame:
    LOGGER.info("Geocoding boundary for %s", city)
    gdf = ox.geocode_to_gdf(city)
    if gdf.empty:
        raise RuntimeError(f"Could not geocode place: {city}")
    return gdf


def _tile_polygon(polygon: BaseGeometry, n: int) -> list[BaseGeometry]:
    """Split `polygon` into an NxN grid of tiles, each clipped to the polygon."""
    if n <= 1:
        return [polygon]
    minx, miny, maxx, maxy = polygon.bounds
    dx = (maxx - minx) / n
    dy = (maxy - miny) / n
    tiles: list[BaseGeometry] = []
    for i in range(n):
        for j in range(n):
            cell = box(minx + i * dx, miny + j * dy,
                       minx + (i + 1) * dx, miny + (j + 1) * dy)
            clipped = cell.intersection(polygon)
            if not clipped.is_empty and clipped.area > 0:
                tiles.append(clipped)
    return tiles


def _download_tile(
    polygon: BaseGeometry,
    cache_dir: Path,
    max_retries: int,
    timeout: int,
    overpass_urls: list[str],
) -> gpd.GeoDataFrame:
    key = _cache_key(polygon)
    cache_file = cache_dir / f"tile_{key}.gpkg"
    if cache_file.exists():
        LOGGER.info("Cache hit  tile=%s", key)
        return gpd.read_file(cache_file)

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        overpass_url = overpass_urls[(attempt - 1) % len(overpass_urls)]
        _configure_osmnx(timeout, overpass_url)
        try:
            LOGGER.info(
                "Downloading tile=%s attempt=%d via %s",
                key, attempt, overpass_url,
            )
            gdf = ox.features_from_polygon(polygon, tags=BUILDING_TAGS)
            if gdf is None or gdf.empty:
                LOGGER.info("Tile %s returned 0 features", key)
                gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
            else:
                # osmnx returns a MultiIndex (element_type, osmid); flatten it.
                if isinstance(gdf.index, gpd.pd.MultiIndex):
                    gdf = gdf.reset_index()
            # Persist to cache even when empty so we don't hammer the API again.
            _safe_write_gpkg(gdf, cache_file)
            return gdf
        except InsufficientResponseError as err:
            # Do not treat an empty response as authoritative: regional or
            # overloaded endpoints can return no elements for valid queries.
            last_err = err
            LOGGER.warning(
                "Tile %s returned no features on %s (attempt %d/%d); retrying",
                key, overpass_url, attempt, max_retries,
            )
            time.sleep(2 * attempt)
        except Exception as err:  # noqa: BLE001 - retry any network/parse err
            last_err = err
            LOGGER.warning("Tile %s failed (attempt %d/%d via %s): %s",
                           key, attempt, max_retries, overpass_url, err)
            time.sleep(2 * attempt)

    raise RuntimeError(
        f"Tile {key} failed after {max_retries} attempts; no empty cache "
        f"entry was written. Retry the pipeline after resolving the download "
        f"failure. Last error: {last_err}"
    ) from last_err


def _safe_write_gpkg(gdf: gpd.GeoDataFrame, path: Path) -> None:
    """Write a GeoDataFrame to GeoPackage, coercing unhashable/list columns."""
    if gdf.empty:
        # Still write an empty file so cache lookups succeed.
        gdf.to_file(path, driver="GPKG")
        return
    out = gdf.copy()
    for col in out.columns:
        if col == "geometry":
            continue
        # Stringify objects that GDAL can't serialize (lists, dicts, ints64...).
        if out[col].dtype == object:
            out[col] = out[col].astype(str)
    out.to_file(path, driver="GPKG")


def download_buildings(settings: dict[str, Any]) -> gpd.GeoDataFrame:
    """Download all buildings in the configured study area."""
    city = settings["study_area"]["city"]
    acq = settings["acquisition"]
    cache_dir = ensure_dir(resolve_path(settings["paths"]["cache_dir"]))
    raw_dir = ensure_dir(resolve_path(settings["paths"]["raw_dir"]))

    timeout = int(acq.get("timeout", 300))
    overpass_urls = acq.get("overpass_urls", ["https://overpass-api.de/api"])
    if not isinstance(overpass_urls, list) or not overpass_urls:
        raise ValueError("acquisition.overpass_urls must be a non-empty list")
    overpass_urls = [str(url) for url in overpass_urls]
    _configure_osmnx(timeout, overpass_urls[0])

    boundary = get_boundary(city)
    # Union in case the geocoder returns multi-part boundaries.
    polygon = boundary.geometry.unary_union

    tiles = _tile_polygon(polygon, int(acq.get("tile_grid", 4)))
    LOGGER.info("Study area split into %d tile(s)", len(tiles))

    frames: list[gpd.GeoDataFrame] = []
    for idx, tile in enumerate(tiles, start=1):
        LOGGER.info("Tile %d/%d", idx, len(tiles))
        frames.append(_download_tile(
            tile, cache_dir=cache_dir,
            max_retries=int(acq.get("max_retries", 5)),
            timeout=timeout,
            overpass_urls=overpass_urls,
        ))

    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        LOGGER.warning("No buildings retrieved for %s", city)
        merged = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    else:
        merged = gpd.pd.concat(non_empty, ignore_index=True)
        merged = gpd.GeoDataFrame(merged, geometry="geometry",
                                  crs=non_empty[0].crs)

    LOGGER.info("Total raw building features: %d", len(merged))

    # Prefix per-city so multi-city runs don't clobber each other's intermediates.
    basename = settings.get("run", {}).get("basename", "study_area")

    # Save the merged raw dataset for reproducibility.
    raw_path = raw_dir / f"{basename}_buildings_raw.gpkg"
    _safe_write_gpkg(merged, raw_path)
    LOGGER.info("Wrote %s", raw_path)

    # Also save the boundary for downstream visualization / debugging.
    boundary_path = raw_dir / f"{basename}_boundary.gpkg"
    boundary.to_file(boundary_path, driver="GPKG")
    LOGGER.info("Wrote %s", boundary_path)

    return merged
