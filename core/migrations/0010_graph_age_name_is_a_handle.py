"""`Graph.age_name` becomes an opaque handle.

It was `{name}_{org_slug}` with a counter, `max_length=1000`, required on
create, and — through `api/context.py` — the public address of a view. It is a
random `g<32 hex>` now, assigned by the model default, never accepted as input,
and never resolved by; see `core.models.new_projection_handle`.

Existing rows keep their handles: renaming a live Apache AGE namespace is a
schema rename plus `ag_catalog` bookkeeping, and nothing needs it — after this
migration nothing resolves a graph by the handle. The only thing that must hold
is the new length ceiling, which is the 63-byte Postgres identifier limit AGE
stores graph names in. A row longer than that would already be broken on the
AGE side (the namespace name was truncated or refused), so refusing the migration
is the honest outcome rather than silently truncating the column.
"""

from django.db import migrations, models

import core.models


def refuse_overlong_handles(apps, schema_editor):
    Graph = apps.get_model("core", "Graph")
    overlong = [(g.pk, g.age_name) for g in Graph.objects.all() if len(g.age_name) > 63]
    if overlong:
        listed = ", ".join(f"#{pk} ({len(name)} chars)" for pk, name in overlong)
        raise RuntimeError(f"{len(overlong)} graph(s) carry an age_name longer than 63 bytes, which Apache AGE cannot have honoured: {listed}. Reproject them under a fresh handle before migrating.")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_dead_models_die"),
    ]

    operations = [
        migrations.RunPython(refuse_overlong_handles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="graph",
            name="age_name",
            field=models.CharField(
                default=core.models.new_projection_handle,
                editable=False,
                help_text="Internal handle of this graph's Apache AGE namespace. Random, assigned at creation, read only through `get_age_name()` by the engine. Not an identifier: a graph is addressed by its primary key. See `new_projection_handle`.",
                max_length=63,
                unique=True,
            ),
        ),
        # `simple_history` keeps a mirror of every `Graph` column; it follows the
        # field, minus the unique constraint a history table cannot carry.
        migrations.AlterField(
            model_name="historicalgraph",
            name="age_name",
            field=models.CharField(
                db_index=True,
                default=core.models.new_projection_handle,
                editable=False,
                help_text="Internal handle of this graph's Apache AGE namespace. Random, assigned at creation, read only through `get_age_name()` by the engine. Not an identifier: a graph is addressed by its primary key. See `new_projection_handle`.",
                max_length=63,
            ),
        ),
    ]
