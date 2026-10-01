"""Plot footprint area against number of floors for OSM and RDH records."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .analyze_rdh import DEFAULT_INPUT, _load_rdh
    from .plot_footprint_area_by_city import (
        LOCATIONS,
        PART_3_FLOOR_AREA_M2,
        PART_3_MIN_AREA_M2,
        PART_3_MIN_STOREYS,
        STOREY_HEIGHT_M,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.analyze_rdh import DEFAULT_INPUT, _load_rdh
    from scripts.plot_footprint_area_by_city import (
        LOCATIONS,
        PART_3_FLOOR_AREA_M2,
        PART_3_MIN_AREA_M2,
        PART_3_MIN_STOREYS,
        STOREY_HEIGHT_M,
    )


DEFAULT_OSM_DIR = Path("data/outputs")
DEFAULT_OUTPUT = Path("data/outputs/analysis/floor_area_vs_floors.svg")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare OSM and RDH footprint area against number of floors."
    )
    parser.add_argument(
        "--osm-dir",
        type=Path,
        default=DEFAULT_OSM_DIR,
        help="Directory containing OSM *_murb.csv and *_murbs.csv exports.",
    )
    parser.add_argument(
        "--rdh-csv",
        type=Path,
        default=DEFAULT_INPUT,
        help="RDH consultant CSV file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output SVG path.",
    )
    return parser.parse_args()


def _load_osm_points(input_dir: Path) -> pd.DataFrame:
    csv_paths = sorted(
        path for path in input_dir.glob("*.csv")
        if path.stem.endswith(("_murb", "_murbs"))
    )
    points = []
    seen_cities = set()
    for csv_path in csv_paths:
        suffix = "_murbs" if csv_path.stem.endswith("_murbs") else "_murb"
        city = csv_path.stem[:-len(suffix)]
        if city not in LOCATIONS:
            continue
        if city in seen_cities:
            raise ValueError(f"Duplicate OSM exports for {city}")
        seen_cities.add(city)

        frame = pd.read_csv(csv_path)
        confidence = pd.to_numeric(frame["murb_confidence"], errors="coerce")
        area = pd.to_numeric(frame["footprint_area_m2"], errors="coerce")
        levels = pd.to_numeric(frame["levels"], errors="coerce")
        estimated_levels = pd.to_numeric(frame["levels_est"], errors="coerce")
        height = pd.to_numeric(frame["height_m"], errors="coerce")
        estimated_height = pd.to_numeric(frame["height_est_m"], errors="coerce")

        more_than_three_storeys = (
            levels.gt(PART_3_MIN_STOREYS)
            | estimated_levels.gt(PART_3_MIN_STOREYS)
            | height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
            | estimated_height.gt(PART_3_MIN_STOREYS * STOREY_HEIGHT_M)
        )
        part_3 = confidence.ge(0.77) & area.ge(PART_3_FLOOR_AREA_M2) & (
            area.gt(PART_3_MIN_AREA_M2) | more_than_three_storeys
        )
        explicit_height_data = part_3 & height.gt(0) & levels.gt(0)
        plausible_floor_height = (height / levels).between(2, 6)
        valid = explicit_height_data & plausible_floor_height & area.gt(0)
        points.append(pd.DataFrame({
            "footprint_area_m2": area[valid],
            "floors": levels[valid],
            "source": "OSM",
        }))

    if not points:
        return pd.DataFrame(columns=["footprint_area_m2", "floors", "source"])
    return pd.concat(points, ignore_index=True)


def _load_rdh_points(csv_path: Path) -> pd.DataFrame:
    frame = _load_rdh(csv_path)
    area = pd.to_numeric(
        frame["Typical/Tower Floor Plate Area (m2)"], errors="coerce"
    )
    floors = pd.to_numeric(frame["Building Storeys"], errors="coerce")
    valid = area.gt(0) & floors.gt(0)
    return pd.DataFrame({
        "footprint_area_m2": area[valid],
        "floors": floors[valid],
        "source": "Consultants",
    })


def _load_comparison_data(osm_dir: Path, rdh_csv: Path) -> pd.DataFrame:
    osm = _load_osm_points(osm_dir)
    rdh = _load_rdh_points(rdh_csv)
    return pd.concat([osm, rdh], ignore_index=True)


def _trim_percentiles(points: pd.DataFrame) -> pd.DataFrame:
    keep = pd.Series(True, index=points.index)
    for column in ("floors", "footprint_area_m2"):
        lower, upper = points[column].quantile([0.003, 0.997])
        keep &= points[column].between(lower, upper)
    return points.loc[keep].reset_index(drop=True)


def _write_scatterplot(points: pd.DataFrame, output_path: Path) -> None:
    colors = {"OSM": "#000000", "Consultants": "#d16543"}
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.set_box_aspect(1)

    for source in ("OSM", "Consultants"):
        subset = points.loc[points["source"].eq(source)]
        if subset.empty:
            continue
        ax.scatter(
            subset["footprint_area_m2"],
            subset["floors"],
            s=10 if source == "OSM" else 36,
            alpha=0.45 if source == "OSM" else 0.85,
            color=colors[source],
            edgecolors="none",
            label=f"{source} (n={len(subset):,})",
            rasterized=True,
        )

    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_title("Number of Floors vs. Footprint Area")
    ax.set_xlabel("Number of floors")
    ax.set_ylabel("Footprint area (m$^2$)")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = _parse_args()
    try:
        points = _load_comparison_data(args.osm_dir, args.rdh_csv)
        if points.empty:
            raise ValueError("No valid OSM or RDH area/floor pairs were found")
        initial_counts = points["source"].value_counts().to_dict()
        points = _trim_percentiles(points)
        if points.empty:
            raise ValueError("No records remain after percentile trimming")
        _write_scatterplot(points, args.output)
    except (OSError, KeyError, ValueError, pd.errors.ParserError) as error:
        print(f"Unable to create footprint/floor comparison: {error}", file=sys.stderr)
        return 1

    counts = points["source"].value_counts().to_dict()
    print(f"Wrote {args.output}")
    print(
        f"Loaded {initial_counts.get('OSM', 0)} explicit-height OSM records and "
        f"{initial_counts.get('Consultants', 0)} consultant records; plotted "
        f"{counts.get('OSM', 0)} OSM and {counts.get('Consultants', 0)} consultant "
        f"records after percentile trimming"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())