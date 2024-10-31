# Generated by Django 4.2.8 on 2024-10-23 14:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_alter_reagentmapping_reagent"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reagentmapping",
            name="reagent",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="used_in",
                to="core.reagent",
            ),
        ),
    ]
