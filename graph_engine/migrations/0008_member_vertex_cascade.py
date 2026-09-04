"""A vertex's member rows go with it at the SQL level (RFC 0018).

The reason is the one migration 0005 gives for the edge FKs: the composite
category FK deletes vertices *in the database* when a category goes, and
Django's Python-side `on_delete=CASCADE` never runs there — so without this
the member rows block the delete with an IntegrityError. The DO block rewrites
the constraint Django created in 0007 (found by column — the name is hashed)
to `ON DELETE CASCADE`, keeping it deferrable as Django made it. Its own
migration because Django creates the constraint only when 0007 has finished.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("graph_engine", "0007_projection_member"),
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
                   WHERE conrelid = 'graph_engine_projectionmember'::regclass
                     AND contype = 'f'
                     AND confrelid = 'graph_engine_projectionvertex'::regclass
                     AND conkey = ARRAY[(
                          SELECT attnum FROM pg_attribute
                           WHERE attrelid = 'graph_engine_projectionmember'::regclass
                             AND attname = 'vertex_id'
                     )];
                  EXECUTE format('ALTER TABLE graph_engine_projectionmember DROP CONSTRAINT %I', cname);
                  EXECUTE format(
                    'ALTER TABLE graph_engine_projectionmember ADD CONSTRAINT %I '
                    'FOREIGN KEY (vertex_id) REFERENCES graph_engine_projectionvertex (id) '
                    'ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED',
                    cname
                  );
                END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
