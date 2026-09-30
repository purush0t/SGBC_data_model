"""Reader abstractions and bounded demo data for the spatial viewer."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from io import BytesIO
from math import exp
import os
from pathlib import Path
import re

import numpy as np


MAX_POINTS = 50_000
MAX_IMAGE_DIMENSION = 4096


class SpatialDataError(ValueError):
    """A safe, user-facing spatial data request error."""


class SpatialDatasetUnavailable(SpatialDataError):
    """A known dataset is unavailable in this environment."""


def _select_display_raster(rasters):
    rasters = list(rasters)
    if not rasters:
        return None
    suitable = [
        raster for raster in rasters
        if max(raster.sizes["x"], raster.sizes["y"]) <= MAX_IMAGE_DIMENSION
    ]
    if suitable:
        return max(suitable, key=lambda raster: raster.sizes["x"] * raster.sizes["y"])
    return min(rasters, key=lambda raster: raster.sizes["x"] * raster.sizes["y"])


def _scale_spatial_coordinates(coordinates, source_raster, display_raster):
    coordinates = np.asarray(coordinates, dtype=np.float64).copy()
    coordinates[:, 0] *= display_raster.sizes["x"] / source_raster.sizes["x"]
    coordinates[:, 1] *= display_raster.sizes["y"] / source_raster.sizes["y"]
    return coordinates


@dataclass(frozen=True)
class SpatialDatasetReader:
    dataset_id: str

    def get_metadata(self) -> dict:
        raise NotImplementedError

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        raise NotImplementedError

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        raise NotImplementedError

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        raise NotImplementedError


class SyntheticSpatialDatasetReader(SpatialDatasetReader):
    """Small structured data exercising the real API and Canvas pipeline."""

    genes = tuple(f"Gene_{index}" for index in range(50))

    def get_metadata(self) -> dict:
        return {
            "id": self.dataset_id,
            "name": "Synthetic Demo Dataset",
            "description": "Structured synthetic data for viewer development; not a biological observation.",
            "species": "Synthetic",
            "platform": "Demo reader",
            "resolution": "100 spatial bins",
            "width": 100,
            "height": 100,
            "n_bins": 100,
            "n_genes": len(self.genes),
            "genes": list(self.genes),
            "layers": [
                {"id": "coordinates", "name": "Spatial bins", "available": True},
                {"id": "expression", "name": "Gene expression", "available": True},
                {"id": "clusters", "name": "Clusters", "available": True},
                {"id": "image", "name": "Tissue image", "available": False},
                {"id": "tissue_mask", "name": "Tissue mask", "available": False},
                {"id": "cell_mask", "name": "Cell segmentation", "available": False},
                {"id": "umap", "name": "UMAP", "available": False},
            ],
            "synthetic": True,
        }

    @staticmethod
    def _in_bounds(x: float, y: float, bounds: dict | None) -> bool:
        if not bounds:
            return True
        return bounds["xmin"] <= x <= bounds["xmax"] and bounds["ymin"] <= y <= bounds["ymax"]

    def _points(self, bounds: dict | None, limit: int) -> list[dict]:
        if limit < 1 or limit > MAX_POINTS:
            raise SpatialDataError(f"limit must be between 1 and {MAX_POINTS}.")
        points = []
        for row in range(10):
            for column in range(10):
                x, y = column * 10 + 5, row * 10 + 5
                if self._in_bounds(x, y, bounds):
                    points.append({
                        "id": f"bin-{row:02d}-{column:02d}",
                        "x": x,
                        "y": y,
                        "cluster": f"Region {('A', 'B', 'C')[(column + row) % 3]}",
                    })
        return points[:limit]

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        return self._points(bounds, limit)

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        if gene not in self.genes:
            raise SpatialDataError(f"Gene {gene!r} was not found in this dataset.")
        gene_index = self.genes.index(gene)
        values = []
        for point in self._points(bounds, limit):
            region = (point["x"] // 10 + point["y"] // 10) % 3
            target = gene_index % 3
            distance = abs(region - target)
            value = 2.0 + (8.0 if distance == 0 else 1.5) * exp(-((gene_index % 10) / 9))
            values.append({**point, "value": round(value, 4), "scale": "synthetic raw counts"})
        return values

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        points = self._points(bounds, limit)
        return [{**point, "value": round(sum(
            2.0 + (8.0 if abs((point["x"] // 10 + point["y"] // 10) % 3 - index % 3) == 0 else 1.5)
            * exp(-((index % 10) / 9)) for index in range(len(self.genes))
        ), 4), "scale": "synthetic total counts"} for point in points]


def _mouse_liver_path() -> Path:
    configured_path = os.environ.get("SPATIALDATA_MOUSE_LIVER_PATH")
    if configured_path:
        return Path(configured_path)
    return _spatial_data_directory() / "mouse_liver.zarr"


def _spatial_data_directory() -> Path:
    configured_path = os.environ.get("SPATIALDATA_DIRECTORY")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "spatial"


def _dataset_slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-_").lower()


@dataclass(frozen=True)
class SpatialDataZarrReader(SpatialDatasetReader):
    data_path: Path
    name: str
    description: str
    species: str
    platform: str

    @cached_property
    def _data(self):
        if not self.data_path.is_dir():
            raise SpatialDatasetUnavailable(
                f"The SpatialData store for {self.dataset_id!r} is missing at {self.data_path}."
            )
        try:
            import spatialdata
        except ImportError as error:
            raise SpatialDatasetUnavailable(
                "Install the optional SpatialData dependency to read this dataset."
            ) from error
        try:
            return spatialdata.read_zarr(str(self.data_path))
        except Exception as error:
            raise SpatialDatasetUnavailable(f"Could not read the SpatialData store: {error}") from error

    @cached_property
    def _table(self):
        return self._data.tables["table"]

    @cached_property
    def _image_rasters(self):
        image = self._data.images.get("raw_image")
        if image is None:
            return ()
        return tuple(image[level].ds["image"] for level in image.keys())

    @cached_property
    def _image_raster(self):
        return _select_display_raster(self._image_rasters)

    @cached_property
    def _image_reference_raster(self):
        if not self._image_rasters:
            return None
        return max(
            self._image_rasters,
            key=lambda raster: raster.sizes["x"] * raster.sizes["y"],
        )

    @cached_property
    def _cells(self):
        table = self._table
        coordinates = np.asarray(table.obsm["spatial"])
        if self._image_reference_raster is not None and self._image_raster is not None:
            coordinates = _scale_spatial_coordinates(
                coordinates,
                self._image_reference_raster,
                self._image_raster,
            )
        matrix = table.X.tocsr() if hasattr(table.X, "tocsr") else np.asarray(table.X)
        if hasattr(matrix, "tocsr"):
            detected = np.asarray((matrix > 0).sum(axis=1)).reshape(-1)
            totals = np.asarray(matrix.sum(axis=1)).reshape(-1)
        else:
            detected = np.count_nonzero(matrix, axis=1)
            totals = matrix.sum(axis=1)
        cells = []
        for index, observation in table.obs.reset_index(drop=True).iterrows():
            cells.append({
                "id": str(observation["cell_ID"]),
                "x": float(coordinates[index, 0]),
                "y": float(coordinates[index, 1]),
                "annotation": str(observation["annotation"]),
                "genes_detected": int(detected[index]),
                "total_counts": int(totals[index]),
            })
        return cells

    def get_metadata(self) -> dict:
        if not self.data_path.is_dir():
            return {
                "id": self.dataset_id,
                "name": self.name,
                "description": self.description,
                "species": self.species,
                "platform": self.platform,
                "resolution": "Unavailable",
                "width": 0,
                "height": 0,
                "n_bins": 0,
                "n_genes": 0,
                "genes": [],
                "layers": [
                    {"id": layer_id, "name": layer_name, "available": False}
                    for layer_id, layer_name in (
                        ("coordinates", "Spatial cells"),
                        ("image", "Tissue image"),
                        ("tissue_mask", "Segmentation mask"),
                        ("cell_boundaries", "Cell boundaries"),
                        ("expression", "Gene expression"),
                        ("cell_annotations", "Cell annotations"),
                    )
                ],
                "synthetic": False,
                "reader_available": False,
            }
        data = self._data
        image = data.images.get("raw_image")
        segmentation = data.labels.get("segmentation_mask")
        table = self._table
        if segmentation is not None:
            height, width = segmentation.shape
        elif self._image_raster is not None:
            height = self._image_raster.sizes["y"]
            width = self._image_raster.sizes["x"]
        else:
            height, width = 0, 0
        available = {
            "coordinates": True,
            "image": image is not None,
            "tissue_mask": segmentation is not None,
            "cell_boundaries": "nucleus_boundaries" in data.shapes,
            "transcripts": "transcripts" in data.points,
            "expression": table is not None,
            "cell_annotations": "annotation" in table.obs,
            "clusters": False,
            "umap": "X_umap" in table.obsm,
        }
        layer_names = {
            "coordinates": "Spatial cells",
            "image": "Tissue image",
            "tissue_mask": "Segmentation mask",
            "cell_boundaries": "Nucleus boundaries",
            "transcripts": "Transcript points",
            "expression": "Gene expression",
            "cell_annotations": "Cell annotations",
            "clusters": "Clusters",
            "umap": "UMAP",
        }
        renderable = {
            "coordinates": True,
            "image": True,
            "tissue_mask": True,
            "cell_boundaries": False,
            "transcripts": False,
            "expression": True,
            "cell_annotations": True,
            "clusters": False,
            "umap": False,
        }
        return {
            "id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "species": self.species,
            "platform": self.platform,
            "resolution": f"{width} × {height} pixels",
            "width": int(width),
            "height": int(height),
            "n_bins": int(table.n_obs),
            "n_genes": int(table.n_vars),
            "genes": [str(gene) for gene in table.var_names],
            "layers": [
                {
                    "id": layer_id,
                    "name": layer_names[layer_id],
                    "available": is_available,
                    "renderable": renderable[layer_id],
                }
                for layer_id, is_available in available.items()
            ],
            "synthetic": False,
            "reader_available": True,
            "expression_scale": "raw counts",
        }

    @cached_property
    def _image_png(self) -> bytes:
        from PIL import Image

        image = self._image_raster
        if image is None:
            raise SpatialDataError("The tissue image is unavailable.")
        pixels = image.data.compute()
        if "c" in image.dims:
            pixels = np.moveaxis(pixels, image.get_axis_num("c"), -1)
        if pixels.shape[-1:] == (1,):
            pixels = pixels[..., 0]
        if pixels.dtype != np.uint8:
            if pixels.ndim == 2:
                low, high = np.percentile(pixels, (1, 99))
                pixels = np.clip((pixels.astype(np.float32) - low) * (255 / max(high - low, 1)), 0, 255)
            else:
                low, high = np.percentile(pixels, (1, 99), axis=(0, 1), keepdims=True)
                pixels = np.clip((pixels.astype(np.float32) - low) * (255 / np.maximum(high - low, 1)), 0, 255)
            pixels = pixels.astype(np.uint8)
        if pixels.ndim == 3 and pixels.shape[-1] > 3:
            pixels = pixels[..., :3]
        output = BytesIO()
        Image.fromarray(pixels).save(output, format="PNG", optimize=True)
        return output.getvalue()

    @cached_property
    def _mask_png(self) -> bytes:
        from PIL import Image

        segmentation = self._data.labels.get("segmentation_mask")
        if segmentation is None:
            raise SpatialDataError("The segmentation mask is unavailable.")
        mask = segmentation.isel(y=slice(None, None, 4), x=slice(None, None, 4))
        labels = mask.data.compute().astype(np.int32)
        colors = np.random.default_rng(2022).integers(55, 220, size=(int(labels.max()) + 1, 3), dtype=np.uint8)
        pixels = np.zeros((*labels.shape, 4), dtype=np.uint8)
        pixels[..., :3] = colors[labels]
        pixels[..., 3] = np.where(labels == 0, 0, 110).astype(np.uint8)
        output = BytesIO()
        Image.fromarray(pixels).save(output, format="PNG", optimize=True)
        return output.getvalue()

    def get_image(self) -> bytes:
        return self._image_png

    def get_mask(self) -> bytes:
        return self._mask_png

    @staticmethod
    def _validate_query(bounds: dict | None, limit: int) -> None:
        if limit < 1 or limit > MAX_POINTS:
            raise SpatialDataError(f"limit must be between 1 and {MAX_POINTS}.")
        if bounds and (bounds["xmin"] > bounds["xmax"] or bounds["ymin"] > bounds["ymax"]):
            raise SpatialDataError("Minimum bounds must not exceed maximum bounds.")

    def _selected_cells(self, bounds: dict | None, limit: int) -> list[dict]:
        self._validate_query(bounds, limit)
        cells = self._cells
        if bounds:
            cells = [
                cell for cell in cells
                if bounds["xmin"] <= cell["x"] <= bounds["xmax"]
                and bounds["ymin"] <= cell["y"] <= bounds["ymax"]
            ]
        return cells[:limit]

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        return self._selected_cells(bounds, limit)

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        self._validate_query(bounds, limit)
        table = self._table
        if gene not in table.var_names:
            raise SpatialDataError(f"Gene {gene!r} was not found in this dataset.")
        column = table[:, gene].X
        values = column.toarray().reshape(-1) if hasattr(column, "toarray") else np.asarray(column).reshape(-1)
        cells = self._selected_cells(bounds, limit)
        index_by_id = {cell["id"]: index for index, cell in enumerate(self._cells)}
        return [
            {"id": cell["id"], "x": cell["x"], "y": cell["y"], "value": int(values[index_by_id[cell["id"]]])}
            for cell in cells
        ]

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        return [
            {"id": cell["id"], "x": cell["x"], "y": cell["y"], "value": cell["total_counts"]}
            for cell in self._selected_cells(bounds, limit)
        ]


@dataclass(frozen=True)
class RegisteredSpatialDatasetReader(SpatialDatasetReader):
    metadata: dict

    def get_metadata(self) -> dict:
        return {"id": self.dataset_id, "synthetic": False, **self.metadata}

    def _unavailable(self):
        raise SpatialDataError("This dataset is registered, but no compatible spatial reader is available.")

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        self._unavailable()

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        self._unavailable()

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS) -> list[dict]:
        self._unavailable()


_READERS = {
    "synthetic-demo": SyntheticSpatialDatasetReader("synthetic-demo"),
    "mouse_liver_demo": SpatialDataZarrReader(
        "mouse_liver_demo",
        _mouse_liver_path(),
        "Mouse Liver SpatialData Demo",
        "Molecular Cartography mouse-liver demo from Guilliams et al. 2022.",
        "Mouse",
        "Molecular Cartography",
    ),
}


def _zarr_readers() -> dict[str, SpatialDataZarrReader]:
    directory = _spatial_data_directory()
    if not directory.is_dir():
        return {}
    readers = {}
    for data_path in sorted(directory.glob("*.zarr")):
        if not ((data_path / "zarr.json").is_file() or (data_path / ".zgroup").is_file()):
            continue
        if data_path.resolve() == _mouse_liver_path().resolve():
            continue
        dataset_id = _dataset_slug(data_path.name.removesuffix(".zarr"))
        if not dataset_id or dataset_id in _READERS or dataset_id in readers:
            continue
        readers[dataset_id] = SpatialDataZarrReader(
            dataset_id,
            data_path,
            data_path.name.removesuffix(".zarr").replace("_", " "),
            "SpatialData Zarr store.",
            "Unknown",
            "SpatialData",
        )
    return readers


def _registered_readers() -> dict[str, RegisteredSpatialDatasetReader]:
    from .models import Entity, EntityInformationRecord

    records = EntityInformationRecord.objects.select_related("entity", "entity__entity_type").order_by(
        "entity_id", "-version", "-recorded_at"
    )
    readers = {}
    for record in records:
        if record.entity_id in {reader.metadata.get("entity_pk") for reader in readers.values()}:
            continue
        registration = (record.metadata or {}).get("spatial_dataset")
        if not isinstance(registration, dict):
            continue
        dataset_id = f"entity-{record.entity_id}"
        readers[dataset_id] = RegisteredSpatialDatasetReader(dataset_id, {
            "name": registration.get("name", record.entity.identifier),
            "description": registration.get(
                "description", "A provenance entity registered as a spatial dataset."
            ),
            "entity_id": record.entity_id,
            "entity_identifier": record.entity.identifier,
            "entity_type": record.entity.entity_type.code,
            "layers": registration.get("layers", []),
            "genes": registration.get("genes", []),
            "n_bins": registration.get("n_bins"),
            "n_genes": registration.get("n_genes"),
            "reader_available": False,
            "entity_pk": record.entity_id,
        })
    return readers


def get_reader(dataset_id: str) -> SpatialDatasetReader:
    readers = {**_READERS, **_zarr_readers(), **_registered_readers()}
    try:
        return readers[dataset_id]
    except KeyError as error:
        raise SpatialDataError("Dataset is unavailable or has no registered reader.") from error


def list_datasets() -> list[dict]:
    readers = {**_READERS, **_zarr_readers(), **_registered_readers()}
    datasets = []
    for reader in readers.values():
        if isinstance(reader, SpatialDataZarrReader):
            datasets.append({
                "id": reader.dataset_id,
                "name": reader.name,
                "description": reader.description,
                "reader_available": reader.data_path.is_dir(),
            })
        else:
            datasets.append(reader.get_metadata())
    return datasets
