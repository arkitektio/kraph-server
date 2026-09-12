"""The log is readable (RFC 0020).

Two indexes for the two ways the log is now read: `changes(afterSeq:)` walks one
organization's assertions in `seq` order, and `assertions(appIds:)` lists what
one tool wrote. No column changes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authentikate", "0006_alter_app_identifier_alter_release_unique_together"),
        ("evidence", "0014_negative_sameness"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="assertion",
            index=models.Index(fields=["organization", "seq"], name="evidence_as_organiz_3c5519_idx"),
        ),
        migrations.AddIndex(
            model_name="assertion",
            index=models.Index(fields=["organization", "app_id"], name="evidence_as_organiz_100a40_idx"),
        ),
    ]
