from io import BytesIO

from django.test import TestCase
from PIL import Image

from .models import Entity, EntityInformationRecord, EntityType, InformationRecordType
from .spatial import _mouse_liver_path


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

    def test_overall_expression_returns_total_counts(self):
        response = self.client.get("/api/spatial/synthetic-demo/expression/", {"overall": "true", "limit": 3})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["gene"], "Overall expression")
        self.assertEqual(response.json()["count"], 3)
        self.assertTrue(all(point["value"] > 0 for point in response.json()["points"]))

    def test_invalid_gene_and_unbounded_limit_are_rejected(self):
        missing_gene = self.client.get(
            "/api/spatial/synthetic-demo/expression/", {"gene": "not-a-gene"}
        )
        too_many = self.client.get(
            "/api/spatial/synthetic-demo/coordinates/", {"limit": 50001}
        )

        self.assertEqual(missing_gene.status_code, 400)
        self.assertEqual(too_many.status_code, 400)

    def test_mouse_liver_demo_is_available_and_capable(self):
        if not _mouse_liver_path().is_dir():
            self.skipTest("Run scripts/download_spatialdata_demo.sh to install the real demo store.")

        response = self.client.get("/api/spatial/mouse_liver_demo/metadata/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "mouse_liver_demo")
        layers = {layer["id"]: layer for layer in response.json()["layers"]}
        for layer_id in ("image", "tissue_mask", "expression", "cell_boundaries", "transcripts"):
            self.assertTrue(layers[layer_id]["available"])
        self.assertFalse(layers["umap"]["available"])

    def test_mouse_liver_image_and_mask_are_served_as_aligned_pngs(self):
        if not _mouse_liver_path().is_dir():
            self.skipTest("Run scripts/download_spatialdata_demo.sh to install the real demo store.")

        image_response = self.client.get("/api/spatial/mouse_liver_demo/image/")
        mask_response = self.client.get("/api/spatial/mouse_liver_demo/mask/")
        image = Image.open(BytesIO(image_response.content))
        mask = Image.open(BytesIO(mask_response.content))

        self.assertEqual(image_response["Content-Type"], "image/png")
        self.assertEqual(mask_response["Content-Type"], "image/png")
        self.assertEqual(image.size, mask.size)
        self.assertEqual(mask.mode, "RGBA")

    def test_mouse_liver_gene_api_returns_only_raw_gene_values(self):
        if not _mouse_liver_path().is_dir():
            self.skipTest("Run scripts/download_spatialdata_demo.sh to install the real demo store.")

        response = self.client.get(
            "/api/spatial/mouse_liver_demo/expression/", {"gene": "Axl", "limit": 3}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scale"], "raw counts")
        self.assertEqual(response.json()["count"], 3)
        self.assertEqual(set(response.json()["points"][0]), {"id", "x", "y", "value"})

    def test_unknown_dataset_is_not_exposed(self):
        response = self.client.get("/api/spatial/unknown/metadata/")

        self.assertEqual(response.status_code, 404)

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