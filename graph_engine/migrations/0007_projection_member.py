"""A vertex stands for an individual, and lists its members (RFC 0018).

`ProjectionMember` holds one row per instance a drawn vertex stands for, so
any member ref addresses the vertex. Every vertex an older projector drew stood
for exactly one instance — itself — so the backfill gives each one that single
member row. The drawing stays droppable: `manage.py reproject` redraws the
components from the sameness claims, and this migration only keeps the
existing drawing addressable until then.

The `vertex` FK must cascade *in the database* too; migration 0008 rewrites it,
because Django only creates the constraint when this migration has finished.
"""

import django.db.models.deletion
from django.db import migrations, models


def one_member_per_vertex(apps, schema_editor) -> None:
    ProjectionVertex = apps.get_model("graph_engine", "ProjectionVertex")
    ProjectionMember = apps.get_model("graph_engine", "ProjectionMember")
    ProjectionMember.objects.bulk_create(
        (ProjectionMember(graph_id=graph_id, vertex_id=vertex_id, ref=ref) for vertex_id, graph_id, ref in ProjectionVertex.objects.values_list("id", "graph_id", "ref").iterator()),
        batch_size=5000,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_every_claim_has_a_time_of_observation"),
        ("graph_engine", "0006_refresh_namespaces"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectionMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ref", models.UUIDField(help_text="An `evidence.Instance` uuid this vertex stands for.")),
                ("graph", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projection_members", to="core.graph")),
                ("vertex", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="members", to="graph_engine.projectionvertex")),
            ],
            options={
                "default_related_name": "projection_members",
                "constraints": [models.UniqueConstraint(fields=("graph", "ref"), name="one_vertex_per_member_per_view")],
            },
        ),
        migrations.RunPython(one_member_per_vertex, migrations.RunPython.noop),
    ]
