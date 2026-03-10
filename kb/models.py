from django.db import models
from kb.services.llm import LLMProvider


class TextExtractionConfig(models.Model):
    title: models.CharField = models.CharField(max_length=255, unique=True)
    details: models.JSONField = models.JSONField(default=dict)
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Secret(models.Model):
    title: models.CharField = models.CharField(max_length=255, unique=True)
    value: models.TextField = models.TextField()
    text_extraction_config: models.ForeignKey = models.ForeignKey(
        TextExtractionConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secrets",
    )
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class Resource(models.Model):
    class ResourceType(models.TextChoices):
        PAPER = "paper", "Paper"
        BLOG_POST = "blog_post", "Blog Post"

    url: models.URLField = models.URLField(unique=True)
    resource_type: models.CharField = models.CharField(
        max_length=20, choices=ResourceType.choices
    )
    title: models.CharField = models.CharField(max_length=255, blank=True, default="")
    extracted_text: models.TextField = models.TextField(blank=True, default="")
    summary: models.TextField = models.TextField(blank=True, default="")
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return f"{self.get_resource_type_display()}: {self.url}"


class ChunkConfig(models.Model):
    name: models.CharField = models.CharField(max_length=255, unique=True)
    details: models.JSONField = models.JSONField(default=dict)
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Chunk(models.Model):
    text: models.TextField = models.TextField()
    order: models.PositiveIntegerField = models.PositiveIntegerField()
    resource: models.ForeignKey = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="chunks"
    )
    chunk_config: models.ForeignKey = models.ForeignKey(
        ChunkConfig, on_delete=models.CASCADE, related_name="chunks"
    )
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["resource", "order"]
        unique_together = [("resource", "order")]

    def __str__(self) -> str:
        return f"Chunk {self.order} of Resource {self.resource_id}"


class LLMConfig(models.Model):
    name: models.CharField = models.CharField(max_length=255, unique=True)
    model_name: models.CharField = models.CharField(max_length=255)
    provider: models.CharField = models.CharField(
        max_length=255,
        choices=[(tag.value, tag.name) for tag in LLMProvider],
        default=LLMProvider.OPENAI.value,
    )
    is_default: models.BooleanField = models.BooleanField(default=False)
    secret: models.ForeignKey = models.ForeignKey(
        Secret,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="llm_configs",
    )
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.model_name})"


class EmbeddingModelConfig(models.Model):
    model_name: models.CharField = models.CharField(max_length=255)
    model_provider: models.CharField = models.CharField(max_length=255)
    is_active: models.BooleanField = models.BooleanField(default=False)
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    date_updated: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "date_created"]

    def __str__(self) -> str:
        return f"{self.model_name} ({self.model_provider})"


class ResourceChat(models.Model):
    resource: models.ForeignKey = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="resource_chats"
    )
    chat_id: models.IntegerField = models.IntegerField(unique=True)
    date_created: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return f"Chat {self.chat_id} for Resource {self.resource_id}"


class Reference(models.Model):
    resource = models.ForeignKey(
        Resource, on_delete=models.CASCADE, related_name="references"
    )
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return f"Reference for Resource {self.resource_id}"
