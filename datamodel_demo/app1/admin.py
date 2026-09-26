from django.contrib import admin
from django.apps import apps
from unfold.admin import ModelAdmin
from .models import *

class InformativeModelAdmin(ModelAdmin):
	"""Choose useful columns for generated models without per-model classes."""

class InformativeModelAdmin(admin.ModelAdmin):
	"""Choose useful columns for generated models without per-model classes."""

	preferred_fields = (
		"code",
		"name",
		"identifier",
		"parent",
		"status",
		"direction",
		"version",
		"created_at",
	)

	def get_list_display(self, request):
		field_names = {field.name for field in self.model._meta.get_fields()}
		display = []

		for field_name in self.preferred_fields:
			if field_name not in field_names:
				continue
			display.append(f"display_{field_name}")

		if not display:
			display.append("display_id")

		return tuple(display)

	@staticmethod
	def _related_label(value):
		if value is None:
			return "-"
		for field_name in ("code", "name", "identifier"):
			label = getattr(value, field_name, None)
			if label:
				return label
		return str(value)

	@admin.display(description="Code", ordering="code")
	def display_code(self, obj):
		return obj.code

	@admin.display(description="Name", ordering="name")
	def display_name(self, obj):
		return obj.name

	@admin.display(description="Identifier", ordering="identifier")
	def display_identifier(self, obj):
		return obj.identifier

	@admin.display(description="Parent", ordering="parent")
	def display_parent(self, obj):
		return self._related_label(obj.parent)

	@admin.display(description="Status", ordering="status")
	def display_status(self, obj):
		return obj.status

	@admin.display(description="Direction", ordering="direction")
	def display_direction(self, obj):
		return obj.direction

	@admin.display(description="Version", ordering="version")
	def display_version(self, obj):
		return obj.version

	@admin.display(description="Created", ordering="created_at")
	def display_created_at(self, obj):
		return obj.created_at

	@admin.display(description="ID", ordering="id")
	def display_id(self, obj):
		return obj.pk


for model in apps.get_app_config("app1").get_models():
	admin.site.register(model, InformativeModelAdmin)
