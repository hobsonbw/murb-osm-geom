# Requirements Specification: Ottawa MURB Geometry Dataset Extraction for Code Committee Analysis

## Objective

Develop a Python-based workflow that identifies likely Multi-Unit Residential Buildings (MURBs) within the City of Ottawa and extracts building geometry characteristics that can be used as direct inputs to building energy and code-analysis models.

The workflow should focus on collecting and calculating raw building geometry data rather than assigning buildings to predefined low-rise, mid-rise, or high-rise categories.

The intent is to provide a comprehensive building-level dataset that allows analysts and code committees to:

- Develop their own building classifications.
- Modify height thresholds in the future.
- Create representative archetypes based on measured data.
- Conduct custom clustering and statistical analyses.
- Derive geometry inputs for energy, carbon, and code-compliance models.

The workflow should avoid embedding assumptions about building archetypes beyond basic geometric descriptions.

---

## Key Research Questions

The resulting dataset should allow analysts to answer questions such as:

- What are the most common apartment footprint sizes?
- What are the most common building heights and storey counts?
- What are the most common building dimensions?
- What footprint shapes occur most frequently?
- What distributions best represent Ottawa's MURB stock?
- What representative geometries should be used in code-analysis models?

---

## Study Area

Default study area:

```yaml
city: Ottawa, Ontario, Canada
```

Requirements:

- Automatically retrieve the municipal boundary.
- Download and process all buildings within the boundary.
- Allow future use with other municipalities through configuration.

---

## Data Source

Primary source:

- OpenStreetMap (OSM)

Supported acquisition methods:

1. OSMnx
2. Overpass API
3. Local OSM PBF extract

The workflow should support local caching to avoid repeated downloads.

---

## Building Selection

Collect all buildings within Ottawa.

Identify likely MURBs using available OSM attributes.

Retain original OSM tags whenever possible.

Relevant tags include:

```text
building
building:levels
building:flats
height
roof:height
name
addr:*
```

Output fields:

```text
osmid
building_type
murb_confidence
murb_reason
```

A confidence-based approach is preferred.

---

## Geometry Validation

Before analysis:

- Remove null geometries.
- Repair invalid polygons.
- Handle multipolygons correctly.
- Remove duplicate records.
- Validate topology.

Use a projected coordinate reference system suitable for metric calculations.

Preferred CRS:

```text
EPSG:3978
```

All geometry outputs should be reported in metres and square metres.

---

## Height and Storey Data

### Direct Data

Extract when available:

```text
height
building:levels
roof:height
```

### Height Estimation

When height is unavailable, estimate height using:

```text
building:levels × assumed floor-to-floor height
```

Store:

```text
height_est_m
height_source
```

Recommended height source categories:

```text
explicit_height
building_levels
estimated
```

### Storey Estimation

When levels are unavailable, estimate storeys using available building information.

Store:

```text
levels_est
levels_source
```

---

## Required Geometry Outputs

### Footprint Area

```text
footprint_area_m2
```

### Perimeter

```text
perimeter_m
```

### Building Dimensions

Using the minimum rotated rectangle:

```text
length_m
width_m
aspect_ratio
```

These dimensions should represent the overall building form regardless of orientation.

---

## Estimated Gross Floor Area

Estimate:

```text
gross_floor_area_est_m2
```

Calculation:

```text
footprint_area_m2 × estimated_levels
```

Store the methodology used for each estimate.

---

## Shape Metrics

Calculate a limited set of metrics directly useful for later archetype development.

### Aspect Ratio

```text
aspect_ratio
```

### Compactness

Formula:

```text
4 × pi × area / perimeter²
```

Output:

```text
compactness
```

### Rectangularity

Formula:

```text
footprint_area / bounding_rectangle_area
```

Output:

```text
rectangularity
```

### Courtyard Metrics

Calculate:

```text
courtyard_area_m2
courtyard_ratio
```

### Shape Complexity

Calculate:

```text
vertex_count
```

No additional complexity metrics are required unless easily obtainable.

---

## Basic Shape Classification

Implement lightweight shape classification.

Classes:

```text
Rectangle
Square
Slab
Tower
L
U
Courtyard
Irregular
```

Outputs:

```text
shape_class
shape_confidence
```

This classification is intended only as a descriptive feature and not as an archetype assignment.

---

## Output Dataset

Each building record should contain the following fields where available:

```text
osmid
building_type
murb_confidence
murb_reason

footprint_area_m2
perimeter_m

length_m
width_m
aspect_ratio

height_m
height_est_m
height_source

levels
levels_est
levels_source

gross_floor_area_est_m2

compactness
rectangularity

courtyard_area_m2
courtyard_ratio

vertex_count

shape_class
shape_confidence

geometry
```

---

## Output Formats

### CSV

One row per building.

### GeoPackage

Include:

- Building geometry
- Original OSM attributes
- All calculated geometry metrics

### GeoJSON

Same contents as GeoPackage.

---

## Optional Visualizations

Generate:

1. Building footprint map.
2. Building height map.
3. Shape classification map.
4. Footprint-area distribution plots.
5. Height distribution plots.
6. Aspect-ratio distribution plots.

---

## Project Structure

```text
project/
│
├── config/
│   └── settings.yaml
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── outputs/
│
├── src/
│   ├── download_osm.py
│   ├── preprocess.py
│   ├── identify_murbs.py
│   ├── estimate_heights.py
│   ├── calculate_geometry.py
│   ├── classify_shapes.py
│   ├── export_results.py
│   └── run_pipeline.py
│
├── requirements.txt
└── README.md
```

---

## Required Libraries

```text
osmnx
geopandas
shapely
pyproj
numpy
pandas
matplotlib
folium
pyyaml
```

Optional:

```text
joblib
tqdm
```

---

## Performance Requirements

The workflow should:

- Process the complete Ottawa building inventory.
- Handle Overpass failures gracefully.
- Cache downloaded data.
- Avoid unnecessary re-downloads.
- Log all processing steps.
- Support reproducible reruns.

---

## Reproducibility Requirements

Provide:

- README.md
- requirements.txt
- Configuration file
- Command-line interface

Example:

```bash
python run_pipeline.py --city "Ottawa, Ontario, Canada"
```
