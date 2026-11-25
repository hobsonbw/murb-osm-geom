# Calgary PBF Investigation: Deduplication and Tag Mapping

## Conclusion

The loss from roughly 473,000 building polygons to 134 records was a
**workflow bug**, not genuine duplication or missing buildings in the PBF.
The previous version of this analysis incorrectly attributed the loss to
Geofabrik coverage and GDAL layer limitations.

Two independent ingestion problems were confirmed:

1. **Wrong identity column.** GDAL's `multipolygons` layer includes both
   closed building ways and multipolygon relations. Relations have `osm_id`;
   ways have `osm_way_id` and a null `osm_id`. Preprocessing renamed only
   `osm_id` to `osmid`, then deduplicated on it. All null way IDs were treated
   as duplicates, retaining only one way.
2. **Unexpanded tags.** GDAL stores `height`, `roof:height`,
   `building:levels`, `building:flats`, and `addr:housenumber` in the
   HSTORE-formatted `other_tags` field by default. Downstream scoring and height
   estimation expect separate columns, so these values were effectively invisible.

GDAL does not expose a `ways` layer. Its `multipolygons` layer already includes
area ways; the absence of a separately named layer does not imply absent data.
See the [GDAL OSM driver documentation](https://gdal.org/en/stable/drivers/vector/osm.html).

## Measured Processing Flow

Re-read `data/raw/canada-261122.osm.pbf` using the saved Calgary boundary,
GDAL 3.12.4, pyogrio 0.13.0, and GeoPandas 1.1.4. The read filtered to
nonempty `building` tags and the boundary bounding box, then clipped to the
actual boundary.

```text
PBF building areas intersecting Calgary bounding box: 478,392
        |
Clip to Calgary boundary: 472,995
        |
Normalize IDs: 472,862 ways + 133 relations
        |
Preprocess & deduplicate: 472,995 retained; 0 duplicates
        |
Existing MURB filter (confidence >= 0.50): 59,335 candidates
```

The previous report recorded 472,990 clipped features, five fewer than this
read. That small difference has not been isolated; it does not affect the
confirmed identity-collapse mechanism. All 472,995 audited geometries were
valid MultiPolygons after clipping, with no null/empty geometry losses.

### Reproducing the 134-record failure

| Identity field in clipped data | Populated | Null |
|--------------------------------|----------:|-----:|
| `osm_id` (relations) | 133 | 472,862 |
| `osm_way_id` (ways) | 472,862 | 133 |

Applying the old `drop_duplicates("osm_id")` to this data produces
**exactly 134 records**: 133 relations and one arbitrarily retained way.
Thus **472,861 distinct building ways were discarded as supposed duplicates**.
No geometric similarity or footprint-size criterion caused this loss.

Ways and relations use separate OSM ID namespaces, so deduplication must use
`(element_type, osmid)`, not a bare numeric ID.

## Tag Recovery and Classification

The audited PBF contains substantial height and level information:

| Raw tag restored from `other_tags` | Buildings with a value |
|-----------------------------------|-----------------------:|
| `height` | 6,342 |
| `roof:height` | 3 |
| `building:levels` | 39,662 |
| `building:flats` | 447 |
| `addr:housenumber` | 257,387 |

These are raw non-null tag counts across all building areas, not necessarily
valid numeric values or MURB-only counts.

With only identity handling fixed, the existing classifier retains **58,835**
candidates. Restoring the tags increases this to **59,335**, including
**986 candidates with parsed explicit heights** and **4,893 with parsed
explicit levels**. The scoring rules and confidence threshold were unchanged.

| Retained `building` type | Candidates |
|-------------------------|-----------:|
| residential | 56,258 |
| apartments | 2,572 |
| terrace | 361 |
| yes | 139 |
| dormitory | 5 |
| **Total** | **59,335** |

The remaining reduction from 472,995 to 59,335 is classification, not
deduplication. The input includes 223,386 houses, 94,090 garages, 57,179
generic `yes` buildings, and other non-MURB types. Most do not meet the
configured confidence threshold.

**Important qualification:** `building=residential` alone scores 0.55,
above the 0.50 threshold. The 56,258 residential candidates are therefore not
confirmed multi-unit buildings. Most retained candidates lack explicit height
or levels. This qualification applies to the broad exported **possible MURB**
pool, not equally to the stricter downstream analysis cohort.

## Downstream Analysis Criteria

The separate city-analysis script, `scripts/plot_footprint_area_by_city.py`,
narrows the exported candidates using these existing rules:

- **Likely MURBs:** confidence >= 0.77.
- **Part 3 MURBs:** likely MURBs with footprint >= 87.6 m2, and either
  footprint > 600 m2 or more than three storeys.
- The storey criterion accepts explicit/estimated levels > 3 or
  explicit/estimated height > 9 m.
- **Height-analysis subset:** Part 3 candidates with positive explicit
  height and levels, and an explicit height/levels ratio between 2 and 6 m,
  inclusive.

A residential tag alone does not pass the 0.77 threshold, regardless of
footprint size. Storey/flat-count and address evidence can increase its
confidence. The scoring weights are heuristics, not calibrated probabilities;
these filters do not independently verify dwelling counts or regulatory
classification. This investigation does not change the selection rules.

### Measured Calgary Cohorts

The corrected PBF loader was rerun on the full local extract. After
preprocessing, scoring, and height estimation, footprint area was calculated
in the working CRS (EPSG:3978), using the same `geometry.area` calculation as
the pipeline. The persisted candidates were passed to the existing
`_summarize` helper without changing its filters.

| Cohort | Saved Overpass | Broken PBF | Corrected PBF |
|--------|---------------:|-----------:|--------------:|
| Possible MURBs (confidence >= 0.50) | 11,036 | 32 | 59,335 |
| Likely MURBs (confidence >= 0.77) | 262 | 16 | 2,830 |
| Part 3 MURBs | 141 | 16 | 1,612 |
| Part 3 height-analysis subset | 2 | 0 | 166 |

Thus the broad 59,335-candidate pool narrows to **1,612 Part 3 candidates**,
of which **166** have the explicit height/levels data and plausible
floor-height ratio required for height analysis. The median footprint of the
Part 3 cohort is **1,061 m2**. Part 3 counts are approximately 11.4 times the
saved Overpass count; differences in source snapshot/acquisition coverage
have not been isolated.

The 166-record subset is narrower than the 986 candidates with explicit
heights: it also requires passing the Likely and Part 3 filters, explicit
levels, and the 2-6 m height/levels check.

Measured counts are saved in
[`data/outputs/analysis/calgary_pbf_corrected_cohort.csv`](data/outputs/analysis/calgary_pbf_corrected_cohort.csv).
A separate corrected checkpoint containing all 59,335 possible candidates,
their geometries, raw tags, height estimates, and footprint areas is retained at
`data/processed/calgary_pbf_corrected_checkpoint.gpkg`.
This avoids another country-wide PBF read for further cohort analysis.
It does not contain the remaining geometry/shape metrics yet; those can be
calculated from this checkpoint with:

```powershell
.\.venv\Scripts\python.exe -m src.run_pipeline --city "Calgary, Alberta, Canada" --basename calgary_pbf_corrected --from-checkpoint
```

This basename writes separate exports rather than replacing the original
Calgary files. The initial cohort measurement did not regenerate the city
plots; the subsequent full refresh below did.

## Comparison with the Saved Overpass Output

The saved old output contains 11,036 classified candidates, not a complete
raw building inventory:

| Metric | Saved Overpass output | Broken PBF output | Corrected PBF audit |
|--------|----------------------:|------------------:|--------------------:|
| MURB candidates | 11,036 | 32 | 59,335 |
| Parsed explicit heights | 33 | 0 | 986 |
| Parsed explicit levels | 298 | 0 | 4,893 |

All **11,036 old output IDs occur in the corrected clean PBF inventory**.
Of these, **11,035 also pass the current MURB filter**. The corrected
candidate set has 48,300 additional IDs and one old ID no longer retained.
The excluded old candidate, way 1327771897, was `building=apartments` in
the saved Overpass output and is `building=house` in this PBF, explaining
its exclusion under the unchanged rules.
This comparison uses numeric IDs because the old CSV does not export
`element_type`; the corrected Calgary candidate set has no numeric ID
collisions between element types.

The cause of the larger corrected candidate set has not been isolated.
Snapshot dates, previous acquisition coverage, and tag changes would need
separate comparison. The evidence does **not** support the former claims that
PBF contains only a curated subset, omits ordinary ways, or strips height tags.

## Full 13-City Refresh

The canonical city exports, cohort tables, and OSM plots have now been
regenerated for the 13 configured analysis cities from
`canada-261122.osm.pbf`. Ottawa was intentionally excluded and its existing
export was left unchanged.

The old committed analysis is retained by the local Git tag
`overpass-analysis-baseline` at commit `6693f0a`. New workflow changes and
results are on branch `pbf-analysis-refresh`, in separate commits.
The baseline city CSVs were checked against its sample-size table before
comparison; they are internally consistent.

| Cohort, all configured cities | Baseline | New PBF | Change |
|------------------------------|---------:|--------:|-------:|
| Possible MURBs | 36,371 | 133,011 | +96,640 |
| Likely MURBs | 12,822 | 41,396 | +28,574 |
| Part 3 candidates | 6,611 | 13,559 | +6,948 |
| Height-analysis subset | 133 | 377 | +244 |

The largest Part 3 increases are Calgary (+1,471), Toronto (+2,158), and the
newly populated Montreal (+2,691), Saskatoon (+481), and Whitehorse (+26)
outputs. Zero baseline counts for those last three cities mean no records were
available in that analysis, not that they had no MURBs.

Outputs:

- [`sample_size.csv`](data/outputs/analysis/sample_size.csv): current cohorts
  for every configured city and the aggregate.
- [`cohort_comparison.csv`](data/outputs/analysis/cohort_comparison.csv):
  baseline/current counts and changes in the same city order.
- [`pbf_refresh_manifest.json`](data/outputs/analysis/pbf_refresh_manifest.json):
  source filename and SHA-256, the workflow revision used for generation,
  city list, acquisition counts, and shape-cohort selection.
- Canonical `<city>_murbs.csv` exports under `data/outputs/`, plus local
  GeoPackage/GeoJSON exports and checkpoints.
- Refreshed geometry/height figures, floor-area/floors comparison, and
  shape comparison under `data/outputs/analysis/`.

**Intentional rule change:** OSM shape comparison now uses the same Part 3
mask as geometry plots. The old shape figure used all Possible MURBs, so its
shape counts are not a dataset-only, like-for-like comparison. Other selection
thresholds are unchanged; consultant-only figures/data are unchanged.

The shape figure contains **13,559 OSM Part 3 candidates**. Height histograms
use **377** records; the floor-area/floors scatter contains **371 OSM records**
after its additional pooled percentile trimming. Average-depth summaries use
**13,545 valid Part 3 depths**; the existing calculation still excludes
genuinely multipart polygons. Singleton MultiPolygons from GDAL are now
handled like their equivalent Polygons (Calgary has 1,610 valid depths among
1,612 Part 3 candidates).

All 13 CSV/GeoPackage/GeoJSON/checkpoint row counts, nine pooled summary tables,
and 11 SVGs were verified. The refresh required one streaming source read and
bounded two-process geometry calculations. A Winnipeg topology error exposed
the need to repair invalid areas before clipping; the existing repair policy
was reused rather than skipping failed features. Later batch-format safeguards
promote polygonal areas to conformant MultiPolygon layers and exclude
boundary-only line/point intersections before temporary serialization; these
do not change the final candidate cohort.

The generation manifest records revision `33380d5`. Subsequent batch-format
hardening and comparison-row ordering were committed separately. Large local
PBF/intermediate/binary files remain excluded from Git under the existing
repository rules; city CSVs, analysis outputs, and this report are retained
in the results commit. No branch or tag has been pushed.

## Changes and Validation

- `src/download_osm.py` reads the actual GDAL `multipolygons` area layer,
  extracts the required tags with GDAL's `hstore_get_value`, applies a
  bounding-box filter, and clips to the boundary. Read failures propagate
  rather than becoming a partial successful result.
- `src/preprocess.py` combines the two GDAL identity columns and assigns
  `element_type`; deduplication uses both type and ID when available.
  Missing or ambiguous GDAL IDs raise an error rather than silently collapsing
  buildings. Overpass tile duplicates still deduplicate.
- `tests/test_osm_ingestion.py` covers distinct way IDs, way/relation numeric
  ID collisions, missing/ambiguous IDs, and an actual GDAL OSM-driver read
  exercising clipping, escaped tags, MURB scoring, and height estimation.
- Corrected preprocessing, classification, and height estimation were replayed
  on every audited Calgary PBF building. The corrected PBF loader was then
  rerun end to end for cohort measurement. SQL tag extraction was also verified
  with a small XML fixture using the same GDAL OSM driver.
- Existing Part 3 minimum-footprint regression passed. Both the saved corrected
  checkpoint and the cohort-count CSV were read back and verified.

The initial Calgary-only audit did **not** overwrite the original exports or
checkpoints. The later full refresh has now replaced the broken 32-record
canonical Calgary run and regenerated its analysis. To rebuild a single city
from the PBF rather than a checkpoint:

```powershell
.\.venv\Scripts\python.exe -m src.run_pipeline --city "Calgary, Alberta, Canada"
```

The current configuration already points at the local PBF. Country-sized
PBF reads remain slow because GDAL must reconstruct OSM geometries; the audit
read took about 15 minutes despite returning only the Calgary subset.
Regional extracts or a one-time conversion to an indexed GIS format can
improve repeated-read performance, but reverting to Overpass is not required
to address the demonstrated data loss.
