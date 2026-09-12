"""A vertex's label rows go with it at the SQL level, and the namespaces come back (RFC 0019).

The FK rewrite is the one migrations 0005 and 0008 made for edges and members:
the `projectionlabel_last_label_deletes_vertex` trigger deletes vertices *in
the database*, where Django's Python-side `on_delete=CASCADE` never runs. Its
own migration because Django creates the constraint only when 0009 has
finished.

The namespaces 0009 dropped are rebuilt here from the new DDL — the vertex
views join the label table now — exactly as migration 0006 built them the
first time.
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
            sys.stderr.write(f"graph #{graph.pk}: no namespace built — {error}\n")


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0009_projection_label"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DO $$
                DECLARE
                  cname text;
                BEGIN
                  SELECT conname INTO STRICT cname
                    FROM pg_constraint
                   WHERE conrelid = 'graph_engine_projectionlabel'::regclass
                     AND contype = 'f'
                     AND confrelid = 'graph_engine_projectionvertex'::regclass
                     AND conkey = ARRAY[(
                          SELECT attnum FROM pg_attribute
                           WHERE attrelid = 'graph_engine_projectionlabel'::regclass
                             AND attname = 'vertex_id'
                     )];
                  EXECUTE format('ALTER TABLE graph_engine_projectionlabel DROP CONSTRAINT %I', cname);
                  EXECUTE format(
                    'ALTER TABLE graph_engine_projectionlabel ADD CONSTRAINT %I '
                    'FOREIGN KEY (vertex_id) REFERENCES graph_engine_projectionvertex (id) '
                    'ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED',
                    cname
                  );
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(build_namespaces, migrations.RunPython.noop),
    ]
