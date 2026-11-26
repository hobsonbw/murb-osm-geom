import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plot_polygon.py"


class PlotPolygonTests(unittest.TestCase):
    def test_requires_wkt_file(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wkt_file", result.stderr)

    def test_previews_explicit_polygon_with_default_and_custom_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            polygon = root / "polygon.wkt"
            polygon.write_text("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", encoding="utf-8")
            for arguments, output in (
                ([str(polygon)], root / "data" / "outputs" / "polygon_preview.png"),
                ([str(polygon), "custom.png"], root / "custom.png"),
            ):
                with self.subTest(output=output):
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), *arguments],
                        cwd=root, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(output.is_file())
                    self.assertIn("Area:              16.00 m^2", result.stdout)


if __name__ == "__main__":
    unittest.main()
