"""`Graph.created_at`: when the view was created.

The column is added empty, filled from the graph's own history (the earliest
row simple_history recorded for it — the `+` row, when there is one), and only
then given its database default. Adding it with the default in one step would
stamp every existing graph with the time of this migration, which reads as
"made today" in a member's feed. A graph whose history records nothing keeps a
null: unknown is the truth for it.

The column is nullable and the database assigns it, so the previous release,
which knows nothing of it, still runs on the migrated schema and still stamps
the graphs it creates.
"""

import django.db.models.functions.datetime
from django.db import migrations, models
from django.db.models import Min, OuterRef, Subquery

HELP = (
    "When the view was created. Assigned by the database, so a release that predates "
    "the column still stamps the graphs it creates. Null for a graph made before the "
    "column existed whose creation the history does not record."
)


def backfill_from_history(apps, schema_editor):
    Graph = apps.get_model("core", "Graph")
    HistoricalGraph = apps.get_model("core", "HistoricalGraph")
    first_recorded = (
        HistoricalGraph.objects.filter(id=OuterRef("pk"))
        .values("id")
        .annotate(first=Min("history_date"))
        .values("first")
    )
    Graph.objects.filter(created_at__isnull=True).update(created_at=Subquery(first_recorded))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_graphpairsquery_structurecategory_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="graph",
            name="created_at",
            field=models.DateTimeField(blank=True, help_text=HELP, null=True),
        ),
        migrations.AddField(
            model_name="historicalgraph",
            name="created_at",
            field=models.DateTimeField(blank=True, help_text=HELP, null=True),
        ),
        migrations.RunPython(backfill_from_history, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="graph",
            name="created_at",
            field=models.DateTimeField(blank=True, db_default=django.db.models.functions.datetime.Now(), help_text=HELP, null=True),
        ),
        migrations.AlterField(
            model_name="historicalgraph",
            name="created_at",
            field=models.DateTimeField(blank=True, db_default=django.db.models.functions.datetime.Now(), help_text=HELP, null=True),
        ),
    ]
