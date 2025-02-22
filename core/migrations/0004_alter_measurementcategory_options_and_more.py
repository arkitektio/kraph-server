# Generated by Django 4.2.8 on 2025-02-22 12:56

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_alter_expression_ontology"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="measurementcategory",
            options={"default_related_name": "edge_categories"},
        ),
        migrations.AlterModelOptions(
            name="relationcategory",
            options={"default_related_name": "relation_categories"},
        ),
        migrations.CreateModel(
            name="ScatterPlot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="The name of the scatter plot", max_length=1000
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        help_text="The description of the scatter plot",
                        max_length=1000,
                        null=True,
                    ),
                ),
                (
                    "id_column",
                    models.CharField(
                        help_text="The column that assigns the row_id (could be an edge, a node, etc.)",
                        max_length=1000,
                    ),
                ),
                (
                    "x_column",
                    models.CharField(
                        help_text="The column that assigns the x value",
                        max_length=1000,
                        null=True,
                    ),
                ),
                (
                    "y_column",
                    models.CharField(
                        help_text="The column that assigns the y value",
                        max_length=1000,
                        null=True,
                    ),
                ),
                (
                    "color_column",
                    models.CharField(
                        help_text="The column that assigns the color value",
                        max_length=1000,
                        null=True,
                    ),
                ),
                (
                    "size_column",
                    models.CharField(
                        help_text="The column that assigns the size value",
                        max_length=1000,
                        null=True,
                    ),
                ),
                (
                    "shape_column",
                    models.CharField(
                        help_text="The column that assigns the shape value",
                        max_length=1000,
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "query",
                    models.ForeignKey(
                        help_text="The query this scatter plot was trained on",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scatter_plots",
                        to="core.graphquery",
                    ),
                ),
            ],
        ),
    ]
