from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0002_database_rules"),
    ]

    operations = [
        migrations.AlterField(
            model_name="metric",
            name="source_uuid",
            field=models.UUIDField(
                blank=True,
                help_text="The uuid `assertMetricValues` recorded this metric under, the producer's or a minted one, or the metric's own in the service that recorded it (mikro's `@mikro/metric`). Null for a metric recorded one at a time. Unique: a batch retried, or an entry of the feed read twice, is recorded once (`evidence/metric_batch.py`).",
                null=True,
                unique=True,
            ),
        ),
    ]
