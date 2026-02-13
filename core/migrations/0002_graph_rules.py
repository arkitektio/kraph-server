from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="graph",
            name="rules",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Action-level allow/deny rules evaluated against request context",
            ),
        ),
        migrations.AddField(
            model_name="historicalgraph",
            name="rules",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Action-level allow/deny rules evaluated against request context",
            ),
        ),
    ]
