# Ottawa MURB Geometry Extraction (OpenStreetMap)

Python pipeline that identifies likely Multi-Unit Residential Buildings
(MURBs) in the City of Ottawa from OpenStreetMap, then extracts building-level
geometry characteristics suitable as inputs to energy and code-compliance
models. Designed to support NECB-style archetype development without
baking archetype assumptions into the dataset itself.

See [requirements.md](requirements.md) for the full specification.

## Quick start

```powershell
# From project root (Windows PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# Run the pipeline against the default study area (Ottawa).
python src/run_pipeline.py
```

Outputs are written to `data/outputs/`:

- `ottawa_murbs.csv` - one row per building, geometry as WKT
- `ottawa_murbs.gpkg` - GeoPackage in EPSG:3978 (metric)
- `ottawa_murbs.geojson` - GeoJSON in EPSG:4326

Raw OSM downloads are cached under `data/raw/osm_cache/` so re-runs
skip the network.

## Configuration

All tunable parameters live in [config/settings.yaml](config/settings.yaml):

- Study area (any place name resolvable by OSMnx `geocode_to_gdf`)
- Acquisition method, tile grid size, timeout, retries
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

Matches the specification in `requirements.md`:

```
osmid, building_type, murb_confidence, murb_reason,
footprint_area_m2, perimeter_m,
length_m, width_m, aspect_ratio,
height_m, height_est_m, height_source,
levels, levels_est, levels_source,
gross_floor_area_est_m2,
compactness, rectangularity,
courtyard_area_m2, courtyard_ratio,
vertex_count,
shape_class, shape_confidence,
geometry
```

## Notes / limitations

- OSM height/level coverage in Ottawa is uneven. Rows with neither
  `height` nor `building:levels` will have NaN for `height_est_m`,
  `levels_est`, and `gross_floor_area_est_m2` - filter downstream as needed.
- Shape classification is intentionally lightweight/heuristic and marked
  as descriptive, not prescriptive.
- Overpass can rate-limit large city queries. The pipeline splits the
  boundary into a configurable NxN grid (default 4x4) and caches each tile.

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
├── requirements.md
├── requirements.txt
└── README.md
```
