"""Refresh the configured analysis cities from one streaming PBF read."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import union_all
from shapely.geometry.base import BaseGeometry

from scripts.plot_footprint_area_by_city import LOCATIONS
from src.calculate_geometry import calculate_geometry
from src.classify_shapes import classify_shapes
from src.download_osm import PBF_BUILDING_SQL, get_boundary
from src.estimate_heights import estimate_heights
from src.export_results import export_results
from src.identify_murbs import identify_murbs
from src.preprocess import preprocess
from src.utils import ensure_dir, get_logger, load_settings, project_root, resolve_path


LOGGER = get_logger()


def _extract_city_buildings(
    pbf_path: Path,
    boundaries: dict[str, BaseGeometry],
    output_dir: Path,
    batch_size: int = 65536,
) -> dict[str, int]:
    counts = dict.fromkeys(boundaries, 0)
    mask = union_all(list(boundaries.values()))
    with pyogrio.open_arrow(
        pbf_path, sql=PBF_BUILDING_SQL, sql_dialect="OGRSQL",
        mask=mask, use_pyarrow=True, batch_size=batch_size,
    ) as (metadata, reader):
        geometry_column = metadata["geometry_name"] or "wkb_geometry"
        for batch_number, batch in enumerate(reader, start=1):
            frame = batch.to_pandas()
            geometry = gpd.GeoSeries.from_wkb(
                frame.pop(geometry_column), crs=metadata["crs"],
            )
            buildings = gpd.GeoDataFrame(frame, geometry=geometry)
            for city, polygon in boundaries.items():
                indices = buildings.sindex.query(polygon, predicate="intersects")
                if len(indices) == 0:
                    continue
                clipped = buildings.iloc[indices].clip(polygon)
                if clipped.empty:
                    continue
                path = output_dir / f"{city}_buildings.gpkg"
                clipped.to_file(
                    path, layer="buildings", driver="GPKG", engine="pyogrio",
                    mode="a" if path.exists() else "w", index=False,
                )
                counts[city] += len(clipped)
            LOGGER.info("Extracted batch %d; city totals: %s", batch_number, counts)
    return counts


def _compare_cohorts(baseline: str, analysis_dir: Path) -> None:
    result = subprocess.run(
        ["git", "--no-pager", "show", f"{baseline}:data/outputs/analysis/sample_size.csv"],
        cwd=project_root(), capture_output=True, text=True, check=True,
        encoding="utf-8",
    )
    old = pd.read_csv(io.StringIO(result.stdout)).set_index("Locations")
    new = pd.read_csv(analysis_dir / "sample_size.csv").set_index("Locations")
    comparison = old.join(new, lsuffix="_baseline", rsuffix="_pbf", how="outer")
    for column in new.columns:
        comparison[f"{column}_change"] = (
            comparison[f"{column}_pbf"] - comparison[f"{column}_baseline"]
        )
    comparison.to_csv(analysis_dir / "cohort_comparison.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--baseline", default="overpass-analysis-baseline")
    args = parser.parse_args()
    settings = load_settings(args.config)
    configured_pbf = settings["acquisition"].get("pbf_path", "").strip()
    if not configured_pbf:
        raise ValueError("The city refresh requires acquisition.pbf_path")
    pbf_path = resolve_path(configured_pbf)
    if not pbf_path.is_file():
        raise FileNotFoundError(pbf_path)

    raw_dir = ensure_dir(resolve_path(settings["paths"]["raw_dir"]))
    processed_dir = ensure_dir(resolve_path(settings["paths"]["processed_dir"]))
    outputs_dir = ensure_dir(resolve_path(settings["paths"]["outputs_dir"]))
    analysis_dir = ensure_dir(outputs_dir / "analysis")
    boundaries = {}
    for city, label in LOCATIONS.items():
        path = raw_dir / f"{city}_murbs_boundary.gpkg"
        if path.exists():
            boundary = gpd.read_file(path)
        else:
            boundary = get_boundary(f"{label}, Canada")
            boundary.to_file(path, driver="GPKG")
        polygon = boundary.to_crs("EPSG:4326").geometry.union_all()
        if polygon.is_empty:
            raise ValueError(f"Empty boundary for {label}")
        boundaries[city] = polygon

    LOGGER.info("Reading %s once for %d cities", pbf_path, len(boundaries))
    with tempfile.TemporaryDirectory(prefix="murb-pbf-") as directory:
        temporary_dir = Path(directory)
        counts = _extract_city_buildings(pbf_path, boundaries, temporary_dir)
        settings["paths"]["processed_dir"] = directory
        for city, label in LOCATIONS.items():
            if counts[city] == 0:
                raise RuntimeError(f"No building areas extracted for {label}; refusing stale exports")
            basename = f"{city}_murbs"
            settings.setdefault("run", {})["basename"] = basename
            settings["study_area"]["city"] = f"{label}, Canada"
            LOGGER.info("Refreshing %s from %d building areas", label, counts[city])
            raw = gpd.read_file(temporary_dir / f"{city}_buildings.gpkg")
            clean = preprocess(raw, settings)
            del raw
            murbs = estimate_heights(identify_murbs(clean, settings), settings)
            del clean
            if murbs.empty:
                raise RuntimeError(f"No possible MURBs for {label}; refusing stale exports")
            murbs.to_file(processed_dir / f"{basename}_checkpoint.gpkg", driver="GPKG")
            murbs = classify_shapes(calculate_geometry(murbs), settings)
            export_results(murbs, settings, basename)
            del murbs

    commands = [
        ["scripts.plot_footprint_area_by_city", "--input-dir", str(outputs_dir),
         "--output-dir", str(analysis_dir)],
        ["scripts.plot_floor_area_relationship", "--osm-dir", str(outputs_dir),
         "--output", str(analysis_dir / "floor_area_vs_floors.svg")],
        ["scripts.plot_shape_comparison", "--osm-dir", str(outputs_dir),
         "--output", str(analysis_dir / "shape_comparison.svg")],
    ]
    for command in commands:
        subprocess.run([sys.executable, "-m", *command], cwd=project_root(), check=True)
    _compare_cohorts(args.baseline, analysis_dir)

    with pbf_path.open("rb") as source:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_root(), capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    manifest = {
        "pbf_file": pbf_path.name,
        "pbf_sha256": checksum.hexdigest(),
        "workflow_commit": revision,
        "baseline": args.baseline,
        "cities": list(LOCATIONS),
        "raw_building_counts": counts,
    }
    (analysis_dir / "pbf_refresh_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
    )
    LOGGER.info("Refresh complete; comparison and provenance written to %s", analysis_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
