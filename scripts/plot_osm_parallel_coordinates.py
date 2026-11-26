"""Generate interactive parallel-coordinate plots of filtered OSM metrics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

if __package__:
    from .plot_osm_correlations import METRICS, _load_filtered_metrics
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.plot_osm_correlations import METRICS, _load_filtered_metrics


LABELS = (
    "Footprint (m²)", "Length (m)", "Width (m)", "Avg. depth (m)",
    "Aspect ratio", "Rectangularity", "Floor height (m)",
    "Floors", "Building height (m)",
)
GEOMETRY_METRICS = METRICS[:6]
ALL_METRIC_RANGES = {
    METRICS[0]: (0, 3000),
    METRICS[1]: (0, 120),
    METRICS[2]: (0, 120),
    METRICS[3]: (0, 120),
    METRICS[4]: (1, 5),
    METRICS[5]: (0.25, 1),
    METRICS[6]: (0, 6),
    METRICS[7]: (0, 70),
    METRICS[8]: (0, 220),
}


def _plot(
    metrics: pd.DataFrame,
    columns: tuple[str, ...],
    title: str,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> go.Figure:
    complete = metrics.dropna(subset=list(columns))
    if complete.empty:
        raise ValueError(f"No buildings have all metrics required for {title}")
    dimensions = []
    for column in columns:
        limits = ranges.get(column) if ranges else None
        if limits is not None and not complete[column].between(*limits).all():
            raise ValueError(f"Values for {column} fall outside the fixed axis range {limits}")
        dimensions.append(go.parcoords.Dimension(
            label=LABELS[METRICS.index(column)],
            values=complete[column].tolist(),
            range=limits,
        ))
    figure = go.Figure(go.Parcoords(
        line={"color": "rgba(35, 91, 126, 0.35)"},
        dimensions=dimensions,
        labelfont={"size": 12},
        tickfont={"size": 11},
    ))
    figure.update_layout(
        title={"text": f"{title} (n={len(complete):,})", "x": 0.5, "y": 0.97},
        height=720,
        margin={"l": 70, "r": 70, "t": 150, "b": 60},
        annotations=[{
            "text": "Drag along an axis to select a range; selections on multiple axes combine.",
            "xref": "paper", "yref": "paper", "x": 0.5, "y": 1.16,
            "showarrow": False,
        }],
    )
    return figure


def _normalized_plot(metrics: pd.DataFrame) -> go.Figure:
    complete = metrics.dropna(subset=list(METRICS))
    if complete.empty:
        raise ValueError("No buildings have all metrics required for normalized plot")
    minimum = complete.loc[:, METRICS].min()
    maximum = complete.loc[:, METRICS].max()
    constant = [metric for metric in METRICS if minimum[metric] == maximum[metric]]
    if constant:
        raise ValueError(f"Cannot normalize constant metrics: {', '.join(constant)}")
    normalized = (complete.loc[:, METRICS] - minimum) / (maximum - minimum)
    figure = _plot(
        normalized, METRICS, "OSM Part 3 metrics: observed min–max normalized",
        ranges={metric: (0, 1) for metric in METRICS},
    )
    for dimension, label in zip(figure.data[0].dimensions, LABELS):
        dimension.label = label.split(" (")[0]
    range_labels = [
        f"{label}: {minimum[metric]:.5g}–{maximum[metric]:.5g}"
        for label, metric in zip(LABELS, METRICS)
    ]
    rows = ["  |  ".join(range_labels[start:start + 3]) for start in range(0, 9, 3)]
    figure.update_layout(height=850, margin={"l": 70, "r": 70, "t": 150, "b": 190})
    figure.add_annotation(
        text="Observed ranges in original units (rounded):<br>" + "<br>".join(rows),
        xref="paper", yref="paper", x=0.5, y=-0.11, yanchor="top",
        showarrow=False, font={"size": 11},
    )
    return figure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/outputs"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/outputs/analysis/exploratory"),
    )
    args = parser.parse_args()
    try:
        metrics = _load_filtered_metrics(args.input_dir)
        plots = (
            ("osm_parallel_geometry.html", _plot(
                metrics, GEOMETRY_METRICS, "OSM Part 3 geometry metrics",
            )),
            ("osm_parallel_all_metrics.html", _plot(
                metrics, METRICS, "OSM Part 3 geometry and height metrics",
                ranges=ALL_METRIC_RANGES,
            )),
            ("osm_parallel_all_metrics_normalized.html", _normalized_plot(metrics)),
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, figure in plots:
            figure.write_html(args.output_dir / name, include_plotlyjs=True)
    except (OSError, KeyError, ValueError, pd.errors.ParserError) as error:
        print(f"Unable to create OSM parallel-coordinate plots: {error}", file=sys.stderr)
        return 1
    print(f"Wrote OSM parallel-coordinate plots to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
