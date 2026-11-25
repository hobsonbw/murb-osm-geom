import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, box

from scripts.refresh_city_analysis import _calculate_metrics, _extract_city_buildings
from src.calculate_geometry import _calculate_average_depth
from src.download_osm import _load_from_pbf
from src.estimate_heights import estimate_heights
from src.identify_murbs import identify_murbs
from src.preprocess import preprocess
from src.utils import load_settings


class OsmIngestionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = load_settings()
        self.settings["paths"]["processed_dir"] = self.directory.name

    def test_gdal_ways_survive_and_relation_ids_do_not_collide(self):
        raw = gpd.GeoDataFrame(
            {"osm_id": [None, None, "100", None],
             "osm_way_id": ["100", "101", None, "100"]},
            geometry=[box(0, 0, 1, 1), box(2, 0, 3, 1),
                      box(4, 0, 5, 1), box(0, 0, 1, 1)],
            crs="EPSG:4326",
        )
        clean = preprocess(raw, self.settings)
        self.assertEqual(
            list(zip(clean.element_type, clean.osmid)),
            [("way", "100"), ("way", "101"), ("relation", "100")],
        )

    def test_overpass_tile_duplicates_use_element_namespace(self):
        raw = gpd.GeoDataFrame(
            {"element_type": ["way", "way", "relation"], "id": [100, 100, 100]},
            geometry=[box(0, 0, 1, 1)] * 3, crs="EPSG:4326",
        )
        clean = preprocess(raw, self.settings)
        self.assertEqual(list(zip(clean.element_type, clean.osmid)),
                         [("way", 100), ("relation", 100)])

    def test_missing_ids_fail_instead_of_collapsing_buildings(self):
        for columns in (
            {"osmid": [None, None]},
            {"osm_id": [None, None], "osm_way_id": [None, "100"]},
            {"osm_id": ["100", None], "osm_way_id": ["101", "102"]},
        ):
            with self.subTest(columns=columns):
                raw = gpd.GeoDataFrame(columns, geometry=[box(0, 0, 1, 1)] * 2,
                                       crs="EPSG:4326")
                with self.assertRaises(ValueError):
                    preprocess(raw, self.settings)

    def test_single_part_multipolygon_depth_is_not_discarded(self):
        polygon = box(0, 0, 20, 10)
        labels = np.ones((10, 10), dtype=int)
        distances = np.full((10, 10), 8.0)
        with patch("src.calculate_geometry._get_branches",
                   return_value=(labels, 1, distances)):
            expected = _calculate_average_depth(polygon)
            actual = _calculate_average_depth(MultiPolygon([polygon]))
        self.assertEqual(expected, 8.0)
        self.assertEqual(actual, expected)

    def test_parallel_metrics_preserve_building_order_and_crs(self):
        raw = gpd.GeoDataFrame(
            {"osmid": ["first", "second"], "levels_est": [4, 3]},
            geometry=[MultiPolygon([box(0, 0, 20, 10)]),
                      MultiPolygon([box(30, 0, 40, 10)])],
            crs="EPSG:3978",
        )
        calculated = _calculate_metrics(raw, workers=2, batch_size=1)
        self.assertEqual(calculated.osmid.tolist(), ["first", "second"])
        self.assertEqual(calculated.crs, raw.crs)
        self.assertEqual(calculated.footprint_area_m2.tolist(), [200, 100])
        self.assertTrue(calculated.average_depth_m.notna().all())

    def test_invalid_osm_polygon_is_repaired_before_clipping(self):
        osm_path = Path(self.directory.name) / "invalid.osm"
        osm_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="51.00" lon="-114.00"/>
  <node id="2" lat="51.02" lon="-113.98"/>
  <node id="3" lat="51.02" lon="-114.00"/>
  <node id="4" lat="51.00" lon="-113.98"/>
  <way id="100">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
    <tag k="building" v="apartments"/>
  </way>
</osm>""", encoding="utf-8")
        boundary = box(-114.005, 51.005, -113.985, 51.015)
        raw = _load_from_pbf(osm_path, boundary)
        self.assertEqual(len(raw), 1)
        self.assertTrue(raw.is_valid.all())
        output_dir = Path(self.directory.name) / "invalid_extracted"
        output_dir.mkdir()
        counts = _extract_city_buildings(osm_path, {"city": boundary}, output_dir)
        self.assertEqual(counts, {"city": 1})
        extracted = gpd.read_file(output_dir / "city_buildings.gpkg")
        self.assertTrue(extracted.is_valid.all())

    def test_gdal_area_loading_restores_tags_and_clips(self):
        # XML and PBF share GDAL's OSM driver, schema, and SQL tag extraction.
        osm_path = Path(self.directory.name) / "buildings.osm"
        osm_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lat="51.00" lon="-114.00"/>
  <node id="2" lat="51.00" lon="-113.99"/>
  <node id="3" lat="51.01" lon="-113.99"/>
  <node id="4" lat="51.01" lon="-114.00"/>
  <node id="5" lat="51.02" lon="-114.00"/>
  <node id="6" lat="51.02" lon="-113.99"/>
  <node id="7" lat="51.03" lon="-113.99"/>
  <node id="8" lat="51.03" lon="-114.00"/>
  <node id="9" lat="51.04" lon="-114.00"/>
  <node id="10" lat="51.04" lon="-113.99"/>
  <node id="11" lat="51.05" lon="-113.99"/>
  <node id="12" lat="51.05" lon="-114.00"/>
  <node id="13" lat="52.00" lon="-114.00"/>
  <node id="14" lat="52.00" lon="-113.99"/>
  <node id="15" lat="52.01" lon="-113.99"/>
  <node id="16" lat="52.01" lon="-114.00"/>
  <way id="100">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
    <tag k="building" v="apartments"/>
    <tag k="height" v="12 m"/><tag k="roof:height" v="2"/>
    <tag k="building:levels" v="4"/>
    <tag k="addr:housenumber" v="12 &quot;A&quot;"/>
  </way>
  <way id="101">
    <nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/>
  </way>
  <way id="102">
    <nd ref="9"/><nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="9"/>
    <tag k="building" v="yes"/><tag k="building:flats" v="4"/>
  </way>
  <way id="103">
    <nd ref="13"/><nd ref="14"/><nd ref="15"/><nd ref="16"/><nd ref="13"/>
    <tag k="building" v="apartments"/>
  </way>
  <relation id="100">
    <member type="way" ref="101" role="outer"/>
    <tag k="type" v="multipolygon"/><tag k="building" v="residential"/>
    <tag k="building:levels" v="3"/>
  </relation>
</osm>""", encoding="utf-8")
        raw = _load_from_pbf(osm_path, box(-114.01, 50.99, -113.98, 51.045))
        clean = preprocess(raw, self.settings)
        self.assertEqual(len(clean), 3)
        self.assertEqual(set(zip(clean.element_type, clean.osmid)),
                         {("way", "100"), ("way", "102"), ("relation", "100")})
        way = clean[(clean.element_type == "way") & (clean.osmid == "100")].iloc[0]
        self.assertEqual(way["addr:housenumber"], '12 "A"')
        murbs = estimate_heights(identify_murbs(clean, self.settings), self.settings)
        self.assertEqual(len(murbs), 3)
        way = murbs[(murbs.element_type == "way") & (murbs.osmid == "100")].iloc[0]
        self.assertEqual(way["height_m"], 12)
        self.assertEqual(way["height_est_m"], 14)
        self.assertEqual(way["levels"], 4)
        generic = murbs[murbs.osmid == "102"].iloc[0]
        self.assertEqual(generic["murb_confidence"], 0.55)
        extract_dir = Path(self.directory.name) / "extracted"
        extract_dir.mkdir()
        counts = _extract_city_buildings(
            osm_path,
            {"inside": box(-114.01, 50.99, -113.98, 51.045),
             "outside": box(-114.01, 51.99, -113.98, 52.02)},
            extract_dir,
            batch_size=2,
        )
        self.assertEqual(counts, {"inside": 3, "outside": 1})
        extracted = gpd.read_file(extract_dir / "inside_buildings.gpkg")
        extracted_clean = preprocess(extracted, self.settings)
        self.assertEqual(set(zip(extracted_clean.element_type, extracted_clean.osmid)),
                         set(zip(clean.element_type, clean.osmid)))
        self.assertEqual(extracted_clean["height"].dropna().tolist(), ["12 m"])


if __name__ == "__main__":
    unittest.main()
