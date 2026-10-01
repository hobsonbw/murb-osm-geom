"""Compare approximate OSM and consultant building-shape counts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .analyze_rdh import DEFAULT_INPUT
    from .plot_footprint_area_by_city import LOCATIONS
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.analyze_rdh import DEFAULT_INPUT
    from scripts.plot_footprint_area_by_city import LOCATIONS


DEFAULT_OSM_DIR = Path("data/outputs")
DEFAULT_OUTPUT = Path("data/outputs/analysis/shape_comparison.svg")
SHAPE_CATEGORIES = (
    "Square",
    "Rectangular",
    "L-shaped",
    "U/C-shaped",
    "Courtyard",
    "Other / Irregular",
)
OSM_SHAPE_MAP = {
    "square": "Square",
    "tower": "Square",
    "rectangle": "Rectangular",
    "slab": "Rectangular",
    "l": "L-shaped",
    "u": "U/C-shaped",
    "courtyard": "Courtyard",
    "irregular": "Other / Irregular",
}
RDH_SHAPE_MAP = {
    "square": "Square",
    "rectangular": "Rectangular",
    "l-shape": "L-shaped",
    "u-shape": "U/C-shaped",
    "c-shape": "U/C-shaped",
    "other": "Other / Irregular",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare approximate shape counts for OSM and consultant buildings."
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


def _map_shapes(values: pd.Series, mapping: dict[str, str]) -> pd.Series:
    normalized = values.astype("string").str.strip().str.casefold()
    return normalized.map(mapping).fillna("Other / Irregular")


def _load_shape_counts(osm_dir: Path, rdh_csv: Path) -> pd.DataFrame:
    osm_counts = pd.Series(0, index=SHAPE_CATEGORIES, dtype=int)
    seen_cities = set()
    csv_paths = sorted(
        path for path in osm_dir.glob("*.csv")
        if path.stem.endswith(("_murb", "_murbs"))
    )
    for csv_path in csv_paths:
        suffix = "_murbs" if csv_path.stem.endswith("_murbs") else "_murb"
        city = csv_path.stem[:-len(suffix)]
        if city not in LOCATIONS:
            continue
        if city in seen_cities:
            raise ValueError(f"Duplicate OSM exports for {city}")
        seen_cities.add(city)
        frame = pd.read_csv(csv_path, usecols=["shape_class"])
        shapes = _map_shapes(frame["shape_class"], OSM_SHAPE_MAP)
        osm_counts = osm_counts.add(
            shapes.value_counts().reindex(SHAPE_CATEGORIES, fill_value=0),
            fill_value=0,
        ).astype(int)

    rdh = pd.read_csv(
        rdh_csv,
        usecols=["Climate Zone", "Building Shape"],
        dtype=str,
        encoding="utf-8-sig",
    )
    zones = rdh["Climate Zone"].astype("string").str.strip()
    rdh = rdh.loc[zones.notna() & zones.ne("")]
    rdh_shapes = _map_shapes(rdh["Building Shape"], RDH_SHAPE_MAP)
    rdh_counts = rdh_shapes.value_counts().reindex(SHAPE_CATEGORIES, fill_value=0)

    return pd.DataFrame({
        "OSM": osm_counts,
        "Consultants": rdh_counts.astype(int),
    }).rename_axis("Approximate shape")


def _write_shape_plot(counts: pd.DataFrame, output_path: Path) -> None:
    colors = {"OSM": "#286a8a", "Consultants": "#d16543"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.5), sharey=True)
    y_positions = range(len(SHAPE_CATEGORIES))

    for axis, source in zip(axes, ("OSM", "Consultants")):
        values = counts[source].reindex(SHAPE_CATEGORIES).fillna(0).astype(int)
        bars = axis.barh(
            list(y_positions),
            values,
            color=colors[source],
            height=0.68,
        )
        axis.set_yticks(list(y_positions), SHAPE_CATEGORIES)
        axis.invert_yaxis()
        axis.set_xlim(0, max(values.max() * 1.16, 1))
        axis.set_title(f"{source} (n={values.sum():,})")
        axis.set_xlabel("Number of buildings")
        axis.grid(axis="x", alpha=0.25)
        axis.set_axisbelow(True)
        for bar, value in zip(bars, values):
            axis.text(
                bar.get_width() + max(values.max() * 0.015, 0.05),
                bar.get_y() + bar.get_height() / 2,
                f"{value:,}",
                va="center",
                fontsize=9,
            )

    axes[1].tick_params(axis="y", labelleft=False)
    fig.suptitle("Approximate Building Shape Counts")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = _parse_args()
    try:
        counts = _load_shape_counts(args.osm_dir, args.rdh_csv)
        if counts.to_numpy().sum() == 0:
            raise ValueError("No OSM or consultant shape categories were found")
        _write_shape_plot(counts, args.output)
    except (OSError, KeyError, ValueError, pd.errors.ParserError) as error:
        print(f"Unable to create shape comparison: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {args.output}")
    print(", ".join(f"{source}: {int(counts[source].sum()):,}" for source in counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())