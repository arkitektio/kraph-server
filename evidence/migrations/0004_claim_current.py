"""Move the cached "does this stand" answer off the log.

`Structure`, `Metric` and `Link` each carried a `stands` boolean that
`writer.claim` flipped in the same transaction as the claim. That made three log
tables mutable — the write path's own docstring promised "there is no update and
no delete" four lines above the `UPDATE` — and it is what stopped
`REVOKE UPDATE` from being possible at all.

The answer still has to be indexed, because `metrics_for`,
`active_metrics_for_structures` and `informs_links_for` all narrow the
highest-churn table in the system by it. So it moves to `ClaimCurrent`, a
projection with the same index and the same query cost, and the log tables become
immutable.

**Order matters here.** Create the projection, fold it from the claim log, and
only then drop the columns — the reverse leaves an install with no answer at all
between two operations of the same migration.

The fold reads `Claim`, not the columns being dropped. Where the two disagree the
log wins, which is the point: nothing ever asserted that the cache and the fold
agreed, and this is the first time they are reconciled.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.db import migrations, models


def fold_claim_current(apps, schema_editor):
    """Rebuild every cached answer from the claim log."""
    Claim = apps.get_model("evidence", "Claim")
    ClaimCurrent = apps.get_model("evidence", "ClaimCurrent")

    # Newest first, by the total order `0002` added. The first claim seen for a
    # target is the one that wins; the rest are history. Same rule as
    # `evidence.claims.stands_for`, restated here because a migration must not
    # import application code that will keep changing under it.
    winners: dict[tuple, object] = {}
    for claim in Claim._default_manager.filter(target_type__in=("structure", "metric", "link")).order_by("-at", "-assertion__seq").iterator():
        winners.setdefault((claim.organization_id, claim.target_type, str(claim.target_id)), claim)

    ClaimCurrent._default_manager.bulk_create(
        [
            ClaimCurrent(
                id=uuid.uuid4(),
                organization_id=organization_id,
                target_type=target_type,
                target_id=target_id,
                stands=claim.stands,
                claim=claim,
            )
            for (organization_id, target_type, target_id), claim in winners.items()
        ],
        batch_size=1000,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('authentikate', '0006_alter_app_identifier_alter_release_unique_together'),
        ('evidence', '0003_claim_seq_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClaimCurrent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('target_type', models.CharField(help_text="Which table the target lives in: 'structure', 'metric' or 'link'. Never 'node' — see the class docstring.", max_length=32)),
                ('target_id', models.UUIDField(help_text="The target row's primary key. A `UUIDField` where `Claim.target_id` is a `CharField`, because this column exists to be joined against those tables' primary keys and a text-to-uuid comparison would either fail or force a cast into every query that narrows by standing.")),
                ('stands', models.BooleanField(help_text='The folded answer. Derived from `Claim` and never authoritative — rebuild it and it must not change.')),
                ('claim', models.ForeignKey(help_text='The claim this answer came from. CASCADE because this row is a projection of that one: if the claim goes, so does the answer derived from it.', on_delete=django.db.models.deletion.CASCADE, related_name='+', to='evidence.claim')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='claim_currents', to='authentikate.organization')),
            ],
            options={
                'base_manager_name': 'all_objects',
                'default_manager_name': 'all_objects',
                'indexes': [models.Index(fields=['organization', 'target_type', 'stands'], name='evidence_cl_organiz_b4a1b3_idx')],
                'constraints': [models.UniqueConstraint(fields=('organization', 'target_type', 'target_id'), name='one_current_answer_per_target')],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunPython(fold_claim_current, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='link',
            name='stands',
        ),
        migrations.RemoveField(
            model_name='metric',
            name='stands',
        ),
        migrations.RemoveField(
            model_name='structure',
            name='stands',
        ),
    ]
