#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$repo_root/datamodel_demo/data/spatial/mouse_liver.zarr"
archive_url="https://s3.embl.de/spatialdata/spatialdata-sandbox/mouse_liver_spatialdata_0.7.1.zip"
archive_sha256="2d2c9caf7281725a29034dfa8038018aa3f209a1b60b44165d1c79d39e9ed894"

if [[ -d "$target" ]]; then
    printf 'Mouse-liver SpatialData already exists at %s\n' "$target"
    exit 0
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT
mkdir -p "$(dirname "$target")"
curl --fail --location --silent --show-error "$archive_url" --output "$temporary_directory/mouse_liver.zip"
printf '%s  %s\n' "$archive_sha256" "$temporary_directory/mouse_liver.zip" | sha256sum --check --status
unzip -q "$temporary_directory/mouse_liver.zip" -d "$temporary_directory"
mv "$temporary_directory/data.zarr" "$target"
printf 'Installed Mouse Liver SpatialData at %s\n' "$target"