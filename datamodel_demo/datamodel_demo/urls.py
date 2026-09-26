"""
URL configuration for datamodel_demo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from app1.views import (
    activity_timeline_dashboard,
    activity_timeline_lane,
    graph_data,
    graph_explorer,
    spatial_coordinates,
    spatial_datasets,
    spatial_expression,
    spatial_image,
    spatial_mask,
    spatial_metadata,
    spatial_viewer,
)

urlpatterns = [
    path(
        "admin/activity-timelines/",
        admin.site.admin_view(activity_timeline_dashboard),
        name="activity-timelines",
    ),
    path(
        "admin/activity-timelines/lane/<int:entity_id>/",
        admin.site.admin_view(activity_timeline_lane),
        name="activity-timeline-lane",
    ),
    path("admin/", admin.site.urls),
    path("graph/", graph_explorer, name="graph-explorer"),
    path("api/graph/", graph_data, name="graph-data"),
    path("spatial/", spatial_viewer, name="spatial-viewer"),
    path("spatial/<slug:dataset_id>/", spatial_viewer, name="spatial-viewer-dataset"),
    path("api/spatial/", spatial_datasets, name="spatial-datasets"),
    path("api/spatial/<slug:dataset_id>/metadata/", spatial_metadata, name="spatial-metadata"),
    path("api/spatial/<slug:dataset_id>/coordinates/", spatial_coordinates, name="spatial-coordinates"),
    path("api/spatial/<slug:dataset_id>/expression/", spatial_expression, name="spatial-expression"),
    path("api/spatial/<slug:dataset_id>/image/", spatial_image, name="spatial-image"),
    path("api/spatial/<slug:dataset_id>/mask/", spatial_mask, name="spatial-mask"),
]
