"""Every claim has a time of observation (RFC 0015).

`Metric.measured_at` was the only world-time column in the log: an instance had
no time it was seen, an event no time it happened, a relation no time it held.
`MEASURED_AT` was therefore a metric-only rule field by necessity, not by design.

This adds `observed_at` to `Instance` and `Link`, backfilled from the assertion's
`asserted_at` — the honest default when nobody said when the world was in that
state, and the default `writer.record_metric` has always applied — and renames
the metric column so the three claim tables share one word for one axis.
`Standing.at` keeps its name: it is when a position took effect.

The backfill is an `UPDATE` on log tables, which `0005_log_is_append_only`
refuses; the migration names the escape hatch, as that migration prescribes,
and only for its own transaction.
"""

from django.db import migrations, models

ALLOW_REWRITE = "SET LOCAL kraph.allow_log_rewrite = 'on';"

BACKFILL = f"""
{ALLOW_REWRITE}
UPDATE evidence_instance AS i
   SET observed_at = a.asserted_at
  FROM evidence_assertion AS a
 WHERE i.assertion_id = a.id AND i.observed_at IS NULL;
UPDATE evidence_link AS l
   SET observed_at = a.asserted_at
  FROM evidence_assertion AS a
 WHERE l.assertion_id = a.id AND l.observed_at IS NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0010_comment_is_append_only"),
    ]

    operations = [
        migrations.RenameField(
            model_name="metric",
            old_name="measured_at",
            new_name="observed_at",
        ),
        migrations.AlterField(
            model_name="metric",
            name="observed_at",
            field=models.DateTimeField(
                db_index=True,
                help_text=(
                    "When the world was observed. The axis a scientist means by 'when'. "
                    "Was `measured_at` until RFC 0015 gave every claim the same column under one name."
                ),
            ),
        ),
        migrations.AddField(
            model_name="instance",
            name="observed_at",
            field=models.DateTimeField(null=True, db_index=True),
        ),
        migrations.AddField(
            model_name="link",
            name="observed_at",
            field=models.DateTimeField(null=True, db_index=True),
        ),
        migrations.RunSQL(sql=BACKFILL, reverse_sql=migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="instance",
            name="observed_at",
            field=models.DateTimeField(
                db_index=True,
                help_text=(
                    "When the world contained this individual — for an event, when it happened; for an entity, "
                    "when it was seen. A point, not an interval: a duration is a metric. Defaults to the assertion's "
                    "`asserted_at` on save (RFC 0015)."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="link",
            name="observed_at",
            field=models.DateTimeField(
                db_index=True,
                help_text=(
                    "When the world was in this state: a relation held, a participation happened, a classification "
                    "applied. Defaults to the assertion's `asserted_at` on save when the claimant gave no other time "
                    "(RFC 0015), so `OBSERVED_AT` rules are total."
                ),
            ),
        ),
        # `State` folds metrics; its help text named the old column.
        migrations.AlterField(
            model_name="state",
            name="first_ts",
            field=models.DateTimeField(blank=True, help_text="observed_at of the earliest contributing metric.", null=True),
        ),
        migrations.AlterField(
            model_name="state",
            name="last_ts",
            field=models.DateTimeField(blank=True, help_text="observed_at of the latest contributing metric.", null=True),
        ),
    ]
