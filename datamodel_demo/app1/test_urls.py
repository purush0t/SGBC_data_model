from django.urls import path

from .views import (
    spatial_coordinates,
    spatial_datasets,
    spatial_expression,
    spatial_image,
    spatial_mask,
    spatial_metadata,
)


urlpatterns = [
    path("api/spatial/", spatial_datasets),
    path("api/spatial/<slug:dataset_id>/metadata/", spatial_metadata),
    path("api/spatial/<slug:dataset_id>/coordinates/", spatial_coordinates),
    path("api/spatial/<slug:dataset_id>/expression/", spatial_expression),
    path("api/spatial/<slug:dataset_id>/image/", spatial_image),
    path("api/spatial/<slug:dataset_id>/mask/", spatial_mask),
]