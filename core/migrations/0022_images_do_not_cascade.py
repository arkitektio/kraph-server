"""A picture does not take the view with it.

`Graph.image` and `Category.image` cascaded *from* `datalayer.MediaStore`, so
deleting a media row deleted the graph — and by cascade every category, schema
version, asserted-term index row and the whole projection. The evidence-side
twins (`Term.image`, `StructureKind.image`) were already `SET_NULL`.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0021_dead_columns_die"),
        ("datalayer", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="category",
            name="image",
            field=models.ForeignKey(blank=True, help_text="The store of the image if associated with the category", null=True, on_delete=django.db.models.deletion.SET_NULL, to="datalayer.mediastore"),
        ),
        migrations.AlterField(
            model_name="graph",
            name="image",
            field=models.ForeignKey(blank=True, help_text="The store of the image if associated with the category", null=True, on_delete=django.db.models.deletion.SET_NULL, to="datalayer.mediastore"),
        ),
    ]
