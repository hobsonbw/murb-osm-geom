"""End-to-end MURB geometry pipeline.

Usage
-----
    python -m src.run_pipeline --city "Ottawa, Ontario, Canada"

Or from the project root:

    python src/run_pipeline.py --config config/settings.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Route Python's SSL through the OS certificate store so corporate
# SSL-inspection proxies (Zscaler / Netskope / etc.) work without
# extra CA-bundle configuration. Must run BEFORE `requests`/`osmnx`
# opens any HTTPS connection.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - optional dependency
    pass

# Allow `python src/run_pipeline.py` (script) as well as `-m src.run_pipeline`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.calculate_geometry import calculate_geometry
    from src.classify_shapes import classify_shapes
    from src.download_osm import download_buildings
    from src.estimate_heights import estimate_heights
    from src.export_results import export_results
    from src.identify_murbs import identify_murbs
    from src.preprocess import preprocess
    from src.utils import ensure_dir, get_logger, load_settings, resolve_path, slugify_city
else:
    from .calculate_geometry import calculate_geometry
    from .classify_shapes import classify_shapes
    from .download_osm import download_buildings
    from .estimate_heights import estimate_heights
    from .export_results import export_results
    from .identify_murbs import identify_murbs
    from .preprocess import preprocess
    from .utils import ensure_dir, get_logger, load_settings, resolve_path, slugify_city

import geopandas as gpd


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract MURB geometry dataset from OpenStreetMap.",
    )
    p.add_argument("--config", type=Path, default=None,
                   help="Path to settings.yaml (default: config/settings.yaml)")
    p.add_argument("--city", type=str, default=None,
                   help="Override study area (OSM place name)")
    p.add_argument("--basename", type=str, default=None,
                   help="Base filename for exported outputs and intermediates "
                        "(default: derived from the city, e.g. 'ottawa_murbs')")
    p.add_argument("--limit", type=int, default=None,
                   help="Optional: process only first N cleaned buildings (debug)")
    p.add_argument("--from-checkpoint", action="store_true",
                   help="Skip stages 1-4, load from checkpoint, only run metrics/export (stages 5-6)")
    p.add_argument("--verbose", action="store_true",
                   help="Enable DEBUG logging")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    log = get_logger(level=logging.DEBUG if args.verbose else logging.INFO)

    settings = load_settings(args.config)
    if args.city:
        settings["study_area"]["city"] = args.city

    # Derive basename from the city name when the caller didn't override it,
    # so running a second city doesn't overwrite the first city's outputs.
    basename = args.basename or f"{slugify_city(settings['study_area']['city'])}_murbs"
    settings.setdefault("run", {})["basename"] = basename
    log.info("Study area: %s   basename: %s",
             settings["study_area"]["city"], basename)

    # Checkpoint file: classified MURBs with height estimates (after stage 4)
    processed_dir = ensure_dir(resolve_path(settings["paths"]["processed_dir"]))
    checkpoint_path = processed_dir / f"{basename}_checkpoint.gpkg"

    t0 = time.time()

    if args.from_checkpoint:
        if not checkpoint_path.exists():
            log.error("Checkpoint not found: %s", checkpoint_path)
            log.error("Run without --from-checkpoint first to create it.")
            return 1
        log.info("=== Loading from checkpoint: %s ===", checkpoint_path)
        murbs = gpd.read_file(checkpoint_path)
        log.info("Loaded %d records from checkpoint", len(murbs))
    else:
        log.info("=== Stage 1/6: download OSM buildings ===")
        raw = download_buildings(settings)

        log.info("=== Stage 2/6: preprocess & repair geometries ===")
        clean = preprocess(raw, settings)

        if args.limit:
            log.info("Applying debug --limit=%d", args.limit)
            clean = clean.head(args.limit).copy()

        log.info("=== Stage 3/6: identify MURBs ===")
        murbs = identify_murbs(clean, settings)

        log.info("=== Stage 4/6: estimate heights & storeys ===")
        murbs = estimate_heights(murbs, settings)

        # Save checkpoint after classification and height estimation
        log.info("Saving checkpoint to %s", checkpoint_path)
        murbs.to_file(checkpoint_path, driver="GPKG")

    log.info("=== Stage 5/6: compute geometry metrics ===")
    murbs = calculate_geometry(murbs)
    murbs = classify_shapes(murbs, settings)

    log.info("=== Stage 6/6: export results ===")
    paths = export_results(murbs, settings, basename=basename)
    for kind, p in paths.items():
        log.info("  %-8s -> %s", kind, p)

    log.info("Done in %.1fs. Retained %d MURB records.",
             time.time() - t0, len(murbs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
