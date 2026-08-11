"""Remove structure and metric categories from the category hierarchy.

Hand-ordered. The autodetector split this into two migrations that drop the MTI
pointer column before re-pointing the materialized-edge foreign keys that
reference it, which Postgres refuses:

    cannot drop column nodecategory_ptr_id of table core_structurecategory
    because other objects depend on it

So the edges move to `evidence.StructureKind` first, and only then do the models
go. `DeleteModel` on the MTI child also cleans up its parent rows, which is why
the deletes come last and metric before structure — `MetricCategory` cascades
from `StructureCategory`.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_alter_graphschema_unique_together"),
        ("evidence", "0001_initial"),
    ]

    operations = [
        # 1. Re-point the materialized edges. Dropped and re-added rather than
        #    altered: the old columns are bigint keys into an MTI child table and
        #    the new ones are uuids, and Postgres will not cast between them
        #    ("cannot cast type bigint to uuid"). The rows are derived anyway —
        #    `re_materialize_*` rebuilds them — so nothing is lost.
        migrations.RemoveField(model_name="materializedstructurerelationedge", name="source"),
        migrations.RemoveField(model_name="materializedstructurerelationedge", name="target"),
        migrations.RemoveField(model_name="materializedmeasurementedge", name="source"),
        migrations.AddField(
            model_name="materializedstructurerelationedge",
            name="source",
            field=models.ForeignKey(
                default=None,
                help_text="The source structure kind of the edge",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materialized_structure_relation_edges_as_source",
                to="evidence.structurekind",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="materializedstructurerelationedge",
            name="target",
            field=models.ForeignKey(
                default=None,
                help_text="The target structure kind of the edge",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materialized_structure_relation_edges_as_target",
                to="evidence.structurekind",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="materializedmeasurementedge",
            name="source",
            field=models.ForeignKey(
                default=None,
                help_text="The source structure kind of the edge",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materialized_measurement_edges_as_source",
                to="evidence.structurekind",
            ),
            preserve_default=False,
        ),
        # 2. Now nothing points at them.
        migrations.RemoveField(model_name="metriccategory", name="structure_category"),
        migrations.RemoveField(model_name="metriccategory", name="nodecategory_ptr"),
        migrations.RemoveField(model_name="structurecategory", name="nodecategory_ptr"),
        migrations.DeleteModel(name="MetricCategory"),
        migrations.DeleteModel(name="StructureCategory"),
    ]
