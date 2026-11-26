# MURB Geometry Extraction from OpenStreetMap

Python pipeline that identifies likely Multi-Unit Residential Buildings
(MURBs) in a given city from OpenStreetMap, then extracts building-level
geometry characteristics suitable as inputs to energy and code-compliance
models. Designed to support NECB-style archetype development without
baking archetype assumptions into the dataset itself.

Ottawa was the initial proof-of-concept study area; the pipeline is
city-agnostic and can be pointed at any place name resolvable by OSMnx.

See [specification.md](specification.md) for the full specification.

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

Set `acquisition.pbf_path` in [config/settings.yaml](config/settings.yaml) to
an existing Geofabrik `.osm.pbf` extract to use local data instead of Overpass.
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

See [CALGARY_ANALYSIS.md](CALGARY_ANALYSIS.md) for the measured identity-loss
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
manifest, `data/outputs/analysis/pbf_refresh_manifest.json`. Access the old outputs through the
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

After exporting city CSVs, regenerate the Part 3 footprint, geometry, and height
plots and tables:

```powershell
python scripts/plot_footprint_area_by_city.py
```

The Part 3 cohort requires confidence >= 0.77, footprint area >= 87.6 m²,
and either area > 600 m² or more than three storeys. The storey criterion
accepts explicit or estimated levels > 3 or explicit or estimated height > 9 m.
Height analysis additionally requires positive explicit height and levels,
with height divided by levels between 2 and 6 m, inclusive.

The script reads `data/outputs/*_murb.csv` and `*_murbs.csv` and writes
`data/outputs/analysis/footprint_area.svg`, `length.svg`, `width.svg`,
`average_depth.svg`, `aspect_ratio.svg`, `rectangularity.svg`, `sample_size.csv`,
`footprint_area_summary.csv`, `length_summary.csv`, `width_summary.csv`,
`average_depth_summary.csv`, `aspect_ratio_summary.csv`, `rectangularity_summary.csv`,
`floor_height.csv`, `floor_num.csv`, and `build_height.csv`. Height
distributions are also written as pooled histograms in `floor_height.svg`,
`floor_num.svg`, and `build_height.svg`; unlike the geometry boxplots, these
combine eligible data across configured cities into one distribution per metric.
Floor-height bins and ticks run from 2 to 6 m in 0.25 m increments;
building-height bins and ticks run from 0 to 204 m in 12 m increments.
Floor-count bins span four storeys and are labeled by their ranges. All three
histogram plotting areas are square.
The geometry plots and tables summarize `length_m`, `width_m`, `average_depth_m`,
`aspect_ratio`, and `rectangularity` for the same Part 3 MURB cohort as the
footprint output.
Tables include configured locations in a fixed order, zero rows for cities
without data, and an aggregate `All` row. Each plot omits individual cities
with fewer than 10 valid values for that metric, but their buildings still
contribute to `All`.
Use `--input-dir` and `--output-dir` to analyze a different set of CSVs without
overwriting these results.

### OSM presentation-level outlier filtering

OSM footprint area, length, width, average depth, aspect ratio, and
rectangularity summaries and figures use a single-pass 1.5-times-IQR filter
after the existing cohort and valid-value selection. For each of these six
metrics, quartiles are calculated from pooled values across all configured
cities:

```text
IQR = Q3 - Q1
retain Q1 - 1.5 * IQR <= value <= Q3 + 1.5 * IQR
```

The same bounds apply to each city and `All`. Filtering is independent per
metric. Floor height, number of floors, and building height use all eligible
values without IQR filtering; their existing explicit-height and 2–6 m
floor-height eligibility criteria still apply. A footprint outlier can
contribute to height statistics. Min, max, and 5th/50th/95th percentiles are
calculated from each metric's selected values; figures use those same values,
without additional percentile-based hiding.
Remaining boxplot dots reflect city-specific whiskers, but are within the
pooled retention bounds and are included in the tables.

`data/outputs/analysis/osm_metric_filter_counts.csv` records the filter policy,
bounds, and eligible-value, retained, and excluded counts per metric/city and
for `All`. Unfiltered height metrics have `none`, blank bounds, and zero IQR
exclusions.
Input counts exclude missing metric values. `sample_size.csv` remains the
untrimmed eligibility/cohort count table, and categorical shape counts are
unchanged. Building CSVs and all consultant-only data/tables/figures are
untouched. Zero IQR produces equal fences and retains only values equal to the
quartiles; no alternative rule is silently substituted.

The percentage removed depends on each metric's distribution, not a guaranteed
0.7%. Filtered summaries describe the retained presentation dataset, not
unbiased estimates of the full building population. Regenerate analysis only (no PBF
read or building export needed):

```powershell
python -m scripts.plot_footprint_area_by_city
python -m scripts.plot_floor_area_relationship
```

### Distribution audit (2026-11-26)

The original eligible values, before IQR filtering, were checked using
histograms, normal Q-Q plots, skewness, excess kurtosis, and SciPy's
D'Agostino-Pearson normality test. All nine pooled raw metrics reject normality,
including with a Bonferroni threshold of `0.05 / 9`. Large samples make these
tests sensitive to small departures; Q-Q plots and measurement constraints
matter more than treating a p-value as a pass/fail suitability rule.

Length is close to normal on a log scale, although its log-scale test still
rejects normality. Most size metrics are right-skewed; rectangularity is
left-skewed and bounded by 0 and 1. Floor counts are discrete, while floor
height is heaped and already restricted to 2-6 m by cohort selection.
Per-city diagnostics are also included; samples smaller than 20 and constant
samples are explicitly not tested.

IQR fences do **not** require normality, and neither they nor normality tests
establish that excluded buildings are erroneous. Empirical percentiles do not
require normality either. In the audit's hypothetical all-metric trimming, the
pooled 95th percentile fell by 24.60% for footprint area and 36.32% for
building height. Building height is now unfiltered. A bell-shaped distribution
after filtering does not validate deleting the original observations.

Exploratory outputs and individual metric tables and figures live in
`data/outputs/analysis/`.
The full building CSVs remain in `data/outputs/`. Distribution-audit outputs
are not regenerated by the regular city-analysis command:

- [`osm_distribution_diagnostics.csv`](data/outputs/analysis/osm_distribution_diagnostics.csv):
  pooled/per-city raw, hypothetical IQR-retained, and log-raw diagnostics.
  The retained height views describe the prior all-metric IQR scenario, not
  the current unfiltered height outputs. Zero p-values indicate numeric
  underflow; the log10 p-value column preserves their magnitude.
- [`osm_iqr_summary_sensitivity.csv`](data/outputs/analysis/osm_iqr_summary_sensitivity.csv):
  raw versus hypothetical IQR-retained min/max and 5th/50th/95th percentiles,
  with exclusion counts and changes; height comparisons are hypothetical.
- [`osm_metric_distributions.svg`](data/outputs/analysis/osm_metric_distributions.svg):
  full-range untrimmed histograms with normal reference curves.
- [`osm_normal_qq.svg`](data/outputs/analysis/osm_normal_qq.svg) and
  [`osm_log_normal_qq.svg`](data/outputs/analysis/osm_log_normal_qq.svg):
  normal Q-Q comparisons before filtering, on original and log scales.
- [`footprint_outlier_method_comparison.csv`](data/outputs/analysis/footprint_outlier_method_comparison.csv):
  comparison of unfiltered, IQR, and standard-deviation footprint summaries.

### OSM metric correlations

Generate a nine-metric scatterplot matrix and pairwise Pearson and Spearman
correlation tables:

```powershell
python -m scripts.plot_osm_correlations
```

The pooled Part 3 OSM data use the same eligibility and per-metric filtering
as the summaries above. Each off-diagonal panel uses only buildings with both
metrics available and retained: the lower triangle plots every such pair and
the upper triangle reports Pearson's `r`, Spearman's rank correlation, and the
pair count. Diagonal histograms show each metric's individually selected
values. The height metrics require valid explicit height and storeys, so their
pair counts are much smaller. Counts vary across pairs; the matrix is not a
single complete-case sample and is not necessarily positive semidefinite.
Pearson measures linear association; Spearman measures monotonic rank
association. A coefficient is unavailable for fewer than two observations or
constant values.

Outputs are [`osm_correlation_matrix.svg`](data/outputs/analysis/osm_correlation_matrix.svg),
[`osm_correlation_pearson.csv`](data/outputs/analysis/osm_correlation_pearson.csv),
[`osm_correlation_spearman.csv`](data/outputs/analysis/osm_correlation_spearman.csv),
and [`osm_correlation_counts.csv`](data/outputs/analysis/osm_correlation_counts.csv).
Use `--input-dir` and `--output-dir` to analyze other exports.

These are descriptive associations, not causal relationships. Some metrics
are mathematically related (for example aspect ratio is length/width, and
floor height is building height/floors). Pooled city composition, missing height
tags, cohort criteria, and IQR selection can also influence the relationships.

## OSM and RDH area/floors comparison

Compare Part 3 OSM buildings with RDH consultant records using a square
scatterplot of footprint/floor-plate area against floors/storeys:

```powershell
python scripts/plot_floor_area_relationship.py
```

The output is `data/outputs/analysis/floor_area_vs_floors.svg`, with floors on
the x-axis and area on the y-axis. OSM points use configured cities and the
Part 3 filter, and require explicit `height_m` and `levels` with a 2–6 m
floor-height ratio. Consultant points
require a nonblank climate zone and positive storey and floor-plate values.
OSM points must pass the same pooled footprint IQR bounds as the footprint
summary; floor counts are not IQR-filtered. Consultant points retain the existing
pooled 0.3rd–99.7th percentile selection computed from the original unfiltered
OSM/consultant pairs; the new OSM filter does not change their selection.
Source-specific colors and plotted counts appear in the legend.
Override `--osm-dir`, `--rdh-csv`, or `--output` to use other inputs or an
output path.

## OSM and consultant shape comparison

Generate a two-panel count plot of approximate shape categories with:

```powershell
python scripts/plot_shape_comparison.py
```

The output is `data/outputs/analysis/shape_comparison.svg`. OSM `Rectangle` and
`Slab` map to `Rectangular`; `Square` and `Tower` map to `Square`; L-shapes are
combined, U- and C-shapes are grouped as `U/C-shaped`, and `Courtyard` remains
separate. Remaining labels map to `Other / Irregular`. Panels have separate
count scales to keep the
smaller consultant sample visible. Only configured OSM cities and RDH rows
with a climate zone are included. OSM shapes use the same Part 3 selection
as the geometry plots, rather than the entire Possible MURB export.

## RDH consultant analysis

Generate climate-zone summaries and square histograms for the consultant
dataset with:

```powershell
python scripts/analyze_rdh.py
```

Outputs use the `_rdh` suffix, such as `floor_num_rdh.svg` and
`floor_num_rdh_summary.csv`. WWR outputs are named
`wwr_<orientation>_rdh.svg` and `wwr_<orientation>_rdh_summary.csv`; their
histograms use 5% bins and ticks from 0–70%. The footprint-area histogram spans
0–6000 m² with 500 m² bins labeled by their ranges. Histograms are pooled across climate zones; summary
tables include one row per climate zone and an `All` row. Blank climate-zone
records are excluded, and zones `7A` and `7B` are combined under `7`.

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
├── specification.md
├── requirements.txt
└── README.md
```