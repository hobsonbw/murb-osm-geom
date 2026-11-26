# City and consultant analysis

Run the commands below from the project root.

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

`data/outputs/analysis/exploratory/osm_metric_filter_counts.csv` records the filter policy,
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

Exploratory outputs live in `data/outputs/analysis/exploratory/`, separate
from individual metric tables and figures in `data/outputs/analysis/`.
The full building CSVs remain in `data/outputs/`. Distribution-audit outputs
are not regenerated by the regular city-analysis command:

- [`osm_distribution_diagnostics.csv`](../data/outputs/analysis/exploratory/osm_distribution_diagnostics.csv):
  pooled/per-city raw, hypothetical IQR-retained, and log-raw diagnostics.
  The retained height views describe the prior all-metric IQR scenario, not
  the current unfiltered height outputs. Zero p-values indicate numeric
  underflow; the log10 p-value column preserves their magnitude.
- [`osm_iqr_summary_sensitivity.csv`](../data/outputs/analysis/exploratory/osm_iqr_summary_sensitivity.csv):
  raw versus hypothetical IQR-retained min/max and 5th/50th/95th percentiles,
  with exclusion counts and changes; height comparisons are hypothetical.
- [`osm_metric_distributions.svg`](../data/outputs/analysis/exploratory/osm_metric_distributions.svg):
  full-range untrimmed histograms with normal reference curves.
- [`osm_normal_qq.svg`](../data/outputs/analysis/exploratory/osm_normal_qq.svg) and
  [`osm_log_normal_qq.svg`](../data/outputs/analysis/exploratory/osm_log_normal_qq.svg):
  normal Q-Q comparisons before filtering, on original and log scales.
- [`footprint_outlier_method_comparison.csv`](../data/outputs/analysis/exploratory/footprint_outlier_method_comparison.csv):
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

Outputs are [`osm_correlation_matrix.svg`](../data/outputs/analysis/exploratory/osm_correlation_matrix.svg),
[`osm_correlation_pearson.csv`](../data/outputs/analysis/exploratory/osm_correlation_pearson.csv),
[`osm_correlation_spearman.csv`](../data/outputs/analysis/exploratory/osm_correlation_spearman.csv),
and [`osm_correlation_counts.csv`](../data/outputs/analysis/exploratory/osm_correlation_counts.csv).
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
