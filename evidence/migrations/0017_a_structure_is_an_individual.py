"""A structure is an individual with an external identity (RFC 0023).

It gains the two columns every claim has — `observed_at` (RFC 0015) and
`confidence` (RFC 0016) — so an OBSERVED_AT or CONFIDENCE rule is total over
claim kinds. Existing rows take their assertion's `asserted_at`, the same
default a claim made without a time takes on save. The backfill is the one
UPDATE the append-only guard has to be told about, and says so.
"""

from django.db import migrations, models

BACKFILL = """
SET LOCAL kraph.allow_log_rewrite = 'on';
UPDATE evidence_structure AS s
SET observed_at = a.asserted_at
FROM evidence_assertion AS a
WHERE s.assertion_id = a.id AND s.observed_at IS NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0016_vocabulary_identity_is_immutable"),
    ]

    operations = [
        migrations.AddField(
            model_name="structure",
            name="observed_at",
            field=models.DateTimeField(null=True, help_text="When the datum was observed to exist — world time, like every claim's (RFC 0015, 0023). Equal to the assertion's `asserted_at` when the claimant gave no other."),
        ),
        migrations.AddField(
            model_name="structure",
            name="confidence",
            field=models.FloatField(blank=True, null=True, help_text="How sure the claimant was, 0 to 1. Null means they gave no number — which is not 1.0 and not 0.0: a `CONFIDENCE` rule admits only claims that carry one (RFC 0016)."),
        ),
        migrations.RunSQL(sql=BACKFILL, reverse_sql=migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="structure",
            name="observed_at",
            field=models.DateTimeField(help_text="When the datum was observed to exist — world time, like every claim's (RFC 0015, 0023). Equal to the assertion's `asserted_at` when the claimant gave no other."),
        ),
        migrations.AddConstraint(
            model_name="structure",
            constraint=models.CheckConstraint(condition=models.Q(("confidence__isnull", True)) | models.Q(("confidence__gte", 0.0), ("confidence__lte", 1.0)), name="structure_confidence_in_unit_interval"),
        ),
    ]
