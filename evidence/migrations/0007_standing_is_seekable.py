"""Make `claims.standing()`'s anti-join a seek instead of a scan.

`ClaimCurrent` was indexed on `(organization, target_type, stands)`, but the one
query that reads it hardest — the `NOT IN (retracted)` narrowing inside
`evidence.claims.standing` — filters on `(target_type, stands)` alone. It has no
organization to filter by: `standing()` takes a queryset and a target type, and
the queryset is already scoped. Skipping the index's leading column means the
index cannot be used, so every read on every hot path scanned the table.

This is the index the query actually issues. `target_id` is the third column so
the subquery is answered from the index without touching the heap. The
organization-leading index stays, because the reads that *do* name a tenant
(`claims.current`, `record_current`) are the ones the unique constraint and it
serve.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentikate', '0006_alter_app_identifier_alter_release_unique_together'),
        ('evidence', '0006_entity_identity'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='claimcurrent',
            index=models.Index(fields=['target_type', 'stands', 'target_id'], name='claimcurrent_retracted_idx'),
        ),
    ]
