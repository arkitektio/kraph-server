# Generated by Django 4.2.8 on 2025-03-30 12:33

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="naturaleventcategory",
            old_name="source_definitions",
            new_name="source_entity_roles",
        ),
        migrations.RenameField(
            model_name="naturaleventcategory",
            old_name="target_definitions",
            new_name="target_entity_roles",
        ),
    ]
