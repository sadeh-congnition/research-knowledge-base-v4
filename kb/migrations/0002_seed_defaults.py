from django.db import migrations


def seed_default_chunk_config(apps, schema_editor):
    ChunkConfig = apps.get_model("kb", "ChunkConfig")
    ChunkConfig.objects.get_or_create(
        name="chonkie-semantic-default",
        defaults={
            "details": {
                "embedding_model": "text-embedding-embeddinggemma-300m",
                "threshold": 0.7,
                "chunk_size": 512,
                "similarity_window": 3,
                "skip_window": 0,
            }
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_chunk_config, migrations.RunPython.noop),
    ]
