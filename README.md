# MURB Geometry Extraction from OpenStreetMap

Python pipeline that identifies likely Multi-Unit Residential Buildings
(MURBs) in a given city from OpenStreetMap, then extracts building-level
geometry characteristics suitable as inputs to energy and code-compliance
models. Designed to support NECB-style archetype development without
baking archetype assumptions into the dataset itself.

Ottawa was the initial proof-of-concept study area; the pipeline is
city-agnostic and can be pointed at any place name resolvable by OSMnx.

See [specification.md](docs/specification.md) for the full specification.

## Quick start

Use Python 3.10 or newer (`truststore` does not support Python 3.9).

```powershell
# From project root (Windows PowerShell)
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Run the pipeline against the default study area (Ottawa).
python src/run_pipeline.py
```

Outputs are written to `data/outputs/`, with filenames derived from the
city (or the `--basename` you pass):

- `<basename>.csv` - one row per building, geometry in `geometry_wkt`
- `<basename>.gpkg` - GeoPackage in EPSG:3978 (metric)
- `<basename>.geojson` - GeoJSON in EPSG:4326

Raw OSM downloads are cached under `data/raw/osm_cache/` (keyed by tile
geometry hash, so multiple cities share the cache safely) and re-runs
skip the network.

### Local PBF acquisition

Geofabrik provides OpenStreetMap extracts on its
[North America download page](https://download.geofabrik.de/north-america/).
To use the Canada extract, download
[canada-latest.osm.pbf](https://download.geofabrik.de/north-america/canada/canada-latest.osm.pbf)
and place it under `data/raw/`. The file is over 6 GB and is not included in
the repository; PBF files under `data/raw/` are ignored by Git.

Geofabrik extracts are updated regularly, in some cases daily, so the latest
download may differ from the data used for the committed analysis. That
analysis used `canada-261122.osm.pbf`, downloaded on **2026-11-23 at 16:23
UTC**. Its SHA-256 checksum is recorded in the
[refresh manifest](data/outputs/analysis/provenance/pbf_refresh_manifest.json);
matching it requires the same file, not just a later download from the latest
link.

Set `acquisition.pbf_path` in [config/settings.yaml](config/settings.yaml) to
the downloaded file's path to use local data instead of Overpass. The configured
path names the analysis file above, so update it if the downloaded file has a
different name.
An empty path uses Overpass; a configured path that is missing logs a warning
and falls back to Overpass. The current implementation selects by `pbf_path`,
not by `acquisition.method`.

GDAL's `multipolygons` layer contains both closed building ways and
multipolygon relations. The loader clips these areas to the city boundary and
expands height, level, flat-count, and house-number tags from `other_tags`.
Invalid polygonal areas are repaired before clipping so topology errors do not
prevent acquisition. Boundary-only intersections that produce points or lines
are excluded from the building areas.
Preprocessing maps `osm_way_id` for ways and `osm_id` for relations to
`(element_type, osmid)` so distinct buildings are not discarded as duplicates.
Country-sized PBF files can still take many minutes to read; prefer regional
extracts when available. After an ingestion fix, rerun without
`--from-checkpoint` to rebuild classification and height estimates.

See [CALGARY_ANALYSIS.md](docs/investigations/CALGARY_ANALYSIS.md) for the measured identity-loss
investigation and the existing MURB heuristic's limitations.

### Refresh all configured analysis cities

Preserve the previous committed analysis with a baseline tag before refreshing.
The bulk command reads the PBF once in bounded Arrow batches, uses saved
municipal boundaries when available, and regenerates the 13 cities configured
in the analysis scripts (Ottawa is not included):

```powershell
git tag overpass-analysis-baseline
python -m scripts.refresh_city_analysis --baseline overpass-analysis-baseline
```

This replaces those cities' exports/checkpoints and regenerates OSM geometry,
height, floor-area/floors, and shape-comparison figures. Consultant-only figures
are unchanged. In addition to `sample_size.csv`, it writes
`data/outputs/analysis/cohort_comparison.csv` and a source-checksum/workflow
manifest, `data/outputs/analysis/provenance/pbf_refresh_manifest.json`. Access the old outputs through the
baseline tag. Do not recreate an existing baseline tag on a later commit.
Geometry calculations use two worker processes by default; pass `--workers 1`
to run serially on a resource-constrained machine.

## Fast iteration on metrics

To iterate quickly on geometry metrics without re-running classification:

```powershell
# First run: creates checkpoint after stage 4 (classification + height estimation)
python src/run_pipeline.py

# Fast re-runs: skip stages 1-4, only recalculate metrics (stages 5-6)
python src/run_pipeline.py --from-checkpoint
```

The checkpoint is saved to `data/processed/<basename>_checkpoint.gpkg` and contains all classified MURBs with height estimates. Modify [src/calculate_geometry.py](src/calculate_geometry.py) or [src/classify_shapes.py](src/classify_shapes.py), then run with `--from-checkpoint` to see changes in seconds.

## Running additional cities

The pipeline is city-agnostic. Pass `--city` with any place name that
OSMnx's `geocode_to_gdf` can resolve. If you don't pass `--basename`,
it is derived from the city (first comma-separated segment, slugified),
so successive cities produce distinct filenames without collisions:

```powershell
# Uses the default city from config/settings.yaml (Ottawa)
python src/run_pipeline.py

# Kingston, ON  -> outputs/kingston_murbs.{csv,gpkg,geojson}
python src/run_pipeline.py --city "Kingston, Ontario, Canada"

# Explicit basename overrides the derived one
python src/run_pipeline.py --city "Halifax, Nova Scotia, Canada" --basename halifax_pilot
```

All per-city artifacts are namespaced by basename:

| Location | Filename pattern |
|----------|------------------|
| `data/raw/` | `<basename>_boundary.gpkg`, `<basename>_buildings_raw.gpkg` |
| `data/processed/` | `<basename>_buildings_clean.gpkg`, `<basename>_checkpoint.gpkg` |
| `data/outputs/` | `<basename>.csv`, `<basename>.gpkg`, `<basename>.geojson` |

The OSM tile cache in `data/raw/osm_cache/` is keyed by tile geometry
hash, so different cities can share it safely and re-runs of the same
city skip Overpass entirely.

### Disk footprint and pruning

An Ottawa-sized run produces about 3.25 GB of files, of which ~2.7 GB
is the raw+clean full-building GeoPackages that stages 3-6 no longer
need once the checkpoint is written. By default the pipeline deletes
those two files after the checkpoint is saved, cutting per-city cost
to ~530 MB. They are trivially rebuildable from the tile cache, so
`--from-checkpoint` runs are unaffected.

To retain them (e.g. for debugging stages 1-2):

```powershell
python src/run_pipeline.py --city "Kingston, Ontario, Canada" --keep-intermediates
```

You can also change the default study area permanently by editing
`study_area.city` in [config/settings.yaml](config/settings.yaml).

## Polygon plots (optional, run separately)

The main pipeline does not draw any per-building images. To render one
PNG per MURB after a run completes, invoke the batch plotter directly
against the exported CSV:

```powershell
# Plot every polygon for Ottawa
# -> data/outputs/polygon_plots/ottawa_murbs/<osmid>.png
python scripts/plot_all_polygons.py --basename ottawa_murbs

# Smoke test with only 25 buildings
python scripts/plot_all_polygons.py --basename ottawa_murbs --limit 25

# Or point at any CSV / output dir explicitly
python scripts/plot_all_polygons.py --csv data/outputs/kingston_murbs.csv
```

PNGs land in `data/outputs/polygon_plots/<basename>/` so different cities
never overwrite each other. Expect ~40 KB per polygon (Ottawa's full run
was ~113 MB for ~2,800 MURBs).

## City analysis

After exporting city CSVs, regenerate the OSM metric tables and figures, the
OSM/consultant comparisons, and consultant-only analysis from the project root:

```powershell
python -m scripts.plot_footprint_area_by_city
python -m scripts.plot_floor_area_relationship
python -m scripts.plot_shape_comparison
python -m scripts.analyze_rdh
```

Generate the optional OSM metric correlation matrix separately:

```powershell
python -m scripts.plot_osm_correlations
```

For interactive geometry-only, geometry-plus-height, and normalized
parallel-coordinate plots, run `python -m scripts.plot_osm_parallel_coordinates`
and open the resulting HTML files in a browser.

City MURB CSVs remain in `data/outputs/`; primary metric outputs are in
`data/outputs/analysis/`, with exploratory outputs in its `exploratory/`
subfolder. Geometry and footprint summaries use pooled IQR filtering; four
geometry boxplots additionally omit values below their group-specific 5th
percentile. Height summaries use all eligible explicit-height records. See the
[analysis guide](docs/analysis.md) for cohort criteria, filtering, output
files, correlations, consultant comparisons, and interpretation caveats.

## Configuration

All tunable parameters live in [config/settings.yaml](config/settings.yaml):

- Study area (any place name resolvable by OSMnx `geocode_to_gdf`)
- OSMnx/Overpass tile grid size, timeout, retries
- Working CRS (default EPSG:3978 - Canada Atlas Lambert)
- Floor-to-floor height for level-based height estimation
- MURB confidence rules (base scores per `building` tag + boosts)
- Shape classification thresholds

Override the city from the CLI:

```powershell
python src/run_pipeline.py --city "Kingston, Ontario, Canada" --basename kingston_murbs
```

## Pipeline stages

| Stage | Module | Purpose |
|-------|--------|---------|
| 1 | `download_osm.py` | Fetch boundary + all `building=*` features via OSMnx, tiled |
| 2 | `preprocess.py` | Repair, dedupe, project to metric CRS |
| 3 | `identify_murbs.py` | Score each building's MURB likelihood from tags |
| 4 | `estimate_heights.py` | Parse `height` / `building:levels`; estimate the missing one |
| 5 | `calculate_geometry.py` + `classify_shapes.py` | Compute all geometry metrics |
| 6 | `export_results.py` | Write CSV + GeoPackage + GeoJSON |

## Output schema

CSV output columns (the GeoPackage and GeoJSON use `geometry` instead of
`geometry_wkt`):

```
osmid, building_type, murb_confidence, murb_reason,
footprint_area_m2, perimeter_m,
length_m, width_m, average_depth_m, aspect_ratio,
height_m, height_est_m, height_source,
levels, levels_est, levels_source,
gross_floor_area_est_m2,
compactness, rectangularity,
courtyard_area_m2, courtyard_ratio,
vertex_count,
shape_class, shape_confidence,
geometry_wkt
```

## Notes / limitations

- OSM height/level coverage in Ottawa is uneven. Rows with neither
  `height` nor `building:levels` will have NaN for `height_est_m`,
  `levels_est`, and `gross_floor_area_est_m2` - filter downstream as needed.
- Shape classification is intentionally lightweight/heuristic and marked
  as descriptive, not prescriptive.
- Overpass can rate-limit large city queries. The pipeline splits the
  boundary into a configurable NxN grid (default 12x12) and caches each tile.

## Project layout

```
project/
├── config/settings.yaml
├── data/
│   ├── raw/               # cached OSM downloads (tiles + merged raw + boundary)
│   ├── processed/         # cleaned/projected buildings
│   └── outputs/           # final CSV / GPKG / GeoJSON
├── src/
│   ├── download_osm.py
│   ├── preprocess.py
│   ├── identify_murbs.py
│   ├── estimate_heights.py
│   ├── calculate_geometry.py
│   ├── classify_shapes.py
│   ├── export_results.py
│   ├── run_pipeline.py
│   └── utils.py
├── docs/
│   ├── analysis.md
│   ├── specification.md
│   └── investigations/
├── requirements.txt
└── README.md
```