from __future__ import annotations

from django.contrib import admin

from kb.models import Chunk, ChunkConfig, LLMConfig, Resource, Secret


@admin.register(Secret)
class SecretAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("title", "date_created")
    search_fields = ("title",)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("url", "resource_type", "date_created")
    list_filter = ("resource_type",)
    search_fields = ("url",)


@admin.register(ChunkConfig)
class ChunkConfigAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "date_created")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("resource", "order", "date_created")
    list_filter = ("resource",)


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "model_name", "is_default", "date_created")
    list_filter = ("is_default",)
