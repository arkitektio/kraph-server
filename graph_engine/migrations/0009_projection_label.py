"""A vertex is drawn under every category that admits it (RFC 0019).

`label` and `category_pk` leave `ProjectionVertex` for `ProjectionLabel`, one
row per (vertex, category). Every vertex an older projector drew carried
exactly one label, so the copy gives each one that single label row, and the
drawing stays addressable until `manage.py reproject` redraws it with the
union its categories now admit.

Three things move with the columns:

- **The composite foreign key** `(graph_id, category_pk) REFERENCES
  core_category (graph_id, id) ON DELETE CASCADE` (migration 0005, RFC 0006)
  is re-declared on the label table — same NOT VALID + VALIDATE spelling, same
  MATCH SIMPLE semantics for NULL. Dropping the vertex column drops the old
  constraint with it.
- **A vertex with no label is deleted.** A category delete cascades its label
  rows below the ORM; the vertex they were on is still there, drawn under
  nothing, which is a node the view does not admit. The
  `projectionlabel_last_label_deletes_vertex` trigger takes it, and the
  existing SQL-level cascades (0005, 0008) take its edges and members. The
  writer inserts new labels before deleting stale ones so a redraw never
  passes through an empty set.
- **The namespaces.** Every per-graph vertex view selects `label` and
  `category_pk` from the vertex table, so Postgres refuses to drop the columns
  while they exist. They are dropped here and rebuilt by migration 0010 from
  the new DDL — the namespace is a derived artifact (RFC 0006), and this is the
  same drop-and-recreate `refresh_namespace` does on every category write.

The `vertex` FK on the label table must cascade *in the database* too;
migration 0010 rewrites it, because Django only creates the constraint when
this migration has finished.
"""

import django.db.models.deletion
from django.db import migrations, models


def drop_namespaces(apps, schema_editor) -> None:
    Graph = apps.get_model("core", "Graph")
    with schema_editor.connection.cursor() as cursor:
        for age_name in Graph.objects.values_list("age_name", flat=True).order_by("id"):
            cursor.execute(f'DROP SCHEMA IF EXISTS "{age_name}" CASCADE')


def one_label_per_vertex(apps, schema_editor) -> None:
    ProjectionVertex = apps.get_model("graph_engine", "ProjectionVertex")
    ProjectionLabel = apps.get_model("graph_engine", "ProjectionLabel")
    ProjectionLabel.objects.bulk_create(
        (ProjectionLabel(graph_id=graph_id, vertex_id=vertex_id, label=label, category_pk=category_pk) for vertex_id, graph_id, label, category_pk in ProjectionVertex.objects.values_list("id", "graph_id", "label", "category_pk").iterator()),
        batch_size=5000,
    )


def the_label_back(apps, schema_editor) -> None:
    """Reverse: the lowest-pk label of each vertex becomes its one label."""
    ProjectionVertex = apps.get_model("graph_engine", "ProjectionVertex")
    ProjectionLabel = apps.get_model("graph_engine", "ProjectionLabel")
    for vertex_id, label, category_pk in ProjectionLabel.objects.order_by("vertex_id", "-id").values_list("vertex_id", "label", "category_pk").iterator():
        ProjectionVertex.objects.filter(id=vertex_id).update(label=label, category_pk=category_pk)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_every_claim_has_a_time_of_observation"),
        ("graph_engine", "0008_member_vertex_cascade"),
    ]

    operations = [
        migrations.RunPython(drop_namespaces, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ProjectionLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(help_text="The view's word for the category (`Category.age_name`).", max_length=1000)),
                ("category_pk", models.BigIntegerField(blank=True, help_text="The category row that admitted this node; composite FK to `core_category (graph_id, id)` in SQL (migration 0009). RFC 0006, RFC 0019.", null=True)),
                ("graph", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projection_labels", to="core.graph")),
                ("vertex", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="labels", to="graph_engine.projectionvertex")),
            ],
            options={
                "default_related_name": "projection_labels",
            },
        ),
        migrations.AddIndex(
            model_name="projectionlabel",
            index=models.Index(fields=["graph", "label"], name="graph_engin_graph_i_111cba_idx"),
        ),
        migrations.AddIndex(
            model_name="projectionlabel",
            index=models.Index(fields=["graph", "category_pk"], name="graph_engin_graph_i_f5e02d_idx"),
        ),
        migrations.AddConstraint(
            model_name="projectionlabel",
            constraint=models.UniqueConstraint(fields=("vertex", "category_pk"), name="one_label_per_category_per_vertex"),
        ),
        migrations.RunPython(one_label_per_vertex, the_label_back),
        migrations.RemoveIndex(
            model_name="projectionvertex",
            name="graph_engin_graph_i_d01b3a_idx",
        ),
        migrations.RemoveIndex(
            model_name="projectionvertex",
            name="graph_engin_graph_i_f09928_idx",
        ),
        migrations.RunSQL(
            sql="ALTER TABLE graph_engine_projectionvertex DROP CONSTRAINT IF EXISTS projectionvertex_category_in_graph;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="projectionvertex",
            name="category_pk",
        ),
        migrations.RemoveField(
            model_name="projectionvertex",
            name="label",
        ),
        migrations.RunSQL(
            sql="""
                DELETE FROM graph_engine_projectionlabel l
                 WHERE l.category_pk IS NOT NULL
                   AND NOT EXISTS (
                        SELECT 1 FROM core_category c
                         WHERE c.id = l.category_pk AND c.graph_id = l.graph_id
                   );

                ALTER TABLE graph_engine_projectionlabel
                  ADD CONSTRAINT projectionlabel_category_in_graph
                  FOREIGN KEY (graph_id, category_pk)
                  REFERENCES core_category (graph_id, id)
                  ON DELETE CASCADE
                  NOT VALID;

                ALTER TABLE graph_engine_projectionlabel
                  VALIDATE CONSTRAINT projectionlabel_category_in_graph;

                CREATE OR REPLACE FUNCTION graph_engine_delete_unlabelled_vertex() RETURNS trigger AS $$
                BEGIN
                  DELETE FROM graph_engine_projectionvertex v
                   WHERE v.id = OLD.vertex_id
                     AND NOT EXISTS (
                          SELECT 1 FROM graph_engine_projectionlabel l WHERE l.vertex_id = v.id
                     );
                  RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;

                CREATE TRIGGER projectionlabel_last_label_deletes_vertex
                  AFTER DELETE ON graph_engine_projectionlabel
                  FOR EACH ROW EXECUTE FUNCTION graph_engine_delete_unlabelled_vertex();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS projectionlabel_last_label_deletes_vertex ON graph_engine_projectionlabel;
                DROP FUNCTION IF EXISTS graph_engine_delete_unlabelled_vertex();
                ALTER TABLE graph_engine_projectionlabel
                  DROP CONSTRAINT IF EXISTS projectionlabel_category_in_graph;
            """,
        ),
    ]
