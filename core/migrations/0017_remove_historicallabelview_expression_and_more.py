# Generated by Django 4.2.8 on 2024-09-29 15:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_historicalprotocolstep_name_protocolstep_name"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="historicallabelview",
            name="expression",
        ),
        migrations.RemoveField(
            model_name="labelview",
            name="expression",
        ),
        migrations.AddField(
            model_name="acquisitionview",
            name="entity_id",
            field=models.CharField(
                blank=True,
                help_text="The entity that this view is for",
                max_length=1000,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicallabelview",
            name="label",
            field=models.CharField(
                help_text="The label of the entity class", max_length=1000, null=True
            ),
        ),
        migrations.AddField(
            model_name="labelview",
            name="label",
            field=models.CharField(
                help_text="The label of the entity class", max_length=1000, null=True
            ),
        ),
    ]