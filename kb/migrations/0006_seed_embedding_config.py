from django.db import migrations


def seed_embedding_config(apps, schema_editor):
    EmbeddingModelConfig = apps.get_model("kb", "EmbeddingModelConfig")
    EmbeddingModelConfig.objects.create(
        model_name="text-embedding-embeddinggemma-300m",
        model_provider="LMStudio",
        is_active=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('kb', '0005_embeddingmodelconfig'),
    ]

    operations = [
        migrations.RunPython(seed_embedding_config),
    ]
