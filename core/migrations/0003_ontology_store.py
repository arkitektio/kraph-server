# Generated by Django 4.2.8 on 2024-09-02 16:18

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_expression_store_alter_expression_ontology"),
    ]

    operations = [
        migrations.AddField(
            model_name="ontology",
            name="store",
            field=models.ForeignKey(
                blank=True,
                help_text="The store of the image class",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="core.mediastore",
            ),
        ),
    ]
