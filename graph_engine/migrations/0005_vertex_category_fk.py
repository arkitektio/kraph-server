"""The database refuses a vertex drawn under a category its graph does not declare.

A composite foreign key — `(graph_id, category_pk)` on the drawn vertex must name a
`core_category` row *of the same graph* — is the write-side half of RFC 0006: the
schema, not just `resolve_categories`, decides what ends up in a graph. Django cannot
express a composite FK, so this is raw SQL; the model keeps its plain
`BigIntegerField` with a docstring pointing here, and the `(graph, category_pk)`
index that serves the FK's cascade lookups is declared on the model (migration 0004).

Semantics the code relies on:

- `ON DELETE CASCADE`: deleting a category deletes the vertices it admitted, and the
  existing vertex FKs on `ProjectionEdge` cascade the touching edges — the drawing is
  derived, `manage.py reproject` re-draws, and the rule that drew a vertex vanishing
  means the vertex has nothing left to be drawn *as*.
- MATCH SIMPLE (the default): a NULL `category_pk` passes. Only rows an older
  projector drew carry NULL; production always writes the admitting category's pk.

The pre-flight DELETE prunes vertices whose category row is already gone — historic
deletions from before the constraint existed. That is derived state: the claims are
untouched and a reproject re-draws whatever a current category still admits.

The edge FKs must cascade *in the database* too. Django spells `on_delete=CASCADE`
in Python (the deletion collector), leaving the actual constraints NO ACTION — fine
while every delete went through the ORM, but the category FK above deletes vertices
at the SQL level, where only a SQL-level cascade can take the touching edges. The DO
block rewrites the two edge-endpoint constraints (found by column — Django's names
are hashed) to `ON DELETE CASCADE`, keeping them deferrable as Django made them.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0004_alter_projectionvertex_category_pk_and_more"),
        ("core", "0012_category_category_graph_and_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DELETE FROM graph_engine_projectionvertex v
                 WHERE v.category_pk IS NOT NULL
                   AND NOT EXISTS (
                        SELECT 1 FROM core_category c
                         WHERE c.id = v.category_pk AND c.graph_id = v.graph_id
                   );

                ALTER TABLE graph_engine_projectionvertex
                  ADD CONSTRAINT projectionvertex_category_in_graph
                  FOREIGN KEY (graph_id, category_pk)
                  REFERENCES core_category (graph_id, id)
                  ON DELETE CASCADE
                  NOT VALID;

                ALTER TABLE graph_engine_projectionvertex
                  VALIDATE CONSTRAINT projectionvertex_category_in_graph;

                DO $$
                DECLARE
                  cname text;
                  col text;
                BEGIN
                  FOREACH col IN ARRAY ARRAY['source_id', 'target_id'] LOOP
                    SELECT conname INTO STRICT cname
                      FROM pg_constraint
                     WHERE conrelid = 'graph_engine_projectionedge'::regclass
                       AND contype = 'f'
                       AND confrelid = 'graph_engine_projectionvertex'::regclass
                       AND conkey = ARRAY[(
                            SELECT attnum FROM pg_attribute
                             WHERE attrelid = 'graph_engine_projectionedge'::regclass
                               AND attname = col
                       )];
                    EXECUTE format('ALTER TABLE graph_engine_projectionedge DROP CONSTRAINT %I', cname);
                    EXECUTE format(
                      'ALTER TABLE graph_engine_projectionedge ADD CONSTRAINT %I '
                      'FOREIGN KEY (%I) REFERENCES graph_engine_projectionvertex (id) '
                      'ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED',
                      cname, col
                    );
                  END LOOP;
                END $$;
            """,
            reverse_sql="""
                ALTER TABLE graph_engine_projectionvertex
                  DROP CONSTRAINT IF EXISTS projectionvertex_category_in_graph;
            """,
        ),
    ]
