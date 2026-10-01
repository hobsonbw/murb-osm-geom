import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from scripts.plot_footprint_area_by_city import (
    LOCATIONS,
    _summarize,
    _write_histogram,
    main,
)


class CityAnalysisTests(unittest.TestCase):
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

    def test_plot_styles_and_hides_only_extreme_fliers(self):
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
                self.assertEqual([list(line.get_ydata()) for line in fliers], [[900], [900]])
                self.assertEqual([line.get_color() for line in fliers], ["black", "red"])
                self.assertEqual(axis.get_ylim(), (0, 2000))
                self.assertEqual([tick for tick in axis.get_yticks() if 0 <= tick <= 2000],
                                 [0, 1000, 2000])
                self.assertIsInstance(axis.yaxis.get_minor_locator(), MultipleLocator)
                self.assertEqual(axis.yaxis.get_minor_locator().tick_values(0, 2000)[1:4].tolist(),
                                 [0, 250, 500])
                self.assertEqual(pd.read_csv(Path(directory) / "output" / "footprint_area_summary.csv")
                                 .iloc[-1]["Maximum footprint area (m2)"], 10000)
            finally:
                plt.close(figure)

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