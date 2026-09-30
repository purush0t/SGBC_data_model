#!/usr/bin/env python3
"""Convert STOmics SAW cell-bin outputs into a viewer-ready SpatialData Zarr."""

from __future__ import annotations

import argparse
from math import floor, isfinite
from pathlib import Path
import re
import shutil
import tarfile
import tempfile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cellbin-gef", required=True, type=Path)
    h5ad_source = parser.add_mutually_exclusive_group(required=True)
    h5ad_source.add_argument("--cell-cluster-h5ad", type=Path)
    h5ad_source.add_argument("--visualization-archive", type=Path)
    parser.add_argument("--registered-tif", required=True, type=Path)
    parser.add_argument("--dataset-id", help="Dataset ID; defaults to the cell-bin GEF filename")
    parser.add_argument(
        "--crop-bounds",
        nargs=4,
        type=float,
        metavar=("X_MIN", "Y_MIN", "X_MAX", "Y_MAX"),
        help="Keep only cells in this inclusive pixel-coordinate rectangle and crop the image to match",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination Zarr directory (defaults to data/spatial/<dataset-id>.zarr)",
    )
    return parser.parse_args()


def checked_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"{label} is not a file: {resolved}")
    return resolved


def extract_cell_cluster_h5ad(archive_path: Path, destination: Path) -> Path:
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            matches = [
                member
                for member in archive.getmembers()
                if member.isfile() and Path(member.name).name.endswith("cell.cluster.h5ad")
            ]
            if len(matches) != 1:
                raise SystemExit(
                    "Expected exactly one *cell.cluster.h5ad in the visualization archive; "
                    f"found {len(matches)}. Export the cell.cluster.h5ad separately and pass "
                    "--cell-cluster-h5ad."
                )
            source = archive.extractfile(matches[0])
            if source is None:
                raise SystemExit("Could not read cell.cluster.h5ad from the visualization archive.")
            with source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    except (OSError, tarfile.TarError) as error:
        raise SystemExit(f"Could not read visualization archive {archive_path}: {error}") from error
    return destination


def crop_spatial_data(spatial_data, bounds: list[float]) -> tuple[int, tuple[int, int]]:
    import numpy as np

    if len(bounds) != 4 or not all(isfinite(value) for value in bounds):
        raise SystemExit("Crop bounds must be four finite pixel coordinates.")
    x_min, y_min, x_max, y_max = bounds
    if x_min < 0 or y_min < 0 or x_min > x_max or y_min > y_max:
        raise SystemExit("Crop bounds must be non-negative and ordered X_MIN Y_MIN X_MAX Y_MAX.")

    image = spatial_data.images["raw_image"]
    width, height = image.sizes["x"], image.sizes["y"]
    if x_max >= width or y_max >= height:
        raise SystemExit(f"Crop bounds exceed image dimensions ({width} x {height}).")
    x_start, y_start = floor(x_min), floor(y_min)
    x_stop, y_stop = floor(x_max) + 1, floor(y_max) + 1

    table = spatial_data.tables["table"]
    if "spatial" not in table.obsm:
        raise SystemExit("Imported table has no spatial coordinates to crop.")
    coordinates = np.asarray(table.obsm["spatial"])
    keep = (
        (coordinates[:, 0] >= x_min)
        & (coordinates[:, 0] <= x_max)
        & (coordinates[:, 1] >= y_min)
        & (coordinates[:, 1] <= y_max)
    )
    cell_count = int(keep.sum())
    if not cell_count:
        raise SystemExit("No cells fall within the requested crop bounds.")

    table = table[keep].copy()
    table.obsm["spatial"] = coordinates[keep] - np.array([x_start, y_start])
    spatial_data.tables["table"] = table
    spatial_data.images["raw_image"] = image.isel(
        x=slice(x_start, x_stop), y=slice(y_start, y_stop)
    )

    table_metadata = table.uns.get("spatialdata_attrs", {})
    region_key = table_metadata.get("region_key")
    instance_key = table_metadata.get("instance_key")
    if region_key and instance_key and region_key in table.obs and instance_key in table.obs:
        for region in table.obs[region_key].dropna().unique():
            shapes = spatial_data.shapes.get(str(region))
            if shapes is None:
                continue
            instance_ids = table.obs.loc[table.obs[region_key] == region, instance_key]
            shapes = shapes.loc[shapes.index.isin(instance_ids)].copy()
            shapes.geometry = shapes.geometry.translate(xoff=-x_start, yoff=-y_start)
            spatial_data.shapes[str(region)] = shapes

    return cell_count, (x_stop - x_start, y_stop - y_start)


def main() -> None:
    args = parse_args()
    cellbin_gef = checked_file(args.cellbin_gef, "Cell-bin GEF")
    registered_tif = checked_file(args.registered_tif, "Registered TIFF")
    visualization_archive = None
    if args.cell_cluster_h5ad:
        cell_cluster_h5ad = checked_file(args.cell_cluster_h5ad, "Cell-cluster H5AD")
    else:
        visualization_archive = checked_file(args.visualization_archive, "Visualization archive")
    dataset_id = (args.dataset_id or cellbin_gef.name.removesuffix(".cellbin.gef")).strip()
    dataset_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", dataset_id).strip("-_").lower()
    if not dataset_slug:
        raise SystemExit("Could not derive a filename-safe dataset ID from the input GEF.")
    output = args.output.expanduser().resolve() if args.output else (
        Path(__file__).resolve().parents[1]
        / "datamodel_demo/data/spatial"
        / f"{dataset_slug}.zarr"
    )
    if output.exists():
        raise SystemExit(f"Output already exists; choose a new path: {output}")

    try:
        from spatialdata_io import stereoseq
    except ImportError as error:
        raise SystemExit("Install the project requirements, including spatialdata-io, to convert GEF files.") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stomics-spatialdata-") as temporary:
        staging = Path(temporary)
        register = staging / "03.register"
        cellcut = staging / "041.cellcut"
        cellcluster = staging / "051.cellcluster"
        register.mkdir()
        cellcut.mkdir()
        cellcluster.mkdir()

        if visualization_archive:
            extract_cell_cluster_h5ad(
                visualization_archive,
                cellcluster / f"{dataset_id}.cell.cluster.h5ad",
            )
        else:
            (cellcluster / f"{dataset_id}.cell.cluster.h5ad").symlink_to(cell_cluster_h5ad)
        (register / f"{dataset_id}_HE_regist.tif").symlink_to(registered_tif)
        (cellcut / f"{dataset_id}.cellbin.gef").symlink_to(cellbin_gef)

        spatial_data = stereoseq(
            staging,
            dataset_id=dataset_id,
            read_square_bin=False,
        )

        image_key = f"{dataset_id}_HE_regist"
        if image_key not in spatial_data.images:
            raise SystemExit(f"STOmics importer did not produce the registered image {image_key!r}.")
        spatial_data.images["raw_image"] = spatial_data.images.pop(image_key)

        if "cells_table" not in spatial_data.tables:
            raise SystemExit("STOmics importer did not produce its cell expression table.")
        table = spatial_data.tables.pop("cells_table")
        if "cellID" not in table.obs:
            raise SystemExit("Imported table has no cellID column; cannot align expression and coordinates.")
        table.obs["cell_ID"] = table.obs["cellID"].astype(str)
        annotation_column = next(
            (column for column in ("cellTypeID", "clusterID") if column in table.obs),
            None,
        )
        if annotation_column:
            table.obs["annotation"] = (
                table.obs[annotation_column].astype("string").fillna("Unannotated").astype(str)
            )
        else:
            table.obs["annotation"] = "Unannotated"
        spatial_data.tables["table"] = table

        if args.crop_bounds:
            cell_count, crop_size = crop_spatial_data(spatial_data, args.crop_bounds)
            print(f"Cropped to {cell_count:,} cells and {crop_size[0]} x {crop_size[1]} pixels.")

        spatial_data.write(output)

    print(f"Viewer-ready SpatialData written to {output}")


if __name__ == "__main__":
    main()