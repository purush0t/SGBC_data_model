from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase

from .models import Entity, EntityInformationRecord, EntityType, InformationRecordType
from .spatial import _spatial_dimensions


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

    def test_invalid_gene_and_unbounded_limit_are_rejected(self):
        missing_gene = self.client.get(
            "/api/spatial/synthetic-demo/expression/", {"gene": "not-a-gene"}
        )
        too_many = self.client.get(
            "/api/spatial/synthetic-demo/coordinates/", {"limit": 50001}
        )

        self.assertEqual(missing_gene.status_code, 400)
        self.assertEqual(too_many.status_code, 400)

    def test_canvas_dimensions_follow_display_image_not_full_resolution_mask(self):
        image = type("Raster", (), {"sizes": {"x": 1608, "y": 1608}})()
        mask = type("Mask", (), {"shape": (6432, 6432)})()

        self.assertEqual(_spatial_dimensions(image, mask), (1608, 1608))

    def test_mouse_liver_demo_is_available_and_capable(self):
        response = self.client.get("/api/spatial/mouse_liver_demo/metadata/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "mouse_liver_demo")
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

        self.assertEqual(response.status_code, 200)
        test_store = next(
            dataset for dataset in response.json()["datasets"] if dataset["id"] == "test_out"
        )
        self.assertTrue(test_store["reader_available"])

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