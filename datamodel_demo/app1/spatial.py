"""Reader abstractions and bounded demo data for the spatial viewer."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from io import BytesIO
from math import ceil, exp, log2
import os
from pathlib import Path
import re
from threading import Lock

import numpy as np


MAX_POINTS = 50_000
MAX_IMAGE_DIMENSION = 4096
IMAGE_TILE_SIZE = 256


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


def _spatial_dimensions(image_raster, segmentation):
    if image_raster is not None:
        return image_raster.sizes["y"], image_raster.sizes["x"]
    if segmentation is not None:
        return segmentation.shape
    return 0, 0


@dataclass(frozen=True)
class SpatialDatasetReader:
    dataset_id: str

    def get_metadata(self) -> dict:
        raise NotImplementedError

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        raise NotImplementedError

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        raise NotImplementedError

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        raise NotImplementedError

    def get_cell_details(self, cell_id: str) -> dict:
        raise NotImplementedError

    def get_coordinate_count(self, bounds: dict | None = None) -> int:
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

    def _points(self, bounds: dict | None, limit: int, offset: int) -> list[dict]:
        if limit < 1 or limit > MAX_POINTS:
            raise SpatialDataError(f"limit must be between 1 and {MAX_POINTS}.")
        if offset < 0:
            raise SpatialDataError("offset must be non-negative.")
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
        return points[offset:offset + limit]

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        return self._points(bounds, limit, offset)

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        if gene not in self.genes:
            raise SpatialDataError(f"Gene {gene!r} was not found in this dataset.")
        gene_index = self.genes.index(gene)
        values = []
        for point in self._points(bounds, limit, offset):
            region = (point["x"] // 10 + point["y"] // 10) % 3
            target = gene_index % 3
            distance = abs(region - target)
            value = 2.0 + (8.0 if distance == 0 else 1.5) * exp(-((gene_index % 10) / 9))
            values.append({**point, "value": round(value, 4), "scale": "synthetic raw counts"})
        return values

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        points = self._points(bounds, limit, offset)
        return [{**point, "value": round(sum(
            2.0 + (8.0 if abs((point["x"] // 10 + point["y"] // 10) % 3 - index % 3) == 0 else 1.5)
            * exp(-((index % 10) / 9)) for index in range(len(self.genes))
        ), 4), "scale": "synthetic total counts"} for point in points]

    def get_cell_details(self, cell_id: str) -> dict:
        for point in self._points(None, MAX_POINTS, 0):
            if point["id"] == cell_id:
                return point
        raise SpatialDataError(f"Cell {cell_id!r} was not found in this dataset.")

    def get_coordinate_count(self, bounds: dict | None = None) -> int:
        return len(self._points(bounds, MAX_POINTS, 0))


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
    _data_lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    @property
    def _data(self):
        data = self.__dict__.get("_loaded_data")
        if data is not None:
            return data
        with self._data_lock:
            data = self.__dict__.get("_loaded_data")
            if data is not None:
                return data
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
                data = spatialdata.read_zarr(str(self.data_path))
            except Exception as error:
                raise SpatialDatasetUnavailable(f"Could not read the SpatialData store: {error}") from error
            self.__dict__["_loaded_data"] = data
            return data

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
        if not self._image_rasters:
            return None
        return max(
            self._image_rasters,
            key=lambda raster: raster.sizes["x"] * raster.sizes["y"],
        )

    @cached_property
    def _display_image_raster(self):
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
    def _image_intensity_range(self):
        raster = self._image_raster
        sample = raster.isel(x=slice(None, None, 16), y=slice(None, None, 16))
        axes = ["y", "x"] + (["c"] if "c" in sample.dims else [])
        data = sample.transpose(*axes).data
        pixels = data.compute() if hasattr(data, "compute") else np.asarray(data)
        if pixels.dtype == np.uint8:
            return None
        if pixels.ndim == 2:
            low, high = np.percentile(pixels, (1, 99))
        else:
            low, high = np.percentile(pixels, (1, 99), axis=(0, 1), keepdims=True)
        return low, high

    def get_image_dimensions(self) -> tuple[int, int]:
        raster = self._image_raster
        if raster is None:
            raise SpatialDataError("The tissue image is unavailable.")
        return int(raster.sizes["x"]), int(raster.sizes["y"])

    def get_image_tile(self, level: int, column: int, row: int) -> bytes:
        from PIL import Image

        raster = self._image_raster
        if raster is None:
            raise SpatialDataError("The tissue image is unavailable.")
        width, height = self.get_image_dimensions()
        max_level = ceil(log2(max(width, height)))
        if level < 0 or level > max_level or column < 0 or row < 0:
            raise SpatialDataError("The requested image tile is outside the image pyramid.")

        downsample = 2 ** (max_level - level)
        level_width = ceil(width / downsample)
        level_height = ceil(height / downsample)
        left = column * IMAGE_TILE_SIZE
        top = row * IMAGE_TILE_SIZE
        if left >= level_width or top >= level_height:
            raise SpatialDataError("The requested image tile is outside the image pyramid.")
        tile_width = min(IMAGE_TILE_SIZE, level_width - left)
        tile_height = min(IMAGE_TILE_SIZE, level_height - top)

        source_rasters = [
            candidate for candidate in self._image_rasters
            if candidate.sizes["x"] >= level_width and candidate.sizes["y"] >= level_height
        ]
        if source_rasters:
            raster = min(
                source_rasters,
                key=lambda candidate: candidate.sizes["x"] * candidate.sizes["y"],
            )
        source_width, source_height = int(raster.sizes["x"]), int(raster.sizes["y"])
        scale_x, scale_y = width / source_width, height / source_height
        step_x = max(1, round(downsample / scale_x))
        step_y = max(1, round(downsample / scale_y))
        source_left = round(left * source_width / level_width)
        source_top = round(top * source_height / level_height)
        source_right = ceil((left + tile_width) * source_width / level_width)
        source_bottom = ceil((top + tile_height) * source_height / level_height)
        tile = raster.isel(
            x=slice(source_left, source_right, step_x),
            y=slice(source_top, source_bottom, step_y),
        )
        axes = ["y", "x"] + (["c"] if "c" in tile.dims else [])
        data = tile.transpose(*axes).data
        pixels = data.compute() if hasattr(data, "compute") else np.asarray(data)
        if pixels.dtype != np.uint8:
            low, high = self._image_intensity_range
            pixels = np.clip((pixels.astype(np.float32) - low) * (255 / np.maximum(high - low, 1)), 0, 255)
            pixels = pixels.astype(np.uint8)
        if "c" in tile.dims and pixels.shape[-1] == 1:
            pixels = pixels[..., 0]
        image = Image.fromarray(pixels).convert("RGB")
        if image.size != (tile_width, tile_height):
            image = image.resize((tile_width, tile_height), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()

    @staticmethod
    def _string_value(value) -> str | None:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null", "na", "n/a", "unannotated"}:
            return None
        return text

    @classmethod
    def _annotation_value(cls, observation: dict) -> str | None:
        candidates = (
            "annotation",
            "cell_type",
            "cellType",
            "celltype",
            "cell_type_name",
            "cellTypeName",
            "cell_type_label",
            "cluster_label",
            "cluster_name",
        )
        for column in candidates:
            value = cls._string_value(observation.get(column))
            if value is None:
                continue
            if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
                continue
            return value
        return None

    @classmethod
    def _cluster_value(cls, observation: dict) -> str | None:
        candidates = (
            "cluster",
            "cluster_name",
            "cluster_label",
            "leiden",
            "cell_cluster",
            "cell_cluster_label",
            "annotation",
            "cell_type",
            "cellType",
            "celltype",
        )
        for column in candidates:
            value = cls._string_value(observation.get(column))
            if value is None:
                continue
            return value
        return None

    def _gene_display_names(self) -> dict[str, str]:
        var = self._table.var
        mapping = {str(gene): str(gene) for gene in self._table.var_names}
        if not hasattr(var, "columns"):
            return mapping
        for column in ("gene_symbol", "symbol", "gene_name", "geneName", "feature_symbol", "feature_name", "gene_symbols"):
            if column not in var.columns:
                continue
            labels = var[column].astype("string")
            for gene, label in zip(self._table.var_names, labels):
                display = self._string_value(label)
                if display is None or str(gene) == display:
                    continue
                mapping[str(gene)] = display
        return mapping

    def _resolve_gene(self, gene: str) -> str:
        target = str(gene).strip()
        if not target:
            return target
        if target in self._table.var_names:
            return target
        normalized = re.sub(r"\.\d+$", "", target).lower()
        matches = []
        for var_name in self._table.var_names:
            if re.sub(r"\.\d+$", "", str(var_name)).lower() == normalized:
                matches.append(str(var_name))
        if len(matches) == 1:
            return matches[0]
        for gene_id, display_name in self._gene_display_names().items():
            if gene_id == target:
                return gene_id
            if re.sub(r"\.\d+$", "", str(display_name)).lower() == normalized:
                matches.append(gene_id)
        if len(matches) == 1:
            return matches[0]
        return target

    @cached_property
    def _cell_data(self):
        table = self._table
        coordinates = np.asarray(table.obsm["spatial"])
        if self._image_reference_raster is not None and self._image_raster is not None:
            coordinates = _scale_spatial_coordinates(
                coordinates,
                self._image_reference_raster,
                self._image_raster,
            )
        cell_ids, annotations, clusters = [], [], []
        for index, observation in table.obs.reset_index(drop=True).iterrows():
            values = observation.to_dict()
            annotation = self._annotation_value(values)
            cluster = self._cluster_value(values)
            if annotation is None and cluster is not None:
                annotation = cluster
            cell_ids.append(str(values["cell_ID"]))
            annotations.append(annotation)
            clusters.append(cluster if cluster and cluster != annotation else None)
        return {
            "id": np.asarray(cell_ids, dtype=object),
            "x": np.asarray(coordinates[:, 0], dtype=np.float64),
            "y": np.asarray(coordinates[:, 1], dtype=np.float64),
            "annotation": annotations,
            "cluster": clusters,
        }

    @cached_property
    def _cell_x_order(self):
        order = np.argsort(self._cell_data["x"], kind="stable")
        return self._cell_data["x"][order], order

    @cached_property
    def _cell_index_by_id(self):
        return {cell_id: index for index, cell_id in enumerate(self._cell_data["id"])}

    def _matching_indices(self, bounds: dict | None) -> np.ndarray:
        data = self._cell_data
        if not bounds:
            return np.arange(len(data["id"]))
        sorted_x, order = self._cell_x_order
        first = np.searchsorted(sorted_x, bounds["xmin"], side="left")
        last = np.searchsorted(sorted_x, bounds["xmax"], side="right")
        indices = order[first:last]
        visible = (data["y"][indices] >= bounds["ymin"]) & (data["y"][indices] <= bounds["ymax"])
        return np.sort(indices[visible], kind="stable")

    def get_coordinate_count(self, bounds: dict | None = None) -> int:
        self._validate_query(bounds, 1, 0)
        return len(self._matching_indices(bounds))

    def _selected_indices(self, bounds: dict | None, limit: int, offset: int, sample: bool = False) -> np.ndarray:
        self._validate_query(bounds, limit, offset)
        indices = self._matching_indices(bounds)
        if sample and offset == 0 and len(indices) > limit:
            return indices[np.linspace(0, len(indices) - 1, num=limit, dtype=np.int64)]
        return indices[offset:offset + limit]

    def _cell_records(self, indices: np.ndarray) -> list[dict]:
        data = self._cell_data
        return [
            {
                "id": str(data["id"][index]),
                "x": float(data["x"][index]),
                "y": float(data["y"][index]),
                "annotation": data["annotation"][index],
                "cluster": data["cluster"][index],
            }
            for index in indices
        ]

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
                "display_width": 0,
                "display_height": 0,
                "n_bins": 0,
                "n_genes": 0,
                "genes": [],
                "gene_display_names": {},
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
        height, width = _spatial_dimensions(self._image_raster, segmentation)
        display_raster = self._display_image_raster
        display_width = int(display_raster.sizes["x"]) if display_raster is not None else 0
        display_height = int(display_raster.sizes["y"]) if display_raster is not None else 0
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
        gene_display_names = self._gene_display_names()
        return {
            "id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "species": self.species,
            "platform": self.platform,
            "resolution": f"{width} × {height} pixels",
            "width": int(width),
            "height": int(height),
            "display_width": display_width,
            "display_height": display_height,
            "n_bins": int(table.n_obs),
            "n_genes": int(table.n_vars),
            "genes": [str(gene) for gene in table.var_names],
            "gene_display_names": gene_display_names,
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

        image = self._display_image_raster
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
    def _validate_query(bounds: dict | None, limit: int, offset: int) -> None:
        if limit < 1 or limit > MAX_POINTS:
            raise SpatialDataError(f"limit must be between 1 and {MAX_POINTS}.")
        if offset < 0:
            raise SpatialDataError("offset must be non-negative.")
        if bounds and (bounds["xmin"] > bounds["xmax"] or bounds["ymin"] > bounds["ymax"]):
            raise SpatialDataError("Minimum bounds must not exceed maximum bounds.")

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        return self._cell_records(self._selected_indices(bounds, limit, offset, sample))

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        self._validate_query(bounds, limit, offset)
        table = self._table
        gene = self._resolve_gene(gene)
        if gene not in table.var_names:
            raise SpatialDataError(f"Gene {gene!r} was not found in this dataset.")
        indices = self._selected_indices(bounds, limit, offset, sample)
        column = table[indices, gene].X
        values = column.toarray().reshape(-1) if hasattr(column, "toarray") else np.asarray(column).reshape(-1)
        return [
            {"id": str(self._cell_data["id"][index]), "x": float(self._cell_data["x"][index]), "y": float(self._cell_data["y"][index]), "value": int(value)}
            for index, value in zip(indices, values)
        ]

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        indices = self._selected_indices(bounds, limit, offset, sample)
        if not len(indices):
            return []
        matrix = self._table.X
        rows = matrix[indices] if hasattr(matrix, "__getitem__") else np.asarray(matrix)[indices]
        if hasattr(rows, "tocsr"):
            rows = rows.tocsr()
            totals = np.asarray(rows.sum(axis=1)).reshape(-1)
        else:
            rows = np.asarray(rows)
            totals = rows.sum(axis=1)
        return [
            {
                "id": str(self._cell_data["id"][index]),
                "x": float(self._cell_data["x"][index]),
                "y": float(self._cell_data["y"][index]),
                "value": int(total),
            }
            for index, total in zip(indices, totals)
        ]

    def get_cell_details(self, cell_id: str) -> dict:
        index = self._cell_index_by_id.get(cell_id)
        if index is None:
            raise SpatialDataError(f"Cell {cell_id!r} was not found in this dataset.")
        matrix = self._table.X
        row = matrix.getrow(index) if hasattr(matrix, "getrow") else np.asarray(matrix[index]).reshape(-1)
        if hasattr(row, "getnnz"):
            genes_detected = int((row > 0).getnnz())
            total_counts = int(row.sum())
        else:
            genes_detected = int(np.count_nonzero(row))
            total_counts = int(np.sum(row))
        details = self._cell_records(np.asarray([index]))[0]
        details.update({"genes_detected": genes_detected, "total_counts": total_counts})
        return details


@dataclass(frozen=True)
class RegisteredSpatialDatasetReader(SpatialDatasetReader):
    metadata: dict

    def get_metadata(self) -> dict:
        return {"id": self.dataset_id, "synthetic": False, **self.metadata}

    def _unavailable(self):
        raise SpatialDataError("This dataset is registered, but no compatible spatial reader is available.")

    def get_coordinates(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        self._unavailable()

    def get_expression(self, gene: str, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        self._unavailable()

    def get_overall_expression(self, *, bounds: dict | None = None, limit: int = MAX_POINTS, offset: int = 0, sample: bool = False) -> list[dict]:
        self._unavailable()

    def get_cell_details(self, cell_id: str) -> dict:
        self._unavailable()

    def get_coordinate_count(self, bounds: dict | None = None) -> int:
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
_ZARR_READER_CACHE: dict[str, SpatialDataZarrReader] = {}


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
    reader = _READERS.get(dataset_id)
    if reader is not None:
        return reader
    reader = _ZARR_READER_CACHE.get(dataset_id)
    if reader is not None and reader.data_path.is_dir():
        return reader
    _ZARR_READER_CACHE.pop(dataset_id, None)
    reader = _zarr_readers().get(dataset_id)
    if reader is not None:
        return _ZARR_READER_CACHE.setdefault(dataset_id, reader)
    reader = _registered_readers().get(dataset_id)
    if reader is None:
        raise SpatialDataError("Dataset is unavailable or has no registered reader.")
    return reader


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
