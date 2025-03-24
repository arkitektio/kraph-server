# Generated by Django 4.2.8 on 2025-03-20 19:13

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_remove_graph_active_for_remove_graphquery_active_for_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="graphquery",
            name="relevant_for",
            field=models.ManyToManyField(
                help_text="The expression that this query should be mostly used for",
                related_name="relevant_graph_queries",
                to="core.expression",
            ),
        ),
        migrations.AddField(
            model_name="nodequery",
            name="relevant_for",
            field=models.ManyToManyField(
                help_text="The entities that this query should be mostly used for",
                related_name="relevant_node_queries",
                to="core.expression",
            ),
        ),
    ]
