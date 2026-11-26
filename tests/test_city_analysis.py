import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
from scipy import stats

from scripts.analyze_rdh import RDH_METRICS, main as analyze_rdh
from scripts.plot_footprint_area_by_city import (
    LOCATIONS,
    _filter_metric_values,
    _iqr_bounds,
    _summarize,
    _write_histogram,
    main,
)
from scripts.plot_floor_area_relationship import (
    _filter_comparison_iqr,
    _load_comparison_data,
    _trim_percentiles,
    _write_scatterplot,
)
from scripts.plot_osm_correlations import (
    METRICS,
    _correlation_tables,
    _load_filtered_metrics,
    _write_scatter_matrix,
)
from scripts.plot_shape_comparison import _load_shape_counts


class CityAnalysisTests(unittest.TestCase):
    def test_pairwise_spearman_uses_only_complete_pairs_and_reranks_ties(self):
        metrics = pd.DataFrame({
            "x": [1, 2, 2, 4, 5],
            "y": [3, 1, None, 4, 5],
            "z": [8, None, None, None, None],
        })
        pearson, spearman, counts = _correlation_tables(metrics)
        pairs = metrics[["x", "y"]].dropna()
        self.assertEqual(counts.loc["x", "y"], 4)
        self.assertEqual(counts.loc["x", "z"], 1)
        self.assertAlmostEqual(pearson.loc["x", "y"], stats.pearsonr(pairs["x"], pairs["y"]).statistic)
        self.assertAlmostEqual(spearman.loc["x", "y"], stats.spearmanr(pairs["x"], pairs["y"]).statistic)
        self.assertTrue(pd.isna(pearson.loc["x", "z"]))
        self.assertTrue(pd.isna(spearman.loc["x", "z"]))

    def test_correlation_matrix_uses_matched_pairs_and_metric_specific_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "calgary_murbs.csv"
            pd.DataFrame({
                "murb_confidence": [0.9] * 11 + [0.2],
                "height_m": [12] * 10 + [150, 12],
                "height_est_m": [12] * 10 + [150, 12],
                "levels": [4] * 10 + [30, 4],
                "levels_est": [4] * 10 + [30, 4],
                "footprint_area_m2": [*range(700, 710), 5000, 705],
                "width_m": [*range(10, 21), 15],
                "average_depth_m": [5] * 9 + [None, 5, 5],
            }).to_csv(source, index=False)
            original = source.read_bytes()
            metrics = _load_filtered_metrics(root)
            pearson, spearman, counts = _correlation_tables(metrics)
            area, width, depth = METRICS[0], METRICS[2], METRICS[3]
            floor_height, floors, building_height = METRICS[6:]

            self.assertEqual(counts.loc[area, area], 10)
            self.assertEqual(counts.loc[width, width], 11)
            self.assertEqual(counts.loc[area, width], 10)
            self.assertEqual(counts.loc[area, depth], 9)
            self.assertEqual(counts.loc[floors, building_height], 11)
            self.assertTrue(pd.isna(metrics.loc[10, area]))
            self.assertEqual(metrics.loc[10, floors], 30)
            self.assertEqual(metrics.loc[10, building_height], 150)
            self.assertEqual(metrics.loc[10, floor_height], 5)
            self.assertTrue(metrics.loc[11].isna().all())
            self.assertAlmostEqual(pearson.loc[area, width], 1)
            self.assertAlmostEqual(spearman.loc[area, width], 1)
            self.assertAlmostEqual(pearson.loc[floors, building_height], 1)
            self.assertAlmostEqual(spearman.loc[floors, building_height], 1)
            self.assertTrue(pd.isna(pearson.loc[area, building_height]))
            self.assertTrue(pd.isna(spearman.loc[area, building_height]))
            self.assertTrue(pd.isna(pearson.loc[area, METRICS[1]]))

            output = root / "correlations.svg"
            with patch("scripts.plot_osm_correlations.plt.close"):
                _write_scatter_matrix(metrics, pearson, spearman, counts, output)
            figure = plt.gcf()
            try:
                self.assertEqual(len(figure.axes), 81)
                self.assertEqual(len(figure.axes[2 * 9].collections[0].get_offsets()), 10)
                self.assertIn("n = 10", figure.axes[2].texts[0].get_text())
                self.assertTrue(output.exists())
            finally:
                plt.close(figure)
            self.assertEqual(source.read_bytes(), original)

    def test_city_box_requires_ten_valid_footprints(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            output_dir = Path(directory) / "output"
            input_dir.mkdir()
            for city, count in (("calgary", 9), ("vancouver", 10)):
                pd.DataFrame({
                    "murb_confidence": [0.9] * count,
                    "height_m": [12] * count,
                    "height_est_m": [12] * count,
                    "levels": [4] * count,
                    "levels_est": [4] * count,
                    "footprint_area_m2": [700] * count,
                }).to_csv(input_dir / f"{city}_murbs.csv", index=False)

            with patch.object(sys, "argv", ["analysis", "--input-dir", str(input_dir),
                                            "--output-dir", str(output_dir)]):
                self.assertEqual(main(), 0)

            plot = (output_dir / "footprint_area.svg").read_text(encoding="utf-8")
            self.assertNotIn("Calgary, AB", plot)
            self.assertIn("Vancouver, BC", plot)
            self.assertIn("<!-- All -->", plot)
            samples = pd.read_csv(output_dir / "sample_size.csv").set_index("Locations")
            self.assertEqual(samples.loc["All", "Part 3 MURBs"], 19)

    def test_plot_and_summary_use_the_same_iqr_filtered_values(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            input_dir.mkdir()
            areas = [100, *range(650, 750), 900, 10000]
            pd.DataFrame({
                "murb_confidence": [0.9] * len(areas),
                "height_m": [12] * len(areas),
                "height_est_m": [12] * len(areas),
                "levels": [4] * len(areas),
                "levels_est": [4] * len(areas),
                "footprint_area_m2": areas,
            }).to_csv(input_dir / "calgary_murbs.csv", index=False)
            with patch.object(sys, "argv", ["analysis", "--input-dir", str(input_dir),
                                            "--output-dir", str(Path(directory) / "output")]), \
                  patch("scripts.plot_footprint_area_by_city.plt.close"), \
                  patch("scripts.plot_footprint_area_by_city._write_histogram"):
                self.assertEqual(main(), 0)

            figure = plt.gcf()
            try:
                axis = figure.axes[0]
                self.assertEqual([label.get_text() for label in axis.get_xticklabels()],
                                 ["Calgary, AB", "All"])
                self.assertEqual(axis.get_ylabel(), "Footprint area (m$^2$)")
                self.assertEqual([label.get_color() for label in axis.get_xticklabels()],
                                 ["black", "red"])
                boxes = [line for line in axis.lines if len(line.get_xdata()) == 5]
                self.assertEqual([box.get_color() for box in boxes], ["black", "red"])
                fliers = [line for line in axis.lines if line.get_marker() == "."]
                self.assertEqual([list(line.get_ydata()) for line in fliers], [[], []])
                self.assertEqual([line.get_color() for line in fliers], ["black", "red"])
                self.assertEqual(axis.get_ylim(), (0, 2000))
                self.assertEqual([tick for tick in axis.get_yticks() if 0 <= tick <= 2000],
                                 [0, 1000, 2000])
                self.assertIsInstance(axis.yaxis.get_minor_locator(), MultipleLocator)
                self.assertEqual(axis.yaxis.get_minor_locator().tick_values(0, 2000)[1:4].tolist(),
                                 [0, 250, 500])
                self.assertEqual(pd.read_csv(Path(directory) / "output" / "footprint_area_summary.csv")
                                 .iloc[-1]["Maximum footprint area (m2)"], 749)
                filters = pd.read_csv(
                    Path(directory) / "output" / "exploratory" / "osm_metric_filter_counts.csv"
                )
                footprint = filters.loc[
                    filters["Locations"].eq("All")
                    & filters["Metric"].eq("footprint area (m2)")
                ].iloc[0]
                self.assertEqual(footprint["Retained count"], 100)
                self.assertEqual(footprint["Excluded count"], 3)
            finally:
                plt.close(figure)

    def test_iqr_bounds_handle_zero_spread_and_missing_values_explicitly(self):
        bounds = _iqr_bounds(list(range(11)))
        self.assertEqual(bounds, (-5.0, 15.0))
        self.assertEqual(_filter_metric_values([-6, -5, 15, 16], bounds), [-5, 15])
        values = [3.0] * 9 + [4.0]
        bounds = _iqr_bounds(values)
        self.assertEqual(bounds, (3.0, 3.0))
        self.assertEqual(_filter_metric_values(values, bounds), [3.0] * 9)
        self.assertIsNone(_iqr_bounds([]))
        self.assertEqual(_filter_metric_values([], None), [])
        with self.assertRaises(ValueError):
            _filter_metric_values([3.0], None)
        with self.assertRaises(ValueError):
            _iqr_bounds([float("inf")])

    def test_pooled_iqr_is_metric_specific_and_does_not_modify_building_csvs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            input_dir.mkdir()
            for city, areas in (
                ("calgary", [*range(100, 110), 10000]),
                ("vancouver", [1000]),
            ):
                pd.DataFrame({
                    "murb_confidence": [0.9] * len(areas),
                    "height_m": [12] * len(areas),
                    "height_est_m": [12] * len(areas),
                    "levels": [4] * len(areas),
                    "levels_est": [4] * len(areas),
                    "footprint_area_m2": areas,
                }).to_csv(input_dir / f"{city}_murbs.csv", index=False)
            original = {path: path.read_bytes() for path in input_dir.glob("*.csv")}
            output_dir = root / "output"
            with patch.object(sys, "argv", [
                "analysis", "--input-dir", str(input_dir), "--output-dir", str(output_dir),
            ]), patch("scripts.plot_footprint_area_by_city._write_boxplot") as boxplot, \
                    patch("scripts.plot_footprint_area_by_city._write_histogram"):
                self.assertEqual(main(), 0)

            summary = pd.read_csv(output_dir / "footprint_area_summary.csv").set_index(
                "Locations"
            )
            self.assertEqual(summary.loc["All", "Maximum footprint area (m2)"], 109)
            self.assertEqual(summary.loc["All", "50th percentile footprint area (m2)"], 104.5)
            filters = pd.read_csv(output_dir / "exploratory" / "osm_metric_filter_counts.csv").set_index(
                ["Locations", "Metric"]
            )
            footprint = filters.loc[("All", "footprint area (m2)")]
            self.assertEqual(footprint["Input count"], 12)
            self.assertEqual(footprint["Retained count"], 10)
            self.assertEqual(footprint["Lower bound"], 94.5)
            self.assertEqual(footprint["Upper bound"], 116.5)
            self.assertEqual(
                filters.loc[("Vancouver, BC", "footprint area (m2)"), "Retained count"], 0
            )
            self.assertEqual(filters.loc[("All", "Number of floors"), "Retained count"], 12)
            self.assertEqual(
                filters.loc[("Vancouver, BC", "Number of floors"), "Retained count"], 1
            )
            samples = pd.read_csv(output_dir / "sample_size.csv").set_index("Locations")
            self.assertEqual(samples.loc["All", "Part 3 MURBs"], 12)
            self.assertEqual(boxplot.call_args.args[0], [list(range(100, 110))] * 2)
            for path, content in original.items():
                self.assertEqual(path.read_bytes(), content)

    def test_height_metrics_are_unfiltered_in_tables_histograms_and_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir, output_dir = root / "input", root / "output"
            input_dir.mkdir()
            pd.DataFrame({
                "murb_confidence": [0.9] * 11,
                "height_m": [12] * 10 + [150],
                "height_est_m": [12] * 10 + [150],
                "levels": [4] * 10 + [30],
                "levels_est": [4] * 10 + [30],
                "footprint_area_m2": [700] * 10 + [10000],
            }).to_csv(input_dir / "calgary_murbs.csv", index=False)
            with patch.object(sys, "argv", [
                "analysis", "--input-dir", str(input_dir), "--output-dir", str(output_dir),
            ]), patch("scripts.plot_footprint_area_by_city._write_boxplot"), \
                    patch("scripts.plot_footprint_area_by_city._write_histogram") as histogram:
                self.assertEqual(main(), 0)
            expected = {
                "Floor height (m)": ("floor_height.csv", 5),
                "Number of floors": ("floor_num.csv", 30),
                "Building height (m)": ("build_height.csv", 150),
            }
            counts = pd.read_csv(output_dir / "exploratory" / "osm_metric_filter_counts.csv").set_index(
                ["Locations", "Metric"]
            )
            for metric, (filename, maximum) in expected.items():
                summary = pd.read_csv(output_dir / filename).set_index("Locations")
                self.assertEqual(summary.loc["All", f"Maximum {metric}"], maximum)
                report = counts.loc[("All", metric)]
                self.assertEqual(report["Input count"], 11)
                self.assertEqual(report["Retained count"], 11)
                self.assertEqual(report["Excluded count"], 0)
                self.assertEqual(report["Filter"], "none")
                self.assertTrue(pd.isna(report["Lower bound"]))
                self.assertTrue(pd.isna(report["Upper bound"]))
            calls = {call.args[2]: call.args[0] for call in histogram.call_args_list}
            self.assertEqual(calls["Floor height (m)"], [3] * 10 + [5])
            self.assertEqual(calls["Number of floors"], [4] * 10 + [30])
            self.assertEqual(calls["Building height (m)"], [12] * 10 + [150])
            self.assertEqual(counts.loc[("All", "footprint area (m2)"), "Excluded count"], 1)

    def test_scatter_iqr_filters_only_osm_footprints_without_changing_consultants(self):
        points = pd.DataFrame({
            "footprint_area_m2": [700, 3000, 700, 50000, 1000, 5000],
            "floors": [4, 4, 15, 40, 5, 20],
            "source": ["OSM"] * 4 + ["Consultants"] * 2,
        })
        original = _trim_percentiles(points)
        filtered = _filter_comparison_iqr(points, {
            "footprint area (m2)": (500, 2000),
            "Number of floors": (3, 6),
        })
        osm = filtered.loc[filtered["source"].eq("OSM")]
        self.assertEqual(osm["footprint_area_m2"].tolist(), [700, 700])
        self.assertEqual(osm["floors"].tolist(), [4, 15])
        pd.testing.assert_frame_equal(
            filtered.loc[filtered["source"].eq("Consultants")].reset_index(drop=True),
            original.loc[original["source"].eq("Consultants")].reset_index(drop=True),
        )
        self.assertEqual(
            filtered.loc[filtered["source"].eq("Consultants"), "footprint_area_m2"].tolist(),
            [1000, 5000],
        )

    def test_part_3_excludes_footprints_smaller_than_87_6(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "toronto_murbs.csv"
            pd.DataFrame({
                "murb_confidence": [0.77] * 4,
                "height_m": [12] * 4,
                "height_est_m": [12] * 4,
                "levels": [4] * 4,
                "levels_est": [4] * 4,
                "footprint_area_m2": [45.15375, 87.59, 87.6, 650],
            }).to_csv(csv_path, index=False)

            areas, heights, counts = _summarize(csv_path)
            self.assertEqual(areas, [87.6, 650])
            self.assertEqual(counts["Part 3 MURBs"], 2)
            self.assertEqual(counts["Part 3 MURBs with Height"], 2)
            self.assertEqual(len(heights["Building height (m)"]), 2)

    def test_geometry_metrics_write_boxplots_and_percentile_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            output_dir = Path(directory) / "output"
            input_dir.mkdir()
            count = 10
            pd.DataFrame({
                "murb_confidence": [0.9] * count,
                "height_m": [12] * count,
                "height_est_m": [12] * count,
                "levels": [4] * count,
                "levels_est": [4] * count,
                "footprint_area_m2": [700] * count,
                "length_m": list(range(20, 30)),
                "width_m": list(range(10, 20)),
                "average_depth_m": list(range(3, 13)),
                "aspect_ratio": list(range(2, 12)),
                "rectangularity": [0.5 + index * 0.05 for index in range(count)],
            }).to_csv(input_dir / "calgary_murbs.csv", index=False)

            self.addCleanup(plt.close, "all")
            with patch.object(sys, "argv", ["analysis", "--input-dir", str(input_dir),
                                            "--output-dir", str(output_dir)]), \
                  patch("scripts.plot_footprint_area_by_city.plt.close"), \
                  patch("scripts.plot_footprint_area_by_city._write_histogram"):
                self.assertEqual(main(), 0)
                axis = plt.gcf().axes[0]
                self.assertEqual(
                    list(axis.get_yticks()), [index / 10 for index in range(11)]
                )

            expected = {
                "length": ("length_summary.csv", "length.svg", "50th percentile length (m)", 24.5),
                "width": ("width_summary.csv", "width.svg", "50th percentile width (m)", 14.5),
                "average_depth": (
                    "average_depth_summary.csv", "average_depth.svg",
                    "50th percentile average depth (m)", 7.5,
                ),
                "aspect_ratio": (
                    "aspect_ratio_summary.csv", "aspect_ratio.svg",
                    "50th percentile aspect ratio", 6.5,
                ),
                "rectangularity": (
                    "rectangularity_summary.csv", "rectangularity.svg",
                    "50th percentile rectangularity", 0.725,
                ),
            }
            for summary_name, plot_name, median_column, median in expected.values():
                summary = pd.read_csv(output_dir / summary_name).set_index("Locations")
                self.assertAlmostEqual(summary.loc["Calgary, AB", median_column], median)
                self.assertAlmostEqual(summary.loc["All", median_column], median)
                plot = (output_dir / plot_name).read_text(encoding="utf-8")
                self.assertIn("Calgary, AB", plot)
                self.assertIn("All", plot)

    def test_height_histogram_ticks_align_with_bins(self):
        with tempfile.TemporaryDirectory() as directory:
            self.addCleanup(plt.close, "all")
            with patch("scripts.plot_footprint_area_by_city.plt.close"):
                building_heights = [3, 6, 9, 10, 202]
                _write_histogram(
                    building_heights,
                    "Building Height Distribution",
                    "Building height (m)",
                    Path(directory) / "build_height.svg",
                    bin_width=12,
                    bin_start=0,
                    x_ticks=tuple(index * 12 for index in range(18)),
                    x_limits=(0, 204),
                )
                building_height_axis = plt.gcf().axes[0]
                self.assertTrue(all(
                    float(tick).is_integer()
                    for tick in building_height_axis.get_yticks()
                ))
                self.assertTrue(all(
                    label.get_text().isdigit()
                    for label in building_height_axis.get_yticklabels()
                ))
                self.assertEqual(
                    [round(patch.get_width(), 6) for patch in building_height_axis.patches],
                    [12.0] * 17,
                )
                self.assertEqual(
                    list(building_height_axis.get_xticks()),
                    [index * 12 for index in range(18)],
                )
                self.assertEqual(
                    [label.get_text() for label in building_height_axis.get_xticklabels()],
                    [str(index * 12) for index in range(18)],
                )
                self.assertEqual(building_height_axis.get_xlim(), (0, 204))
                self.assertEqual(building_height_axis.get_box_aspect(), 1)
                self.assertTrue(all(
                    label.get_rotation() == 45
                    for label in building_height_axis.get_xticklabels()
                ))

                floor_height_ticks = tuple(2 + index * 0.25 for index in range(17))
                _write_histogram(
                    [2, 3.25, 4.5, 6],
                    "Floor Height Distribution",
                    "Floor height (m)",
                    Path(directory) / "floor_height.svg",
                    bin_width=0.25,
                    bin_start=2,
                    x_ticks=floor_height_ticks,
                    x_limits=(2, 6),
                )
                floor_height_axis = plt.gcf().axes[0]
                self.assertEqual(
                    [round(patch.get_width(), 6) for patch in floor_height_axis.patches],
                    [0.25] * 16,
                )
                self.assertEqual(list(floor_height_axis.get_xticks()), list(floor_height_ticks))
                self.assertEqual(
                    [label.get_text() for label in floor_height_axis.get_xticklabels()],
                    [f"{tick:g}" for tick in floor_height_ticks],
                )
                self.assertEqual(floor_height_axis.get_xlim(), (2, 6))
                self.assertEqual(floor_height_axis.get_box_aspect(), 1)
                self.assertTrue(all(
                    label.get_rotation() == 45
                    for label in floor_height_axis.get_xticklabels()
                ))

                floor_counts = [1, 2, 5, 8, 9, 12, 14, 15]
                _write_histogram(
                    floor_counts,
                    "Number of Floors Distribution",
                    "Number of floors",
                    Path(directory) / "floor_num.svg",
                    bin_width=4,
                    bin_start=0.5,
                    bin_labels=True,
                    bin_label_offset=0.5,
                )
                floor_num_axis = plt.gcf().axes[0]
                self.assertEqual(
                    [round(patch.get_width(), 6) for patch in floor_num_axis.patches],
                    [4.0] * 4,
                )
                self.assertEqual(
                    list(floor_num_axis.get_xticks()), [2.5, 6.5, 10.5, 14.5]
                )
                self.assertEqual(
                    [label.get_text() for label in floor_num_axis.get_xticklabels()],
                    ["1-4", "5-8", "9-12", "13-16"],
                )
                self.assertEqual(floor_num_axis.get_box_aspect(), 1)

    def test_rdh_outputs_group_by_climate_zone_and_parse_metric_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "rdh.csv"
            output_dir = Path(directory) / "output"
            data = {
                "Climate Zone": ["6", "7A", "7B", "", "4"],
                "Building Storeys": ["6", "10", "14", "18", "22"],
                "Building Height (m)": ["20", "30", "45", "50", "60"],
                "Typical/Tower Floor Plate Area (m2)": [
                    "1,000", "1,200", "1,400", "1,600", "1,800",
                ],
                "VFAR (Vertical Surface Area to Floor Area Ratio)": [
                    "0.3", "0.5", "0.7", "0.9", "0.4",
                ],
                "Overall WWR": ["30%", "40%", "50%", "60%", "20%"],
                "North WWR": ["25%", "35%", "45%", "55%", "15%"],
                "East WWR": ["20%", "30%", "40%", "50%", "10%"],
                "South WWR": ["35%", "45%", "55%", "65%", "25%"],
                "West WWR": ["30%", "40%", "50%", "60%", "20%"],
            }
            pd.DataFrame(data).to_csv(input_path, index=False)
            output_dir.mkdir()
            for orientation in ("overall", "north", "east", "south", "west"):
                (output_dir / f"{orientation}_wwr_rdh.svg").write_text(
                    "old WWR chart", encoding="utf-8"
                )
                (output_dir / f"{orientation}_wwr_rdh_summary.csv").write_text(
                    "old WWR summary", encoding="utf-8"
                )

            with patch.object(sys, "argv", [
                "analyze_rdh", "--input-csv", str(input_path),
                "--output-dir", str(output_dir),
            ]), patch(
                "scripts.analyze_rdh._write_histogram", wraps=_write_histogram
            ) as write_histogram:
                self.assertEqual(analyze_rdh(), 0)

            for _, metric_stem, _ in RDH_METRICS:
                plot_stem = (
                    f"wwr_{metric_stem.removesuffix('_wwr')}"
                    if metric_stem.endswith("_wwr")
                    else metric_stem
                )
                summary_path = output_dir / f"{plot_stem}_rdh_summary.csv"
                plot_path = output_dir / f"{plot_stem}_rdh.svg"
                self.assertTrue(summary_path.exists())
                self.assertTrue(plot_path.exists())
                summary = pd.read_csv(summary_path)
                self.assertEqual(summary["Climate Zone"].tolist(), ["4", "6", "7", "All"])
            for orientation in ("overall", "north", "east", "south", "west"):
                self.assertFalse((output_dir / f"{orientation}_wwr_rdh.svg").exists())
                self.assertFalse(
                    (output_dir / f"{orientation}_wwr_rdh_summary.csv").exists()
                )

            floor_summary = pd.read_csv(output_dir / "floor_num_rdh_summary.csv")
            zone_7 = floor_summary.set_index("Climate Zone").loc["7"]
            self.assertEqual(zone_7["50th percentile Number of floors"], 12)
            self.assertEqual(
                floor_summary.iloc[-1]["Maximum Number of floors"], 22
            )
            area_summary = pd.read_csv(output_dir / "footprint_area_rdh_summary.csv")
            self.assertEqual(area_summary.iloc[-1]["Minimum Footprint area (m2)"], 1000)
            area_call = write_histogram.call_args_list[2]
            self.assertEqual(area_call.args[1], "Footprint Area Distribution")
            self.assertEqual(area_call.args[2], "Footprint area (m$^2$)")
            self.assertEqual(area_call.kwargs["bin_width"], 500)
            self.assertEqual(area_call.kwargs["x_limits"], (0, 6000))
            self.assertTrue(area_call.kwargs["bin_labels"])
            self.assertEqual(area_call.kwargs["bin_label_offset"], 0)
            self.assertEqual(
                [call.args[1] for call in write_histogram.call_args_list],
                [
                    "Number of Floors Distribution",
                    "Building Height Distribution",
                    "Footprint Area Distribution",
                    "VFAR Distribution",
                    "Overall WWR Distribution",
                    "North WWR Distribution",
                    "East WWR Distribution",
                    "South WWR Distribution",
                    "West WWR Distribution",
                ],
            )
            area_plot = (output_dir / "footprint_area_rdh.svg").read_text(encoding="utf-8")
            self.assertNotIn("RDH", area_plot)
            self.assertIn("6000", area_plot)
            self.assertIn("0-500", area_plot)
            self.assertIn("500-1000", area_plot)
            for orientation in ("overall", "north", "east", "south", "west"):
                wwr_plot = (output_dir / f"wwr_{orientation}_rdh.svg").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("RDH", wwr_plot)
                wwr_call = write_histogram.call_args_list[
                    ("overall", "north", "east", "south", "west").index(orientation) + 4
                ]
                self.assertEqual(wwr_call.kwargs["bin_width"], 5)
                self.assertEqual(wwr_call.kwargs["bin_start"], 0)
                self.assertEqual(wwr_call.kwargs["x_limits"], (0, 70))
                self.assertEqual(wwr_call.kwargs["x_ticks"], tuple(range(0, 71, 5)))
            vfar_plot = (output_dir / "VFAR_rdh.svg").read_text(encoding="utf-8")
            self.assertIn("VFAR", vfar_plot)
            self.assertNotIn("RDH", vfar_plot)

    def test_osm_and_rdh_floor_area_scatterplot_pairs_correct_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            osm_dir = root / "osm"
            osm_dir.mkdir()
            output_path = root / "floor_area_vs_floors.svg"
            pd.DataFrame({
                "murb_confidence": [0.9, 0.9, 0.2],
                "height_m": [12, 15, 12],
                "height_est_m": [12, 15, 12],
                "levels": [4, "", 4],
                "levels_est": [4, 5, 4],
                "footprint_area_m2": [700, 900, 800],
            }).to_csv(osm_dir / "calgary_murbs.csv", index=False)
            pd.DataFrame({
                "murb_confidence": [0.9],
                "height_m": [12],
                "height_est_m": [12],
                "levels": [4],
                "levels_est": [4],
                "footprint_area_m2": [1000],
            }).to_csv(osm_dir / "ottawa_murbs.csv", index=False)
            rdh_path = root / "rdh.csv"
            pd.DataFrame({
                "Climate Zone": ["6", ""],
                "Building Storeys": [8, 10],
                "Building Height (m)": [24, 30],
                "Typical/Tower Floor Plate Area (m2)": [1200, 1400],
                "VFAR (Vertical Surface Area to Floor Area Ratio)": [0.5, 0.7],
                "Overall WWR": ["40%", "50%"],
                "North WWR": ["35%", "45%"],
                "East WWR": ["30%", "40%"],
                "South WWR": ["45%", "55%"],
                "West WWR": ["40%", "50%"],
            }).to_csv(rdh_path, index=False)

            points = _load_comparison_data(osm_dir, rdh_path)
            self.assertEqual(len(points), 2)
            osm_points = points.loc[points["source"].eq("OSM")]
            self.assertEqual(osm_points["footprint_area_m2"].tolist(), [700])
            self.assertEqual(osm_points["floors"].tolist(), [4])
            consultants_point = points.loc[points["source"].eq("Consultants")].iloc[0]
            self.assertEqual(consultants_point["footprint_area_m2"], 1200)
            self.assertEqual(consultants_point["floors"], 8)

            tail_data = pd.DataFrame({
                "footprint_area_m2": range(1, 1001),
                "floors": range(1, 1001),
                "source": "OSM",
            })
            trimmed = _trim_percentiles(tail_data)
            self.assertEqual(len(trimmed), 994)
            self.assertEqual(trimmed["floors"].min(), 4)
            self.assertEqual(trimmed["floors"].max(), 997)

            self.addCleanup(plt.close, "all")
            with patch("scripts.plot_floor_area_relationship.plt.close"):
                _write_scatterplot(points, output_path)
                axis = plt.gcf().axes[0]
                self.assertEqual(axis.get_box_aspect(), 1)
                self.assertEqual(axis.get_xlabel(), "Number of floors")
                self.assertEqual(axis.get_ylabel(), "Footprint area (m$^2$)")
                self.assertEqual(
                    axis.collections[0].get_offsets().tolist(), [[4, 700]]
                )
                self.assertEqual(
                    axis.collections[1].get_offsets().tolist(), [[8, 1200]]
                )
                self.assertEqual(
                    tuple(axis.collections[0].get_facecolors()[0][:3]),
                    (0, 0, 0),
                )
                self.assertEqual(
                    [text.get_text() for text in axis.get_legend().get_texts()],
                    ["OSM (n=1)", "Consultants (n=1)"],
                )
            plot = output_path.read_text(encoding="utf-8")
            self.assertIn("Number of Floors vs. Footprint Area", plot)

    def test_shape_comparison_maps_osm_and_consultant_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            osm_dir = root / "osm"
            osm_dir.mkdir()
            pd.DataFrame({
                "shape_class": [
                    "Rectangle", "Slab", "Square", "Tower", "L", "U",
                    "Courtyard", "Irregular",
                ],
                "murb_confidence": [0.9] * 8,
                "footprint_area_m2": [700] * 8,
                "levels": [4] * 8,
                "levels_est": [4] * 8,
                "height_m": [12] * 8,
                "height_est_m": [12] * 8,
            }).to_csv(osm_dir / "calgary_murbs.csv", index=False)
            rdh_path = root / "rdh.csv"
            pd.DataFrame({
                "Climate Zone": ["6", "6", "6", "6", "6", ""],
                "Building Shape": [
                    "Rectangular", "Square", "L-Shape", "U-Shape", "C-Shape", "Other",
                ],
            }).to_csv(rdh_path, index=False)

            counts = _load_shape_counts(osm_dir, rdh_path)
            self.assertEqual(counts.loc["Rectangular", "OSM"], 2)
            self.assertEqual(counts.loc["Square", "OSM"], 2)
            self.assertEqual(counts.loc["L-shaped", "OSM"], 1)
            self.assertEqual(counts.loc["U/C-shaped", "OSM"], 1)
            self.assertEqual(counts.loc["Courtyard", "OSM"], 1)
            self.assertEqual(counts.loc["Other / Irregular", "OSM"], 1)
            self.assertEqual(counts["Consultants"].sum(), 5)
            self.assertEqual(counts.loc["U/C-shaped", "Consultants"], 2)
            self.assertEqual(counts.loc["Courtyard", "Consultants"], 0)

    def test_shape_comparison_uses_part_3_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            osm_dir = root / "osm"
            osm_dir.mkdir()
            pd.DataFrame({
                "shape_class": ["Rectangle", "Square", "Tower", "L", "U"],
                "murb_confidence": [0.55, 0.77, 0.77, 0.77, 0.77],
                "footprint_area_m2": [700, 600, 87.59, 600, 601],
                "levels": [3, 3, 4, None, None],
                "levels_est": [3, 3, 4, None, None],
                "height_m": [9, 9, 12, 12, None],
                "height_est_m": [9, 9, 12, 12, None],
            }).to_csv(osm_dir / "calgary_murbs.csv", index=False)
            rdh_path = root / "rdh.csv"
            pd.DataFrame({"Climate Zone": ["6"], "Building Shape": ["Square"]}).to_csv(
                rdh_path, index=False,
            )
            counts = _load_shape_counts(osm_dir, rdh_path)
            self.assertEqual(counts["OSM"].sum(), 2)
            self.assertEqual(counts.loc["L-shaped", "OSM"], 1)
            self.assertEqual(counts.loc["U/C-shaped", "OSM"], 1)
            self.assertEqual(counts["Consultants"].sum(), 1)

    def test_location_order_missing_cities_and_pooled_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "input"
            output_dir = Path(directory) / "output"
            input_dir.mkdir()
            columns = ["murb_confidence", "height_m", "height_est_m", "levels",
                       "levels_est", "footprint_area_m2"]
            pd.DataFrame([
                [0.9, 12, 12, 4, 4, 650],
                [0.9, "", "", "", "", 1250],
                [0.2, 18, 18, 6, 6, 900],
            ], columns=columns).to_csv(input_dir / "calgary_murbs.csv", index=False)
            pd.DataFrame([
                [0.9, 15, 15, 5, 5, 1800],
            ], columns=columns).to_csv(input_dir / "vancouver_murb.csv", index=False)
            pd.DataFrame([
                [0.9, 30, 30, 10, 10, 10000],
            ], columns=columns).to_csv(input_dir / "ottawa_murbs.csv", index=False)

            with patch.object(sys, "argv", ["analysis", "--input-dir", str(input_dir),
                                            "--output-dir", str(output_dir)]):
                self.assertEqual(main(), 0)

            samples = pd.read_csv(output_dir / "sample_size.csv").set_index("Locations")
            footprints = pd.read_csv(output_dir / "footprint_area_summary.csv").set_index("Locations")
            height_summaries = {
                "Floor height (m)": pd.read_csv(
                    output_dir / "floor_height.csv"
                ).set_index("Locations"),
                "Number of floors": pd.read_csv(
                    output_dir / "floor_num.csv"
                ).set_index("Locations"),
                "Building height (m)": pd.read_csv(
                    output_dir / "build_height.csv"
                ).set_index("Locations"),
            }
            expected_order = [*LOCATIONS.values(), "All"]
            for table in (samples, footprints, *height_summaries.values()):
                self.assertEqual(table.index.tolist(), expected_order)
                self.assertTrue((table.loc[["Montreal, QC", "Saskatoon, SK", "Whitehorse, YT"]] == 0).all().all())

            self.assertEqual(samples.loc["All"].tolist(), [4, 3, 3, 2])
            self.assertEqual(samples.loc["Calgary, AB", "Part 3 MURBs with Height"], 1)
            self.assertEqual(footprints.loc["All", "50th percentile footprint area (m2)"], 1250)
            self.assertEqual(footprints.loc["All", "Maximum footprint area (m2)"], 1800)
            self.assertEqual(
                height_summaries["Floor height (m)"].loc[
                    "All", "50th percentile Floor height (m)"
                ],
                3,
            )
            self.assertEqual(
                height_summaries["Number of floors"].loc[
                    "All", "50th percentile Number of floors"
                ],
                4.5,
            )
            self.assertEqual(
                height_summaries["Building height (m)"].loc[
                    "All", "50th percentile Building height (m)"
                ],
                13.5,
            )
            self.assertFalse((output_dir / "height.csv").exists())
            for filename, title in (
                ("floor_height.svg", "Floor Height Distribution"),
                ("floor_num.svg", "Number of Floors Distribution"),
                ("build_height.svg", "Building Height Distribution"),
            ):
                histogram = (output_dir / filename).read_text(encoding="utf-8")
                self.assertIn(title, histogram)
                self.assertIn("Number of buildings", histogram)
                self.assertNotIn("Calgary, AB", histogram)
            plot = (output_dir / "footprint_area.svg").read_text(encoding="utf-8")
            self.assertNotIn("Vancouver, BC", plot)
            self.assertNotIn("Calgary, AB", plot)
            self.assertIn("All", plot)
            self.assertNotIn("Ottawa", plot)


if __name__ == "__main__":
    unittest.main()