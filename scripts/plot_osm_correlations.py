"""Plot paired OSM metrics and export pairwise correlation matrices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import pandas as pd

if __package__:
    from .plot_footprint_area_by_city import (
        GEOMETRY_METRICS, HEIGHT_METRICS, _city_name, _load_city_data,
        _metric_frame, _pooled_iqr_bounds,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.plot_footprint_area_by_city import (
        GEOMETRY_METRICS, HEIGHT_METRICS, _city_name, _load_city_data,
        _metric_frame, _pooled_iqr_bounds,
    )


METRICS = (
    "footprint area (m2)",
    *(label for label, _, _ in GEOMETRY_METRICS.values()),
    *HEIGHT_METRICS,
)
PLOT_LABELS = (
    "Footprint\n(m²)", "Length\n(m)", "Width\n(m)", "Avg. depth\n(m)",
    "Aspect\nratio", "Rectangularity", "Floor height\n(m)",
    "Floors", "Building height\n(m)",
)


def _load_filtered_metrics(input_dir: Path) -> pd.DataFrame:
    city_data = _load_city_data(input_dir)
    if not city_data:
        raise ValueError(f"No configured city exports found in {input_dir}")
    bounds = _pooled_iqr_bounds(city_data)
    frames = [
        _metric_frame(pd.read_csv(path))
        for path in sorted(input_dir.glob("*.csv"))
        if path.stem.endswith(("_murb", "_murbs")) and _city_name(path) is not None
    ]
    metrics = pd.concat(frames, ignore_index=True).loc[:, METRICS]
    for metric in METRICS:
        if metric in HEIGHT_METRICS:
            continue
        limits = bounds.get(metric)
        if limits is None:
            if metrics[metric].notna().any():
                raise ValueError(f"Missing pooled IQR bounds for {metric}")
            continue
        metrics[metric] = metrics[metric].where(metrics[metric].between(*limits))
    return metrics


def _correlation_tables(
    metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pearson = metrics.corr(method="pearson", min_periods=2)
    spearman = metrics.corr(method="spearman", min_periods=2)
    available = metrics.notna().astype("int64")
    counts = available.T.dot(available)
    return pearson, spearman, counts


def _format_correlation(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:.2f}"


def _write_scatter_matrix(
    metrics: pd.DataFrame,
    pearson: pd.DataFrame,
    spearman: pd.DataFrame,
    counts: pd.DataFrame,
    output: Path,
) -> None:
    size = len(METRICS)
    fig, axes = plt.subplots(size, size, figsize=(20, 20), squeeze=False)
    for row, y_metric in enumerate(METRICS):
        for column, x_metric in enumerate(METRICS):
            ax = axes[row, column]
            if row == column:
                values = metrics[x_metric].dropna()
                if not values.empty:
                    ax.hist(values, bins=20, color="#6f8f86")
                ax.text(.05, .93, f"n={len(values):,}", transform=ax.transAxes,
                        ha="left", va="top", fontsize=8)
                ax.set_yticks([])
            elif row > column:
                pairs = metrics[[x_metric, y_metric]].dropna()
                ax.scatter(
                    pairs[x_metric], pairs[y_metric], s=3, alpha=.24,
                    color="#263b35", edgecolors="none", rasterized=True,
                )
                ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
                ax.yaxis.set_major_locator(MaxNLocator(nbins=3))
                ax.grid(alpha=.15)
            else:
                ax.set_facecolor("#f4f6f5")
                text = (
                    f"Pearson r = {_format_correlation(pearson.loc[y_metric, x_metric])}\n"
                    f"Spearman ρ = {_format_correlation(spearman.loc[y_metric, x_metric])}\n"
                    f"n = {counts.loc[y_metric, x_metric]:,}"
                )
                ax.text(.5, .5, text, transform=ax.transAxes,
                        ha="center", va="center", fontsize=8)
                ax.set_xticks([])
                ax.set_yticks([])
            ax.tick_params(labelsize=7)
            if row != size - 1:
                ax.tick_params(labelbottom=False)
            if column != 0:
                ax.tick_params(labelleft=False)
            if row == size - 1:
                ax.set_xlabel(PLOT_LABELS[column], fontsize=9)
            if column == 0:
                ax.set_ylabel(PLOT_LABELS[row], fontsize=9)
    fig.suptitle(
        "OSM Part 3 metrics: pairwise scatterplots and correlations\n"
        "Geometry: pooled IQR-filtered; height metrics: eligible, unfiltered",
        fontsize=16,
    )
    fig.tight_layout(rect=(0, 0, 1, .96), w_pad=.45, h_pad=.45)
    fig.savefig(output, format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/outputs"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/outputs/analysis/exploratory"),
    )
    args = parser.parse_args()
    try:
        metrics = _load_filtered_metrics(args.input_dir)
        if metrics.notna().sum().sum() == 0:
            raise ValueError("No eligible OSM metric values found")
        pearson, spearman, counts = _correlation_tables(metrics)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, table in (
            ("osm_correlation_pearson.csv", pearson),
            ("osm_correlation_spearman.csv", spearman),
            ("osm_correlation_counts.csv", counts),
        ):
            table.to_csv(args.output_dir / name, index_label="Metric", float_format="%.8f")
        _write_scatter_matrix(
            metrics, pearson, spearman, counts, args.output_dir / "osm_correlation_matrix.svg",
        )
    except (OSError, KeyError, ValueError, pd.errors.ParserError) as error:
        print(f"Unable to create OSM correlation matrix: {error}", file=sys.stderr)
        return 1
    print(f"Wrote OSM correlation plot and three matrices to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
