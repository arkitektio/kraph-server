"""Dead schema columns and the reagent kind die.

None of these was read by anything: `Graph.node_deletion_allowed` /
`edge_deletion_allowed` named a permission for an operation the model forbids;
`Category.schema_hash` was written on every category save and read nowhere
(`Projection.schema_hash` is the stamp that counts); `ports`, `reverse_label`,
`reverse_description`, `source_reagent_roles`, `target_reagent_roles`,
`variable_definitions` and `plate_children` were left from the multi-table
category era and had no reader, no writer and no GraphQL field.

`REAGENT` goes with them. No `kind_type` served it, `NodeSubtype` has no member
for it and no write can mint a reagent instance, so a category or a term of that
kind could only ever be a row nothing reads. The migration refuses to run while
one exists — retire such rows by hand rather than have a migration decide what
they meant.
"""

from django.db import migrations, models


def refuse_reagent_rows(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    stale = Category.objects.filter(kind="REAGENT").count()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM evidence_term WHERE kind = %s", ["REAGENT"])
        (terms,) = cursor.fetchone()
    if stale or terms:
        raise RuntimeError(f"{stale} category row(s) and {terms} term row(s) of kind REAGENT exist. Nothing can draw or claim a reagent; retire these rows deliberately before migrating.")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_every_claim_has_a_time_of_observation"),
        ("evidence", "0015_the_log_is_readable"),
    ]

    operations = [
        migrations.RunPython(refuse_reagent_rows, migrations.RunPython.noop),
        migrations.DeleteModel(
            name="ReagentCategory",
        ),
        migrations.RemoveField(
            model_name="category",
            name="plate_children",
        ),
        migrations.RemoveField(
            model_name="category",
            name="ports",
        ),
        migrations.RemoveField(
            model_name="category",
            name="reverse_description",
        ),
        migrations.RemoveField(
            model_name="category",
            name="reverse_label",
        ),
        migrations.RemoveField(
            model_name="category",
            name="schema_hash",
        ),
        migrations.RemoveField(
            model_name="category",
            name="source_reagent_roles",
        ),
        migrations.RemoveField(
            model_name="category",
            name="target_reagent_roles",
        ),
        migrations.RemoveField(
            model_name="category",
            name="variable_definitions",
        ),
        migrations.RemoveField(
            model_name="graph",
            name="edge_deletion_allowed",
        ),
        migrations.RemoveField(
            model_name="graph",
            name="node_deletion_allowed",
        ),
        migrations.RemoveField(
            model_name="historicalgraph",
            name="edge_deletion_allowed",
        ),
        migrations.RemoveField(
            model_name="historicalgraph",
            name="node_deletion_allowed",
        ),
        migrations.AlterField(
            model_name="category",
            name="instance_kind",
            field=models.CharField(blank=True, help_text="What an instance of this class represents (e.g. a LOT, an object, etc.). Entity categories only", max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name="category",
            name="kind",
            field=models.CharField(
                choices=[("ENTITY", "Entity"), ("NATURAL_EVENT", "Natural Event"), ("PROTOCOL_EVENT", "Protocol Event"), ("MEASUREMENT", "Measurement"), ("RELATION", "Relation"), ("STRUCTURE_RELATION", "Structure Relation")],
                help_text="Which kind of category this is, and therefore which of the kind-specific fields below are meaningful",
                max_length=1000,
            ),
        ),
        migrations.AlterField(
            model_name="graphschema",
            name="hash",
            field=models.CharField(db_index=True, default="", help_text="Content hash of `definition`. This is the identity a projected node stamps as its `__schema_version`, so a derived value can be told apart from one computed under an older schema.", max_length=64),
        ),
    ]
