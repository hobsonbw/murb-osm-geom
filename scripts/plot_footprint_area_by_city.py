"""Plot MURB footprint areas by city and export percentile summaries.

Usage:
    python scripts/plot_footprint_area_by_city.py

By default, the script reads data/outputs/*_murb.csv and *_murbs.csv and writes:
    data/outputs/analysis/footprint_area.svg
    data/outputs/analysis/sample_size.csv
    data/outputs/analysis/footprint_area_summary.csv
    data/outputs/analysis/height.csv
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
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


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return dict.fromkeys(STATISTICS, 0.0)
    series = pd.Series(values)
    percentiles = series.quantile([0.05, 0.50, 0.95])
    return dict(zip(STATISTICS, (series.min(), percentiles.loc[0.05],
                                 percentiles.loc[0.50], percentiles.loc[0.95], series.max())))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot valid MURB footprint areas for each city."
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
        help="Directory for the SVG plot and summary CSV.",
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
    parser.add_argument(
        "--height-summary-name",
        default="height.csv",
        help="Output per-location height summary CSV filename.",
    )
    return parser.parse_args()


def _city_name(csv_path: Path) -> str | None:
    suffix = "_murbs" if csv_path.stem.endswith("_murbs") else "_murb"
    name = csv_path.stem[:-len(suffix)]
    return LOCATIONS.get(name)


def _summarize(
    csv_path: Path,
) -> tuple[list[float], dict[str, list[float]], dict[str, int]]:
    frame = pd.read_csv(
        csv_path,
        usecols=[
            "murb_confidence",
            "height_m",
            "height_est_m",
            "levels",
            "levels_est",
            "footprint_area_m2",
        ],
    )
    confidence = pd.to_numeric(frame["murb_confidence"], errors="coerce")
    height = pd.to_numeric(frame["height_m"], errors="coerce")
    estimated_height = pd.to_numeric(frame["height_est_m"], errors="coerce")
    levels = pd.to_numeric(frame["levels"], errors="coerce")
    estimated_levels = pd.to_numeric(frame["levels_est"], errors="coerce")
    area = pd.to_numeric(frame["footprint_area_m2"], errors="coerce")
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
    height_summary_data = {
        "Floor height (m)": floor_height_values.tolist(),
        "Number of floors": levels_values.tolist(),
        "Building height (m)": building_height_values.tolist(),
    }
    return valid_values.tolist(), height_summary_data, counts


def main() -> int:
    args = _parse_args()
    csv_paths = sorted(
        path for path in args.input_dir.glob("*.csv")
        if path.stem.endswith(("_murb", "_murbs"))
    )
    labels: list[str] = []
    data: list[list[float]] = []
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
    footprint_rows = []
    height_rows = []
    all_areas: list[float] = []
    all_heights: dict[str, list[float]] = {metric: [] for metric in HEIGHT_METRICS}
    all_counts = dict.fromkeys(("Possible MURBs", "Likely MURBs", "Part 3 MURBs",
                               "Part 3 MURBs with Height"), 0)
    for city in LOCATIONS.values():
        areas, heights, counts = city_data.get(
            city, ([], {metric: [] for metric in HEIGHT_METRICS},
                   dict.fromkeys(all_counts, 0))
        )
        sample_rows.append({"Locations": city, **counts})
        footprint_rows.append({"Locations": city, **{
            f"{statistic} footprint area (m2)": value
            for statistic, value in _statistics(areas).items()
        }})
        height_rows.append({"Locations": city, **{
            f"{metric} {statistic}": value
            for metric in HEIGHT_METRICS
            for statistic, value in _statistics(heights[metric]).items()
        }})
        if len(areas) >= MIN_PLOT_ENTRIES:
            labels.append(city)
            data.append(areas)
        all_areas.extend(areas)
        for metric in HEIGHT_METRICS:
            all_heights[metric].extend(heights[metric])
        for metric in all_counts:
            all_counts[metric] += counts[metric]

    sample_rows.append({"Locations": "All", **all_counts})
    footprint_rows.append({"Locations": "All", **{
        f"{statistic} footprint area (m2)": value
        for statistic, value in _statistics(all_areas).items()
    }})
    height_rows.append({"Locations": "All", **{
        f"{metric} {statistic}": value
        for metric in HEIGHT_METRICS
        for statistic, value in _statistics(all_heights[metric]).items()
    }})

    sample_path = args.output_dir / args.sample_size_name
    pd.DataFrame(sample_rows).to_csv(sample_path, index=False)
    summary_path = args.output_dir / args.summary_name
    pd.DataFrame(footprint_rows).to_csv(summary_path, index=False, float_format="%.6f")
    height_summary_path = args.output_dir / args.height_summary_name
    pd.DataFrame(height_rows).to_csv(height_summary_path, index=False, float_format="%.6f")

    print(f"Wrote {sample_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {height_summary_path}")
    if not all_areas:
        return 0

    labels.append("All")
    data.append(all_areas)
    fig_width = max(10, len(labels) * 1.15)
    fig, ax = plt.subplots(figsize=(fig_width, 6.5))
    artists = ax.boxplot(
        data,
        tick_labels=labels,
        flierprops={"marker": ".", "markersize": 3},
    )
    for index, values in enumerate(data):
        color = "red" if labels[index] == "All" else "black"
        for kind in ("boxes", "medians", "fliers"):
            artists[kind][index].set_color(color)
        for kind in ("whiskers", "caps"):
            for line in artists[kind][2 * index:2 * index + 2]:
                line.set_color(color)
        flier = artists["fliers"][index]
        lower, upper = pd.Series(values).quantile([0.003, 0.997])
        visible = [(position, value) for position, value in zip(flier.get_xdata(), flier.get_ydata())
               if lower <= value <= upper]
        flier.set_data([position for position, _ in visible], [value for _, value in visible])
        flier.set_markerfacecolor(color)
        flier.set_markeredgecolor(color)
    highest_displayed = max(
        max(line.get_ydata())
        for kind in ("boxes", "medians", "whiskers", "caps", "fliers")
        for line in artists[kind]
        if len(line.get_ydata())
    )
    ax.set_ylim(0, (math.floor(highest_displayed / 2000) + 1) * 2000)
    ax.yaxis.set_major_locator(MultipleLocator(1000))
    ax.yaxis.set_minor_locator(MultipleLocator(250))
    ax.tick_params(axis="y", which="minor", length=3)
    ax.set_title("MURB Footprint Area")
    ax.set_xlabel("Locations")
    ax.set_ylabel("Footprint area (m$^2$)")
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    ax.get_xticklabels()[-1].set_color("red")
    fig.tight_layout()
    plot_path = args.output_dir / args.plot_name
    fig.savefig(plot_path, format="svg", bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())