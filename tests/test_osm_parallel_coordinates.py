import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.plot_osm_parallel_coordinates import (
    ALL_METRIC_RANGES, GEOMETRY_METRICS, METRICS, _normalized_plot, _plot, main,
)


class ParallelCoordinatesTests(unittest.TestCase):
    def test_plots_use_complete_rows_for_the_displayed_metrics(self):
        data = pd.DataFrame({metric: [1.0, 2.0, 3.0] for metric in METRICS})
        data.loc[1, METRICS[6]] = None
        data.loc[2, METRICS[1]] = None

        geometry = _plot(data, GEOMETRY_METRICS, "Geometry")
        all_metrics = _plot(data, METRICS, "All")

        self.assertIn("n=2", geometry.layout.title.text)
        self.assertIn("n=1", all_metrics.layout.title.text)
        self.assertEqual(len(geometry.data[0].dimensions), 6)
        self.assertEqual(len(all_metrics.data[0].dimensions), 9)
        self.assertEqual(list(geometry.data[0].dimensions[0].values), [1.0, 2.0])
        self.assertEqual(list(all_metrics.data[0].dimensions[0].values), [1.0])

    def test_fixed_ranges_are_applied_only_when_requested(self):
        data = pd.DataFrame({metric: [1.0] for metric in METRICS})
        geometry = _plot(data, GEOMETRY_METRICS, "Geometry")
        all_metrics = _plot(data, METRICS, "All", ranges=ALL_METRIC_RANGES)

        self.assertTrue(all(dimension.range is None for dimension in geometry.data[0].dimensions))
        expected = (
            (0, 3000), (0, 120), (0, 120), (0, 120), (1, 5),
            (0.25, 1), (0, 6), (0, 70), (0, 220),
        )
        self.assertEqual(tuple(dimension.range for dimension in all_metrics.data[0].dimensions),
                         expected)
        self.assertEqual(all_metrics.data[0].dimensions[0].values[0], 1.0)

    def test_rejects_out_of_range_values_instead_of_hiding_them(self):
        data = pd.DataFrame({metric: [1.0] for metric in METRICS})
        data[METRICS[-1]] = 221.0
        with self.assertRaisesRegex(ValueError, "Building height.*outside"):
            _plot(data, METRICS, "All", ranges=ALL_METRIC_RANGES)

    def test_normalization_uses_observed_complete_case_ranges(self):
        data = pd.DataFrame({metric: [10.0, 15.0, 30.0, 1000.0] for metric in METRICS})
        data.loc[3, METRICS[-1]] = None
        data[METRICS[1]] = [20.0, 30.0, 40.0, 900.0]
        figure = _normalized_plot(data)

        self.assertIn("n=3", figure.layout.title.text)
        self.assertEqual(list(figure.data[0].dimensions[0].values), [0, 0.25, 1])
        self.assertEqual(list(figure.data[0].dimensions[1].values), [0, 0.5, 1])
        self.assertTrue(all(dimension.range == (0, 1) for dimension in figure.data[0].dimensions))
        self.assertIn("Footprint (m²): 10–30", figure.layout.annotations[1].text)

    def test_normalization_rejects_constant_metrics(self):
        data = pd.DataFrame({metric: [1.0, 2.0] for metric in METRICS})
        data[METRICS[2]] = 5.0
        with self.assertRaisesRegex(ValueError, "constant metrics: width"):
            _normalized_plot(data)

    def test_empty_complete_case_fails_before_writing_either_plot(self):
        data = pd.DataFrame({metric: [1.0] for metric in METRICS})
        data[METRICS[-1]] = None
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "argv", ["parallel", "--output-dir", directory]), \
                    patch("scripts.plot_osm_parallel_coordinates._load_filtered_metrics",
                          return_value=data):
                self.assertEqual(main(), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
