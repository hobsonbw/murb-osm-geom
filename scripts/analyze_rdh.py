"""Summarize and plot consultant real-data housing metrics by climate zone."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

if __package__:
    from .plot_footprint_area_by_city import _statistics, _write_histogram
else:
    from plot_footprint_area_by_city import _statistics, _write_histogram


DEFAULT_INPUT = Path("data/raw/2026 09 23 Project Matrix DRAFT - for NRCAN.csv")
RDH_METRICS = (
    ("Building Storeys", "floor_num", "Number of floors"),
    ("Building Height (m)", "build_height", "Building height (m)"),
    (
        "Typical/Tower Floor Plate Area (m2)",
        "footprint_area",
        "Footprint area (m2)",
    ),
    (
        "VFAR (Vertical Surface Area to Floor Area Ratio)",
        "VFAR",
        "VFAR",
    ),
    ("Overall WWR", "overall_wwr", "Overall WWR (%)"),
    ("North WWR", "north_wwr", "North WWR (%)"),
    ("East WWR", "east_wwr", "East WWR (%)"),
    ("South WWR", "south_wwr", "South WWR (%)"),
    ("West WWR", "west_wwr", "West WWR (%)"),
)
RDH_PLOT_TITLES = {
    "floor_num": "Number of Floors Distribution",
    "build_height": "Building Height Distribution",
    "footprint_area": "Footprint Area Distribution",
    "VFAR": "VFAR Distribution",
    "overall_wwr": "Overall WWR Distribution",
    "north_wwr": "North WWR Distribution",
    "east_wwr": "East WWR Distribution",
    "south_wwr": "South WWR Distribution",
    "west_wwr": "West WWR Distribution",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize and plot RDH metrics by climate zone."
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DEFAULT_INPUT,
        help="Consultant RDH CSV file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/analysis"),
        help="Directory for RDH summary CSVs and histogram SVGs.",
    )
    return parser.parse_args()


def _load_rdh(csv_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    required_columns = {"Climate Zone", *(source for source, _, _ in RDH_METRICS)}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    climate_zone = frame["Climate Zone"].astype("string").str.strip()
    climate_zone = climate_zone.replace({"7A": "7", "7B": "7"})
    frame["Climate Zone"] = climate_zone
    frame = frame.loc[climate_zone.notna() & climate_zone.ne("")].copy()

    for source, _, _ in RDH_METRICS:
        values = frame[source].astype("string").str.strip()
        values = values.str.replace(",", "", regex=False).str.replace("%", "", regex=False)
        frame[source] = pd.to_numeric(values, errors="coerce")
    return frame


def _write_rdh_outputs(frame: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    climate_zones = sorted(frame["Climate Zone"].dropna().unique())

    for source, metric_stem, label in RDH_METRICS:
        plot_stem = metric_stem
        if metric_stem.endswith("_wwr"):
            orientation = metric_stem.removesuffix("_wwr")
            plot_stem = f"wwr_{orientation}"
            for old_path in (
                output_dir / f"{metric_stem}_rdh.svg",
                output_dir / f"{metric_stem}_rdh_summary.csv",
            ):
                if old_path.exists():
                    old_path.unlink()

        summary_rows = []
        for zone in climate_zones:
            values = frame.loc[frame["Climate Zone"].eq(zone), source].dropna().tolist()
            summary_rows.append({
                "Climate Zone": zone,
                **{
                    f"{statistic} {label}": value
                    for statistic, value in _statistics(values).items()
                },
            })

        all_values = frame[source].dropna().tolist()
        summary_rows.append({
            "Climate Zone": "All",
            **{
                f"{statistic} {label}": value
                for statistic, value in _statistics(all_values).items()
            },
        })
        summary_path = output_dir / f"{plot_stem}_rdh_summary.csv"
        pd.DataFrame(summary_rows).to_csv(
            summary_path, index=False, float_format="%.6f"
        )

        if not all_values:
            print(f"Wrote {summary_path}")
            continue

        plot_settings = {}
        if metric_stem == "floor_num":
            plot_settings = {
                "bin_width": 4,
                "bin_start": 0.5,
                "bin_labels": True,
                "bin_label_offset": 0.5,
            }
        elif metric_stem == "build_height":
            upper = max(12, math.ceil(max(all_values) / 12) * 12)
            plot_settings = {
                "bin_width": 12,
                "bin_start": 0,
                "x_ticks": tuple(range(0, upper + 12, 12)),
                "x_limits": (0, upper),
            }
        elif metric_stem == "footprint_area":
            plot_settings = {
                "bin_width": 500,
                "bin_start": 0,
                "bin_labels": True,
                "bin_label_offset": 0,
                "x_limits": (0, 6000),
            }
        elif metric_stem.endswith("_wwr"):
            plot_settings = {
                "bin_width": 5,
                "bin_start": 0,
                "x_ticks": tuple(range(0, 71, 5)),
                "x_limits": (0, 70),
            }

        plot_path = output_dir / f"{plot_stem}_rdh.svg"
        plot_title = RDH_PLOT_TITLES[metric_stem]
        plot_label = (
            "Footprint area (m$^2$)"
            if metric_stem == "footprint_area"
            else label
        )
        _write_histogram(
            all_values,
            plot_title,
            plot_label,
            plot_path,
            **plot_settings,
        )
        print(f"Wrote {summary_path}")
        print(f"Wrote {plot_path}")


def main() -> int:
    args = _parse_args()
    try:
        frame = _load_rdh(args.input_csv)
        _write_rdh_outputs(frame, args.output_dir)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"Unable to process {args.input_csv}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())