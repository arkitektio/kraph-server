"""One `Projection` row per existing graph.

Existing drawings are assumed current — they were drawn synchronously on every
write, and `manage.py reproject` is the remedy if one is not — so they start
`CONSISTENT`, with `derived_through_seq` at the organization's current log head
and `schema_hash` at the active schema's hash. A graph with no assertions in its
organization gets 0, which the cursor reads as "nothing to be behind on".
"""

from django.db import migrations
from django.db.models import Max


def forwards(apps, schema_editor):
    Graph = apps.get_model("core", "Graph")
    GraphSchema = apps.get_model("core", "GraphSchema")
    Assertion = apps.get_model("evidence", "Assertion")
    Projection = apps.get_model("graph_engine", "Projection")

    # `_default_manager`: historical models carry no custom managers, and the
    # evidence models' default manager is `all_objects` — deliberately, since a
    # migration is the one caller that must see every tenant.
    heads = {row["organization"]: int(row["top"] or 0) for row in Assertion._default_manager.values("organization").annotate(top=Max("seq"))}
    for graph in Graph._default_manager.all():
        active = GraphSchema._default_manager.filter(graph=graph, is_active=True).first()
        Projection._default_manager.get_or_create(
            graph=graph,
            defaults={
                "kind": "age",
                "status": "consistent",
                "derived_through_seq": heads.get(graph.organization_id, 0),
                "schema_hash": active.hash if active is not None else None,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0001_projection"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
