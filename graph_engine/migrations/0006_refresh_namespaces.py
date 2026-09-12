"""Build the namespace for every graph that predates it.

Graphs materialized before RFC 0006 have categories and (possibly) a drawing,
but no per-graph schema and no property graph — those are created by
`refresh_namespace`, which every later category write calls. This RunPython
brings the existing rows up. Idempotent: the refresh is drop-and-recreate.

Uses the historical-model-free path on purpose: `refresh_namespace` reads live
`core.Category` rows through `graph_engine.namespace`, which is exactly what a
`manage.py refresh_namespaces --all` does — this migration is that command run
once, at the moment the feature arrives.
"""

from django.db import migrations


def build_namespaces(apps, schema_editor) -> None:
    import sys

    from core import models as core_models
    from graph_engine.namespace import NamespaceSpecError
    from graph_engine.projection.table import TableProjector

    projector = TableProjector()
    for graph in core_models.Graph.objects.order_by("id"):
        try:
            projector.refresh_namespace(graph)
        except NamespaceSpecError as error:
            # A pre-existing graph whose schema cannot be spelled (an over-long
            # label, an exploding open descriptor) must not block the deploy:
            # it simply has no namespace until repaired, and the repair is
            # `manage.py refresh_namespaces --graph` after fixing the schema.
            sys.stderr.write(f"graph #{graph.pk}: no namespace built — {error}\n")


def drop_namespaces(apps, schema_editor) -> None:
    from core import models as core_models

    for graph in core_models.Graph.objects.order_by("id"):
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{graph.age_name}" CASCADE')


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0005_vertex_category_fk"),
    ]

    operations = [
        migrations.RunPython(build_namespaces, drop_namespaces),
    ]
