"""What the drawing tables enforce in the database, where Django's Python-side cascades never run.

Hand-written, so re-add it whenever the history is regenerated: ``makemigrations`` emits
none of this.

- **A vertex takes its edges, members and labels with it** at the SQL level. The
  ``projectionlabel_last_label_deletes_vertex`` trigger deletes vertices *in the database*,
  so the FKs onto ``graph_engine_projectionvertex`` are rewritten ``ON DELETE CASCADE``.
- **A vertex is drawn only under a category its graph declares** (RFC 0006): a composite FK
  ``(graph, category_pk) → core_category(graph, id)``, so the database refuses a label for a
  category of another graph, and a category delete cascades its labels.
- **A vertex whose last label went is gone** (RFC 0019): a vertex exists only as drawn under
  some category.
"""

from django.db import migrations

#: (table, column, constraint) of the FKs onto a vertex: Django names them deterministically.
VERTEX_FKS = (
    ("graph_engine_projectionedge", "source_id", "graph_engine_project_source_id_3587cad1_fk_graph_eng"),
    ("graph_engine_projectionedge", "target_id", "graph_engine_project_target_id_1edc892d_fk_graph_eng"),
    ("graph_engine_projectionlabel", "vertex_id", "graph_engine_project_vertex_id_a8f045f9_fk_graph_eng"),
    ("graph_engine_projectionmember", "vertex_id", "graph_engine_project_vertex_id_baa8dd72_fk_graph_eng"),
)


def _cascade(table: str, column: str, name: str) -> str:
    return f"""
ALTER TABLE {table} DROP CONSTRAINT {name};
ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column})
    REFERENCES graph_engine_projectionvertex (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
"""


def _plain(table: str, column: str, name: str) -> str:
    return f"""
ALTER TABLE {table} DROP CONSTRAINT {name};
ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column})
    REFERENCES graph_engine_projectionvertex (id) DEFERRABLE INITIALLY DEFERRED;
"""


CATEGORY_IN_GRAPH = """
ALTER TABLE graph_engine_projectionlabel ADD CONSTRAINT projectionlabel_category_in_graph
    FOREIGN KEY (graph_id, category_pk) REFERENCES core_category (graph_id, id) ON DELETE CASCADE;
"""

LAST_LABEL = """
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
"""


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0001_initial"),
        ("core", "0002_initial"),
    ]

    operations = [
        *[migrations.RunSQL(sql=_cascade(*fk), reverse_sql=_plain(*fk)) for fk in VERTEX_FKS],
        migrations.RunSQL(sql=CATEGORY_IN_GRAPH, reverse_sql="ALTER TABLE graph_engine_projectionlabel DROP CONSTRAINT projectionlabel_category_in_graph;"),
        migrations.RunSQL(
            sql=LAST_LABEL,
            reverse_sql="DROP TRIGGER IF EXISTS projectionlabel_last_label_deletes_vertex ON graph_engine_projectionlabel; DROP FUNCTION IF EXISTS graph_engine_delete_unlabelled_vertex();",
        ),
    ]
