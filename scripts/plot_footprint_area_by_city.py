"""Plot MURB footprint areas by city and export percentile summaries.

Usage:
    python scripts/plot_footprint_area_by_city.py

By default, the script reads data/outputs/*_murbs.csv and writes:
    data/outputs/footprint_area_by_city_part3.svg
    data/outputs/footprint_area_summary_part3.csv
    data/outputs/height_part3.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


PART_3_MIN_STOREYS = 3
PART_3_MIN_AREA_M2 = 600
STOREY_HEIGHT_M = 3.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot valid MURB footprint areas for each city."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory containing *_murbs.csv files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/analysis"),
        help="Directory for the SVG plot and summary CSV.",
    )
    parser.add_argument(
        "--plot-name",
        default="footprint_area_by_city_part3.svg",
        help="Output SVG filename.",
    )
    parser.add_argument(
        "--summary-name",
        default="footprint_area_summary_part3.csv",
        help="Output summary CSV filename.",
    )
    parser.add_argument(
        "--height-summary-name",
        default="height_part3.csv",
        help="Output aggregate height summary CSV filename.",
    )
    return parser.parse_args()


def _city_name(csv_path: Path) -> str:
    suffix = "_murbs"
    name = csv_path.stem[:-len(suffix)] if csv_path.stem.endswith(suffix) else csv_path.stem
    return name.replace("_", " ").title()


def _summarize(
    csv_path: Path,
) -> tuple[str, list[float], dict[str, list[float]], dict[str, object]]:
    city = _city_name(csv_path)
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

    part_3_by_area = likely & area.gt(PART_3_MIN_AREA_M2)
    more_than_three_storeys = (
        levels.gt(PART_3_MIN_STOREYS)
        | estimated_levels.gt(PART_3_MIN_STOREYS)
        | height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
        | estimated_height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
    )
    part_3_murbs = likely & (
        area.gt(PART_3_MIN_AREA_M2) | more_than_three_storeys
    )
    valid_values = area[part_3_murbs]
    explicit_height_data = part_3_murbs & height.gt(0) & levels.gt(0)
    floor_height_values = (height / levels)[explicit_height_data].dropna()
    plausible_floor_height = floor_height_values.between(2, 6)
    floor_height_values = floor_height_values[plausible_floor_height]
    levels_values = levels[floor_height_values.index]
    building_height_values = height[floor_height_values.index]
    percentiles = valid_values.quantile([0.05, 0.50, 0.95])

    summary = {
        "city": city,
        "Possible MURBs": len(frame),
        "Likely MURBs": int(likely.sum()),
        "Part 3 MURBs": int(part_3_murbs.sum()),
        "Minimum footprint area (m2)": valid_values.min() if not valid_values.empty else None,
        "5th percentile footprint area (m2)": percentiles.loc[0.05] if not valid_values.empty else None,
        "50th percentile footprint area (m2)": percentiles.loc[0.50] if not valid_values.empty else None,
        "95th percentile footprint area (m2)": percentiles.loc[0.95] if not valid_values.empty else None,
        "Maximum footprint area (m2)": valid_values.max() if not valid_values.empty else None,
    }
    height_summary_data = {
        "Floor height (m)": floor_height_values.tolist(),
        "Number of floors": levels_values.tolist(),
        "Building height (m)": building_height_values.tolist(),
    }
    return city, valid_values.tolist(), height_summary_data, summary


def main() -> int:
    args = _parse_args()
    csv_paths = sorted(args.input_dir.glob("*_murbs.csv"))
    if not csv_paths:
        print(f"No *_murbs.csv files found in {args.input_dir}", file=sys.stderr)
        return 1

    labels: list[str] = []
    data: list[list[float]] = []
    height_data: dict[str, list[float]] = {
        "Floor height (m)": [],
        "Number of floors": [],
        "Building height (m)": [],
    }
    summaries: list[dict[str, object]] = []
    for csv_path in csv_paths:
        try:
            city, valid_values, city_height_values, summary = _summarize(csv_path)
        except (KeyError, ValueError, pd.errors.ParserError) as err:
            print(f"Unable to process {csv_path}: {err}", file=sys.stderr)
            return 1
        if valid_values:
            labels.append(city)
            data.append(valid_values)
        for metric, values in city_height_values.items():
            height_data[metric].extend(values)
        summaries.append(summary)

    if not data:
        print("No MURBs meet the filters in any city", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / args.summary_name
    pd.DataFrame(summaries).to_csv(summary_path, index=False, float_format="%.6f")

    statistic_columns = [
        "Minimum",
        "5th percentile",
        "50th percentile",
        "95th percentile",
        "Maximum",
    ]
    height_summary_rows = []
    for metric, values in height_data.items():
        series = pd.Series(values)
        percentiles = series.quantile([0.05, 0.50, 0.95])
        height_summary_rows.append({
            "Metric": metric,
            "n": len(series),
            "Minimum": series.min(),
            "5th percentile": percentiles.loc[0.05],
            "50th percentile": percentiles.loc[0.50],
            "95th percentile": percentiles.loc[0.95],
            "Maximum": series.max(),
        })
    height_summary_path = args.output_dir / args.height_summary_name
    pd.DataFrame(height_summary_rows, columns=["Metric", "n"] + statistic_columns).to_csv(
        height_summary_path, index=False, float_format="%.6f"
    )

    fig_width = max(10, len(labels) * 1.15)
    fig, ax = plt.subplots(figsize=(fig_width, 6.5))
    ax.boxplot(
        data,
        tick_labels=labels,
        patch_artist=True,
        boxprops={"facecolor": "#78a6c8", "edgecolor": "#19324a"},
        whiskerprops={"color": "#19324a"},
        capprops={"color": "#19324a"},
        medianprops={"color": "#c0392b", "linewidth": 2},
        flierprops={"marker": ".", "markerfacecolor": "#c0392b", "markeredgecolor": "#c0392b", "markersize": 3, "alpha": 0.35},
    )
    ax.set_title("MURB Footprint Area by City")
    ax.set_xlabel("City")
    ax.set_ylabel("Footprint area (m^2)")
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    plot_path = args.output_dir / args.plot_name
    fig.savefig(plot_path, format="svg", bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {plot_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {height_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())