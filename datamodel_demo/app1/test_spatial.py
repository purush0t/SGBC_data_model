from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from django.test import TestCase
from PIL import Image
from xarray import DataArray

from .models import Entity, EntityInformationRecord, EntityType, InformationRecordType
from .spatial import SpatialDataZarrReader, _spatial_dimensions, get_reader


class SpatialApiTests(TestCase):
    def setUp(self):
        self.entity_type = EntityType.objects.create(code="expression_matrix", name="Expression matrix")
        self.record_type = InformationRecordType.objects.create(code="general", name="General")

    def test_metadata_declares_synthetic_dataset_and_layers(self):
        response = self.client.get("/api/spatial/synthetic-demo/metadata/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["synthetic"])
        self.assertIn("expression", {layer["id"] for layer in response.json()["layers"]})

    def test_expression_is_gene_targeted_and_viewport_bounded(self):
        response = self.client.get(
            "/api/spatial/synthetic-demo/expression/",
            {"gene": "Gene_0", "xmin": 0, "xmax": 25, "ymin": 0, "ymax": 25},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 9)
        self.assertTrue(all(point["x"] <= 25 for point in response.json()["points"]))

    def test_spatial_api_supports_offset_pages(self):
        response = self.client.get(
            "/api/spatial/synthetic-demo/coordinates/",
            {"limit": 10, "offset": 10},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 10)
        self.assertEqual(response.json()["offset"], 10)
        self.assertTrue(response.json()["has_more"])

    def test_viewport_sampling_reports_total_and_preserves_spatial_order(self):
        reader = SpatialDataZarrReader(
            "sample-test", Path("unused.zarr"), "Sample test", "", "", ""
        )
        reader.__dict__["_image_rasters"] = ()
        reader.__dict__["_table"] = SimpleNamespace(
            obsm={"spatial": np.column_stack((np.arange(10), np.arange(10)))},
            obs=pd.DataFrame({"cell_ID": [f"cell-{index}" for index in range(10)]}),
        )
        with patch("app1.views.get_reader", return_value=reader):
            response = self.client.get(
                "/api/spatial/sample-test/coordinates/",
                {"limit": 3, "sample": "true"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 10)
        self.assertTrue(response.json()["sampled"])
        self.assertFalse(response.json()["has_more"])
        self.assertEqual(
            [point["id"] for point in response.json()["points"]],
            ["cell-0", "cell-4", "cell-9"],
        )

    def test_selected_cell_details_endpoint(self):
        response = self.client.get(
            "/api/spatial/synthetic-demo/cell/", {"id": "bin-00-00"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cell"]["id"], "bin-00-00")

    def test_invalid_gene_and_unbounded_limit_are_rejected(self):
        missing_gene = self.client.get(
            "/api/spatial/synthetic-demo/expression/", {"gene": "not-a-gene"}
        )
        too_many = self.client.get(
            "/api/spatial/synthetic-demo/coordinates/", {"limit": 50001}
        )

        self.assertEqual(missing_gene.status_code, 400)
        self.assertEqual(too_many.status_code, 400)

    def test_canvas_dimensions_follow_highest_resolution_image(self):
        image = type("Raster", (), {"sizes": {"x": 6432, "y": 6432}})()
        mask = type("Mask", (), {"shape": (6432, 6432)})()

        self.assertEqual(_spatial_dimensions(image, mask), (6432, 6432))

    def test_deep_zoom_tiles_choose_matching_stored_pyramid_level(self):
        reader = SpatialDataZarrReader(
            "pyramid-test", Path("unused.zarr"), "Pyramid test", "", "", ""
        )
        preview = DataArray(np.full((130, 150), 30, dtype=np.uint8), dims=("y", "x"))
        full = DataArray(np.full((520, 600), 210, dtype=np.uint8), dims=("y", "x"))
        reader.__dict__["_image_rasters"] = (preview, full)

        self.assertEqual(reader.get_image_dimensions(), (600, 520))
        with patch("app1.spatial.MAX_IMAGE_DIMENSION", 300):
            self.assertEqual(reader._display_image_raster.sizes["x"], 150)
        full_tile = Image.open(BytesIO(reader.get_image_tile(10, 0, 0))).convert("RGB")
        preview_tile = Image.open(BytesIO(reader.get_image_tile(8, 0, 0))).convert("RGB")
        self.assertEqual(full_tile.size, (256, 256))
        self.assertGreater(full_tile.getpixel((0, 0))[0], 180)
        self.assertEqual(preview_tile.size, (150, 130))
        self.assertLess(preview_tile.getpixel((0, 0))[0], 60)

    def test_low_zoom_grayscale_tile_encodes_with_single_channel(self):
        reader = SpatialDataZarrReader(
            "grayscale-test", Path("unused.zarr"), "Grayscale test", "", "", ""
        )
        image = DataArray(
            np.arange(32 * 32, dtype=np.uint16).reshape(1, 32, 32),
            dims=("c", "y", "x"),
        )
        reader.__dict__["_image_rasters"] = (image,)

        tile = Image.open(BytesIO(reader.get_image_tile(0, 0, 0)))

        self.assertEqual(tile.size, (1, 1))
        self.assertEqual(tile.mode, "RGB")

    def test_bounded_coordinates_do_not_access_expression_matrix(self):
        reader = SpatialDataZarrReader(
            "coordinate-test", Path("unused.zarr"), "Coordinate test", "", "", ""
        )
        reader.__dict__["_image_rasters"] = ()
        reader.__dict__["_table"] = SimpleNamespace(
            obsm={"spatial": np.array([[1, 1], [5, 2], [3, 3]])},
            obs=pd.DataFrame({"cell_ID": ["a", "b", "c"], "annotation": ["A", "B", "C"]}),
        )

        points = reader.get_coordinates(
            bounds={"xmin": 1, "xmax": 3, "ymin": 0, "ymax": 3}
        )

        self.assertEqual([point["id"] for point in points], ["a", "c"])

    def test_cell_details_compute_metrics_for_one_expression_row(self):
        reader = SpatialDataZarrReader(
            "detail-test", Path("unused.zarr"), "Detail test", "", "", ""
        )
        reader.__dict__["_image_rasters"] = ()
        reader.__dict__["_table"] = SimpleNamespace(
            obsm={"spatial": np.array([[1, 1], [5, 2]])},
            obs=pd.DataFrame({"cell_ID": ["a", "b"], "annotation": ["A", "B"]}),
            X=csr_matrix(
                (
                    np.array([0, 2, 0, 1, 0, 4]),
                    np.array([0, 1, 2, 0, 1, 2]),
                    np.array([0, 3, 6]),
                ),
                shape=(2, 3),
            ),
        )

        details = reader.get_cell_details("b")

        self.assertEqual(details["genes_detected"], 2)
        self.assertEqual(details["total_counts"], 5)
        self.assertEqual(details["id"], "b")

    def test_deep_zoom_image_descriptor_and_edge_tile(self):
        reader = SpatialDataZarrReader(
            "tile-test", Path("unused.zarr"), "Tile test", "", "", ""
        )
        reader.__dict__["_image_rasters"] = (DataArray(
            np.arange(300 * 260, dtype=np.uint16).reshape(260, 300),
            dims=("y", "x"),
        ),)
        with patch("app1.views.get_reader", return_value=reader):
            descriptor = self.client.get("/api/spatial/tile-test/image.dzi")
            edge_tile = self.client.get("/api/spatial/tile-test/image_files/9/1_1.jpg")
            overview_tile = self.client.get("/api/spatial/tile-test/image_files/0/0_0.jpg")
            invalid_tile = self.client.get("/api/spatial/tile-test/image_files/9/2_0.jpg")

        self.assertEqual(descriptor.status_code, 200)
        self.assertIn('Width="300" Height="260"', descriptor.content.decode())
        self.assertEqual(edge_tile.status_code, 200)
        with Image.open(BytesIO(edge_tile.content)) as image:
            self.assertEqual(image.size, (44, 4))
        with Image.open(BytesIO(overview_tile.content)) as image:
            self.assertEqual(image.size, (1, 1))
        self.assertEqual(invalid_tile.status_code, 404)

    def test_mouse_liver_demo_is_available_and_capable(self):
        response = self.client.get("/api/spatial/mouse_liver_demo/metadata/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "mouse_liver_demo")
        self.assertEqual(response.json()["width"], 6432)
        self.assertEqual(response.json()["display_width"], 1608)
        self.assertIn("expression", {layer["id"] for layer in response.json()["layers"]})
        self.assertIn("umap", {layer["id"] for layer in response.json()["layers"]})

    def test_unknown_dataset_is_not_exposed(self):
        response = self.client.get("/api/spatial/unknown/metadata/")

        self.assertEqual(response.status_code, 404)

    def test_zarr_stores_in_spatial_directory_are_listed_by_name(self):
        with TemporaryDirectory() as temporary_directory:
            test_store = Path(temporary_directory) / "test_out.zarr"
            test_store.mkdir()
            (test_store / "zarr.json").write_text("{}", encoding="utf-8")
            with patch("app1.spatial._spatial_data_directory", return_value=Path(temporary_directory)):
                response = self.client.get("/api/spatial/")
                first_reader = get_reader("test_out")
                second_reader = get_reader("test_out")

        self.assertEqual(response.status_code, 200)
        test_store = next(
            dataset for dataset in response.json()["datasets"] if dataset["id"] == "test_out"
        )
        self.assertTrue(test_store["reader_available"])
        self.assertIs(first_reader, second_reader)

    def test_provenance_metadata_registers_unavailable_dataset_explicitly(self):
        entity = Entity.objects.create(entity_type=self.entity_type, identifier="matrix-001")
        EntityInformationRecord.objects.create(
            entity=entity,
            information_record_type=self.record_type,
            version=1,
            recorded_at="2026-09-25T12:00:00Z",
            metadata={"spatial_dataset": {"name": "Registered matrix", "layers": []}},
        )

        response = self.client.get("/api/spatial/")
        registered = next(item for item in response.json()["datasets"] if item["id"] == f"entity-{entity.pk}")

        self.assertFalse(registered["reader_available"])
        self.assertEqual(
            self.client.get(f"/api/spatial/entity-{entity.pk}/coordinates/").status_code,
            400,
        )