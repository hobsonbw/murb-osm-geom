"""Plot MURB footprint and geometry metrics and export percentile summaries.

Usage:
    python scripts/plot_footprint_area_by_city.py

By default, the script reads data/outputs/*_murb.csv and *_murbs.csv and writes:
    data/outputs/analysis/footprint_area.svg
    data/outputs/analysis/floor_height.svg
    data/outputs/analysis/floor_num.svg
    data/outputs/analysis/build_height.svg
    data/outputs/analysis/sample_size.csv
    data/outputs/analysis/footprint_area_summary.csv
    data/outputs/analysis/floor_height.csv
    data/outputs/analysis/floor_num.csv
    data/outputs/analysis/build_height.csv
    data/outputs/analysis/floor_height.csv
    data/outputs/analysis/floor_num.csv
    data/outputs/analysis/build_height.csv
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, MaxNLocator, MultipleLocator
import pandas as pd


PART_3_MIN_STOREYS = 3
PART_3_MIN_AREA_M2 = 600
PART_3_FLOOR_AREA_M2 = 87.6
MIN_PLOT_ENTRIES = 10
STOREY_HEIGHT_M = 3.0
LOCATIONS = {
    "calgary": "Calgary, AB",
    "vancouver": "Vancouver, BC",
    "winnipeg": "Winnipeg, MB",
    "saintjohn": "Saint John, NB",
    "stjohns": "St. John’s, NL",
    "yellowknife": "Yellowknife, NT",
    "halifax": "Halifax, NS",
    "iqaluit": "Iqaluit, NU",
    "toronto": "Toronto, ON",
    "charlottetown": "Charlottetown, PE",
    "montreal": "Montreal, QC",
    "saskatoon": "Saskatoon, SK",
    "whitehorse": "Whitehorse, YT",
}
STATISTICS = ("Minimum", "5th percentile", "50th percentile", "95th percentile", "Maximum")
HEIGHT_METRICS = ("Floor height (m)", "Number of floors", "Building height (m)")
HEIGHT_OUTPUTS = {
    "Floor height (m)": ("floor_height", "Floor Height Distribution"),
    "Number of floors": ("floor_num", "Number of Floors Distribution"),
    "Building height (m)": ("build_height", "Building Height Distribution"),
}
HEIGHT_AXIS_SETTINGS = {
    "Floor height (m)": {
        "bin_width": 0.25,
        "bin_start": 2.0,
        "x_ticks": tuple(2 + index * 0.25 for index in range(17)),
        "x_limits": (2, 6),
    },
    "Number of floors": {
        "bin_width": 4,
        "bin_start": 0.5,
        "bin_labels": True,
    },
    "Building height (m)": {
        "bin_width": 12,
        "bin_start": 0.0,
        "x_ticks": tuple(index * 12 for index in range(18)),
        "x_limits": (0, 204),
    },
}
GEOMETRY_METRICS = {
    "length_m": ("length (m)", "MURB Length", "Length (m)"),
    "width_m": ("width (m)", "MURB Width", "Width (m)"),
    "average_depth_m": ("average depth (m)", "MURB Average Depth", "Average depth (m)"),
    "aspect_ratio": ("aspect ratio", "MURB Aspect Ratio", "Aspect ratio"),
    "rectangularity": ("rectangularity", "MURB Rectangularity", "Rectangularity"),
}
GEOMETRY_SUMMARY_NAMES = {
    "length_m": "length_summary.csv",
    "width_m": "width_summary.csv",
    "average_depth_m": "average_depth_summary.csv",
    "aspect_ratio": "aspect_ratio_summary.csv",
    "rectangularity": "rectangularity_summary.csv",
}


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return dict.fromkeys(STATISTICS, 0.0)
    series = pd.Series(values)
    percentiles = series.quantile([0.05, 0.50, 0.95])
    return dict(zip(STATISTICS, (series.min(), percentiles.loc[0.05],
                                 percentiles.loc[0.50], percentiles.loc[0.95], series.max())))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot MURB metrics and export per-city summary tables."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory containing *_murb.csv or *_murbs.csv files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/analysis"),
        help="Directory for the SVG plots and summary CSVs.",
    )
    parser.add_argument(
        "--plot-name",
        default="footprint_area.svg",
        help="Output SVG filename.",
    )
    parser.add_argument(
        "--summary-name",
        default="footprint_area_summary.csv",
        help="Output summary CSV filename.",
    )
    parser.add_argument(
        "--sample-size-name",
        default="sample_size.csv",
        help="Output sample-size CSV filename.",
    )
    parser.add_argument("--floor-height-summary-name", default="floor_height.csv")
    parser.add_argument("--floor-num-summary-name", default="floor_num.csv")
    parser.add_argument("--build-height-summary-name", default="build_height.csv")
    return parser.parse_args()


def _city_name(csv_path: Path) -> str | None:
    suffix = "_murbs" if csv_path.stem.endswith("_murbs") else "_murb"
    name = csv_path.stem[:-len(suffix)]
    return LOCATIONS.get(name)


def _summarize(
    csv_path: Path,
) -> tuple[list[float], dict[str, list[float]], dict[str, int]]:
    frame = pd.read_csv(csv_path)
    confidence = pd.to_numeric(frame["murb_confidence"], errors="coerce")
    height = pd.to_numeric(frame["height_m"], errors="coerce")
    estimated_height = pd.to_numeric(frame["height_est_m"], errors="coerce")
    levels = pd.to_numeric(frame["levels"], errors="coerce")
    estimated_levels = pd.to_numeric(frame["levels_est"], errors="coerce")
    area = pd.to_numeric(frame["footprint_area_m2"], errors="coerce")
    geometry_values = {
        metric: pd.to_numeric(
            frame[metric] if metric in frame else pd.Series(index=frame.index, dtype=float),
            errors="coerce",
        )
        for metric in GEOMETRY_METRICS
    }
    likely = confidence.ge(0.77)

    more_than_three_storeys = (
        levels.gt(PART_3_MIN_STOREYS)
        | estimated_levels.gt(PART_3_MIN_STOREYS)
        | height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
        | estimated_height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
    )
    part_3_murbs = likely & area.ge(PART_3_FLOOR_AREA_M2) & (
        area.gt(PART_3_MIN_AREA_M2) | more_than_three_storeys
    )
    valid_values = area[part_3_murbs].dropna()
    explicit_height_data = part_3_murbs & height.gt(0) & levels.gt(0)
    floor_height_values = (height / levels)[explicit_height_data].dropna()
    plausible_floor_height = floor_height_values.between(2, 6)
    floor_height_values = floor_height_values[plausible_floor_height]
    levels_values = levels[floor_height_values.index]
    building_height_values = height[floor_height_values.index]
    counts = {
        "Possible MURBs": len(frame),
        "Likely MURBs": int(likely.sum()),
        "Part 3 MURBs": int(part_3_murbs.sum()),
        "Part 3 MURBs with Height": len(floor_height_values),
    }
    summary_data = {
        "footprint area (m2)": valid_values.tolist(),
        **{
            GEOMETRY_METRICS[metric][0]: values[part_3_murbs].dropna().tolist()
            for metric, values in geometry_values.items()
        },
        "Floor height (m)": floor_height_values.tolist(),
        "Number of floors": levels_values.tolist(),
        "Building height (m)": building_height_values.tolist(),
    }
    return valid_values.tolist(), summary_data, counts


def _write_boxplot(
    values: list[list[float]],
    labels: list[str],
    title: str,
    ylabel: str,
    plot_path: Path,
    is_area: bool = False,
    y_ticks: tuple[float, ...] | None = None,
) -> None:
    fig_width = max(10, len(labels) * 1.15)
    fig, ax = plt.subplots(figsize=(fig_width, 6.5))
    artists = ax.boxplot(
        values,
        tick_labels=labels,
        flierprops={"marker": ".", "markersize": 3},
    )
    for index, series in enumerate(values):
        color = "red" if labels[index] == "All" else "black"
        for kind in ("boxes", "medians", "fliers"):
            artists[kind][index].set_color(color)
        for kind in ("whiskers", "caps"):
            for line in artists[kind][2 * index:2 * index + 2]:
                line.set_color(color)
        flier = artists["fliers"][index]
        lower, upper = pd.Series(series).quantile([0.003, 0.997])
        visible = [
            (position, value)
            for position, value in zip(flier.get_xdata(), flier.get_ydata())
            if lower <= value <= upper
        ]
        flier.set_data(
            [position for position, _ in visible],
            [value for _, value in visible],
        )
        flier.set_markerfacecolor(color)
        flier.set_markeredgecolor(color)

    highest_displayed = max(
        max(line.get_ydata())
        for kind in ("boxes", "medians", "whiskers", "caps", "fliers")
        for line in artists[kind]
        if len(line.get_ydata())
    )
    if is_area:
        ax.set_ylim(0, (math.floor(highest_displayed / 2000) + 1) * 2000)
        ax.yaxis.set_major_locator(MultipleLocator(1000))
        ax.yaxis.set_minor_locator(MultipleLocator(250))
        ax.tick_params(axis="y", which="minor", length=3)
    else:
        ax.set_ylim(0, max(highest_displayed * 1.05, 1))
        locator = FixedLocator(y_ticks) if y_ticks is not None else MaxNLocator(nbins=8)
        ax.yaxis.set_major_locator(locator)
    ax.set_title(title)
    ax.set_xlabel("Locations")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    ax.get_xticklabels()[-1].set_color("red")
    fig.tight_layout()
    fig.savefig(plot_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def _write_histogram(
    values: list[float],
    title: str,
    xlabel: str,
    plot_path: Path,
    bin_width: float | None = None,
    bin_start: float = 0.0,
    bin_labels: bool = False,
    x_ticks: tuple[float, ...] | None = None,
    x_limits: tuple[float, float] | None = None,
) -> None:
    bins = "auto"
    if bin_width is not None:
        bin_end = x_limits[1] if x_limits is not None else max(values)
        bin_count = max(1, math.ceil((bin_end - bin_start) / bin_width))
        bins = [bin_start + index * bin_width for index in range(bin_count + 1)]

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.set_box_aspect(1)
    _, bin_edges, _ = ax.hist(
        values, bins=bins, color="#6f8f86", edgecolor="#263b35"
    )
    if bin_labels:
        tick_positions = (bin_edges[:-1] + bin_edges[1:]) / 2
        lower_floors = (bin_edges[:-1] + 0.5).round().astype(int)
        upper_floors = (bin_edges[1:] - 0.5).round().astype(int)
        tick_labels = [
            f"{lower}-{upper}"
            for lower, upper in zip(lower_floors, upper_floors)
        ]
        ax.set_xticks(tick_positions, tick_labels, rotation=45)
    elif bin_width is None:
        tick_indices = list(range(0, len(bin_edges), 2))
        if tick_indices[-1] != len(bin_edges) - 1:
            tick_indices.append(len(bin_edges) - 1)
        ticks = bin_edges[tick_indices]
        ax.set_xticks(ticks, [f"{edge:g}" for edge in ticks])
    if x_ticks is not None:
        ax.set_xticks(x_ticks, [f"{tick:g}" for tick in x_ticks], rotation=45)
    if x_limits is not None:
        ax.set_xlim(*x_limits)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Number of buildings")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(plot_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = _parse_args()
    metric_definitions = {
        "footprint_area_m2": (
            "footprint area (m2)",
            "MURB Footprint Area",
            "Footprint area (m$^2$)",
            args.plot_name,
            args.summary_name,
            True,
        ),
        **{
            metric: (
                label,
                title,
                ylabel,
                f"{metric.removesuffix('_m')}.svg",
                GEOMETRY_SUMMARY_NAMES[metric],
                False,
            )
            for metric, (label, title, ylabel) in GEOMETRY_METRICS.items()
        },
    }
    csv_paths = sorted(
        path for path in args.input_dir.glob("*.csv")
        if path.stem.endswith(("_murb", "_murbs"))
    )
    city_data: dict[str, tuple[list[float], dict[str, list[float]], dict[str, int]]] = {}
    for csv_path in csv_paths:
        city = _city_name(csv_path)
        if city is None:
            continue
        if city in city_data:
            print(f"Duplicate exports for {city}: {csv_path}", file=sys.stderr)
            return 1
        try:
            city_data[city] = _summarize(csv_path)
        except (KeyError, ValueError, pd.errors.ParserError) as err:
            print(f"Unable to process {csv_path}: {err}", file=sys.stderr)
            return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample_rows = []
    metric_rows = {metric: [] for metric in metric_definitions}
    height_rows = {metric: [] for metric in HEIGHT_METRICS}
    all_metric_values: dict[str, list[float]] = {
        metric: [] for metric in metric_definitions
    }
    all_heights: dict[str, list[float]] = {metric: [] for metric in HEIGHT_METRICS}
    all_counts = dict.fromkeys(("Possible MURBs", "Likely MURBs", "Part 3 MURBs",
                               "Part 3 MURBs with Height"), 0)
    for city in LOCATIONS.values():
        _, metrics, counts = city_data.get(
            city, ([], {
                **{definition[0]: [] for definition in metric_definitions.values()},
                **{metric: [] for metric in HEIGHT_METRICS},
            },
                   dict.fromkeys(all_counts, 0))
        )
        sample_rows.append({"Locations": city, **counts})
        for metric, (label, *_rest) in metric_definitions.items():
            metric_values = metrics[label]
            metric_rows[metric].append({"Locations": city, **{
                f"{statistic} {label}": value
                for statistic, value in _statistics(metric_values).items()
            }})
            all_metric_values[metric].extend(metric_values)
        for metric in HEIGHT_METRICS:
            height_rows[metric].append({"Locations": city, **{
                f"{statistic} {metric}": value
                for statistic, value in _statistics(metrics[metric]).items()
            }})
            all_heights[metric].extend(metrics[metric])
        for metric in all_counts:
            all_counts[metric] += counts[metric]

    sample_rows.append({"Locations": "All", **all_counts})
    for metric, (label, *_rest) in metric_definitions.items():
        metric_rows[metric].append({"Locations": "All", **{
            f"{statistic} {label}": value
            for statistic, value in _statistics(all_metric_values[metric]).items()
        }})
    for metric in HEIGHT_METRICS:
        height_rows[metric].append({"Locations": "All", **{
            f"{statistic} {metric}": value
            for statistic, value in _statistics(all_heights[metric]).items()
        }})

    sample_path = args.output_dir / args.sample_size_name
    pd.DataFrame(sample_rows).to_csv(sample_path, index=False)
    summary_paths = {}
    for metric, (_, _, _, _, summary_name, _) in metric_definitions.items():
        summary_path = args.output_dir / summary_name
        pd.DataFrame(metric_rows[metric]).to_csv(
            summary_path, index=False, float_format="%.6f"
        )
        summary_paths[metric] = summary_path
    height_summary_names = {
        "Floor height (m)": args.floor_height_summary_name,
        "Number of floors": args.floor_num_summary_name,
        "Building height (m)": args.build_height_summary_name,
    }
    height_summary_paths = {}
    for metric, summary_name in height_summary_names.items():
        height_summary_path = args.output_dir / summary_name
        pd.DataFrame(height_rows[metric]).to_csv(
            height_summary_path, index=False, float_format="%.6f"
        )
        height_summary_paths[metric] = height_summary_path

    print(f"Wrote {sample_path}")
    for summary_path in summary_paths.values():
        print(f"Wrote {summary_path}")
    for height_summary_path in height_summary_paths.values():
        print(f"Wrote {height_summary_path}")
    for metric, (label, title, ylabel, plot_name, _, is_area) in metric_definitions.items():
        all_values = all_metric_values[metric]
        if not all_values:
            continue
        labels = [
            city for city in LOCATIONS.values()
            if len(city_data.get(city, ([], {}, {}))[1].get(label, [])) >= MIN_PLOT_ENTRIES
        ]
        plot_values = [city_data[city][1][label] for city in labels]
        labels.append("All")
        plot_values.append(all_values)
        plot_path = args.output_dir / plot_name
        y_ticks = tuple(index / 10 for index in range(11)) if metric == "rectangularity" else None
        _write_boxplot(
            plot_values, labels, title, ylabel, plot_path, is_area, y_ticks
        )
        print(f"Wrote {plot_path}")
    for metric, (file_stem, title) in HEIGHT_OUTPUTS.items():
        values = all_heights[metric]
        if not values:
            continue
        plot_path = args.output_dir / f"{file_stem}.svg"
        _write_histogram(
            values,
            title,
            metric,
            plot_path,
            **HEIGHT_AXIS_SETTINGS.get(metric, {}),
        )
        print(f"Wrote {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())