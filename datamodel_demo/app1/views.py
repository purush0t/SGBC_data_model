"""HTTP views for app1. Schema utilities live in app1.utils."""

from django.contrib import admin
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from math import isfinite

from .models import Activity, ActivityEntity, ActivityInformationRecord, Entity, EntityInformationRecord
from .spatial import MAX_POINTS, SpatialDataError, get_reader, list_datasets


def _timeline_rows(entity_page):
    """Turn prefetched entities into presentation-friendly timeline rows."""
    rows = []
    for entity in entity_page:
        activities = {}
        for link in entity.timeline_links:
            activity = link.activity
            # An entity can occupy more than one port on the same activity.
            activities.setdefault(activity.pk, activity)

        def activity_time(activity):
            sidecar = activity.timeline_sidecars[0] if activity.timeline_sidecars else None
            value = sidecar.started_at if sidecar and sidecar.started_at else activity.created_at
            return value.timestamp()

        ordered = sorted(activities.values(), key=activity_time)
        rows.append({"entity": entity, "activities": ordered})
    return rows


def _timeline_entities():
    """Entity queryset with everything needed to render a timeline lane."""
    entity_sidecars = EntityInformationRecord.objects.order_by("-version", "-recorded_at")
    sidecars = ActivityInformationRecord.objects.select_related(
        "protocol", "operator_agent", "recorded_by_agent"
    ).order_by("-version", "-recorded_at")
    outputs = ActivityEntity.objects.filter(port__direction="output").select_related(
        "entity", "entity__entity_type", "port"
    ).prefetch_related(
        Prefetch("entity__information_records", queryset=entity_sidecars, to_attr="timeline_sidecars")
    ).order_by("sequence_no", "entity__identifier")
    links = ActivityEntity.objects.select_related(
        "activity", "activity__activity_type", "port"
    ).prefetch_related(
        Prefetch("activity__information_records", queryset=sidecars, to_attr="timeline_sidecars"),
        Prefetch("activity__entity_links", queryset=outputs, to_attr="timeline_output_links"),
    ).order_by("activity__created_at")
    return Entity.objects.select_related("entity_type").prefetch_related(
        Prefetch("activity_links", queryset=links, to_attr="timeline_links")
    )


def activity_timeline_dashboard(request):
    """Paginated Unfold dashboard of entity activity swimlanes."""
    query = request.GET.get("q", "").strip()
    entity_type = request.GET.get("entity_type", "").strip()
    if entity_type and not entity_type.isdecimal():
        entity_type = ""

    entities = _timeline_entities().order_by("identifier")

    if query:
        entities = entities.filter(
            Q(identifier__icontains=query)
            | Q(physical_identity__icontains=query)
            | Q(entity_type__name__icontains=query)
            | Q(entity_type__code__icontains=query)
        )
    if entity_type:
        entities = entities.filter(entity_type_id=entity_type)

    page = Paginator(entities, 12).get_page(request.GET.get("page"))
    context = {
        **admin.site.each_context(request),
        "title": "Activity timelines",
        "subtitle": "Physical entities and their subsequent provenance activities",
        "page": page,
        "rows": _timeline_rows(page.object_list),
        "query": query,
        "selected_entity_type": entity_type,
        "entity_types": Entity.objects.values_list(
            "entity_type_id", "entity_type__name"
        ).distinct().order_by("entity_type__name"),
    }
    return render(request, "app1/activity_timeline_dashboard.html", context)


def activity_timeline_lane(request, entity_id):
    """Render one additional lane for progressive provenance exploration."""
    entity = get_object_or_404(_timeline_entities(), pk=entity_id)
    row = _timeline_rows([entity])[0]
    html = render_to_string("app1/_activity_timeline_lane.html", {"row": row}, request=request)
    return HttpResponse(html)


def graph_explorer(request):
    return render(request, "app1/graph_explorer.html")


def graph_data(request):
    """Return the provenance graph in a D3-friendly node/link shape."""
    spatial_registrations = {}
    for record in EntityInformationRecord.objects.order_by("entity_id", "-version", "-recorded_at"):
        if record.entity_id not in spatial_registrations and isinstance((record.metadata or {}).get("spatial_dataset"), dict):
            spatial_registrations[record.entity_id] = True
    nodes = []
    for entity in Entity.objects.select_related("entity_type"):
        nodes.append({"id": f"entity:{entity.pk}", "kind": "entity",
                      "label": entity.identifier, "type": entity.entity_type.code,
                      "type_name": entity.entity_type.name,
                      "annotation": entity.physical_identity or "",
                      "spatial_url": f"/spatial/entity-{entity.pk}/" if entity.pk in spatial_registrations else None})
    for activity in Activity.objects.select_related("activity_type"):
        nodes.append({"id": f"activity:{activity.pk}", "kind": "activity",
                      "label": activity.identifier, "type": activity.activity_type.code,
                      "type_name": activity.activity_type.name})
    links = []
    for edge in ActivityEntity.objects.select_related("activity", "entity", "port"):
        source = f"entity:{edge.entity_id}" if edge.port.direction == "input" else f"activity:{edge.activity_id}"
        target = f"activity:{edge.activity_id}" if edge.port.direction == "input" else f"entity:{edge.entity_id}"
        links.append({"source": source, "target": target, "direction": edge.port.direction,
                      "role": edge.port.name, "sequence": edge.sequence_no})
    return JsonResponse({"nodes": nodes, "links": links})


def spatial_viewer(request, dataset_id="mouse_liver_demo"):
    return render(request, "app1/spatial_viewer.html", {"dataset_id": dataset_id})


def spatial_datasets(request):
    return JsonResponse({"datasets": list_datasets()})


def _spatial_reader(dataset_id):
    try:
        return get_reader(dataset_id)
    except SpatialDataError as error:
        return None, JsonResponse({"error": str(error)}, status=404)


def _spatial_query(request):
    try:
        limit = int(request.GET.get("limit", MAX_POINTS))
    except (TypeError, ValueError):
        raise SpatialDataError("limit must be an integer.")
    bounds = {}
    supplied_bounds = [request.GET.get(name) for name in ("xmin", "xmax", "ymin", "ymax")]
    if any(value is not None for value in supplied_bounds):
        if any(value is None for value in supplied_bounds):
            raise SpatialDataError("xmin, xmax, ymin, and ymax must be supplied together.")
        try:
            bounds = {name: float(value) for name, value in zip(("xmin", "xmax", "ymin", "ymax"), supplied_bounds)}
        except (TypeError, ValueError):
            raise SpatialDataError("Spatial bounds must be numbers.")
        if not all(isfinite(value) for value in bounds.values()):
            raise SpatialDataError("Spatial bounds must be finite.")
        if bounds["xmin"] > bounds["xmax"] or bounds["ymin"] > bounds["ymax"]:
            raise SpatialDataError("Minimum bounds must not exceed maximum bounds.")
    return bounds or None, limit


def spatial_metadata(request, dataset_id):
    reader = _spatial_reader(dataset_id)
    if isinstance(reader, tuple):
        return reader[1]
    try:
        return JsonResponse(reader.get_metadata())
    except SpatialDataError as error:
        return JsonResponse({"error": str(error)}, status=503)


def _spatial_image(request, dataset_id, layer):
    reader = _spatial_reader(dataset_id)
    if isinstance(reader, tuple):
        return reader[1]
    get_image = getattr(reader, f"get_{layer}", None)
    if get_image is None:
        return JsonResponse({"error": f"Layer {layer!r} is unavailable."}, status=404)
    try:
        return HttpResponse(get_image(), content_type="image/png")
    except SpatialDataError as error:
        return JsonResponse({"error": str(error)}, status=503)


def spatial_image(request, dataset_id):
    return _spatial_image(request, dataset_id, "image")


def spatial_mask(request, dataset_id):
    return _spatial_image(request, dataset_id, "mask")


def spatial_coordinates(request, dataset_id):
    reader = _spatial_reader(dataset_id)
    if isinstance(reader, tuple):
        return reader[1]
    try:
        bounds, limit = _spatial_query(request)
        points = reader.get_coordinates(bounds=bounds, limit=limit)
    except SpatialDataError as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse({"points": points, "count": len(points)})


def spatial_expression(request, dataset_id):
    reader = _spatial_reader(dataset_id)
    if isinstance(reader, tuple):
        return reader[1]
    gene = request.GET.get("gene", "").strip()
    overall = request.GET.get("overall") == "true"
    if not gene and not overall:
        return JsonResponse({"error": "gene is required."}, status=400)
    try:
        bounds, limit = _spatial_query(request)
        points = reader.get_overall_expression(bounds=bounds, limit=limit) if overall else reader.get_expression(gene, bounds=bounds, limit=limit)
    except SpatialDataError as error:
        return JsonResponse({"error": str(error)}, status=400)
    values = [point["value"] for point in points]
    scale = points[0].get("scale") if points else None
    if not scale:
        scale = reader.get_metadata().get("expression_scale", "raw counts")
    return JsonResponse({
        "gene": gene or "Overall expression",
        "points": points,
        "count": len(points),
        "scale": scale,
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
    })
