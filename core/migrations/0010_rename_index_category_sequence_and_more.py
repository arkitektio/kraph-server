# Generated by Django 4.2.8 on 2025-04-02 13:36

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_alter_category_index"),
    ]

    operations = [
        migrations.RenameField(
            model_name="category",
            old_name="index",
            new_name="sequence",
        ),
        migrations.AddField(
            model_name="graphsequence",
            name="description",
            field=models.CharField(
                help_text="The description of the sequence", max_length=1000, null=True
            ),
        ),
        migrations.AddField(
            model_name="graphsequence",
            name="label",
            field=models.CharField(
                help_text="The label of the sequence", max_length=1000, null=True
            ),
        ),
    ]
