"""Entity identity: the `SAME_AS` claim, and the fold over it.

Every observation mints its own instance — "this is an AIS" writes a fresh node
rather than reusing one — so identity *between* observations has to be a claim in
its own right. `docs/LOG.md` listed this as a known gap: *"No merge. Identity is a
bare uuid, so one vertex standing for several nodes is expressible — but nothing
implements it."*

Two operations here:

- **`Link.Kind.SAME_AS`**, entity to entity. It inherits the existing
  `(organization, kind, source_ref)` / `…target_ref` indexes, `claims.standing()`,
  retraction and provenance, because it is a `Link` like every other claim.
- **`NodeIdentity`**, the persisted union-find over those claims, so "everything
  known about this thing" is `WHERE canonical = c` rather than a traversal.

**`NodeIdentity` is deliberately absent from `LOG_TABLES` in
`0005_log_is_append_only`.** That migration's own docstring records the rule it
follows: `evidence_claimcurrent` and `evidence_state` are excluded because they
are projections of the log rather than part of it, and a fold that cannot be
rewritten cannot be recomputed. This table is the same kind of thing — `identity.recompute`
exists precisely to rewrite it — so it must stay mutable.
"""

import django.db.models.deletion
import django.db.models.manager
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentikate', '0006_alter_app_identifier_alter_release_unique_together'),
        ('evidence', '0005_log_is_append_only'),
    ]

    operations = [
        migrations.AlterField(
            model_name='link',
            name='kind',
            field=models.CharField(choices=[('informs', 'Informs'), ('relation', 'Relation'), ('structure_relation', 'Structure relation'), ('measurement', 'Measurement'), ('participates_as_input', 'Participates as input'), ('participates_as_output', 'Participates as output'), ('classifies', 'Classifies'), ('same_as', 'Same as')], max_length=32),
        ),
        migrations.CreateModel(
            name='NodeIdentity',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('needs_recompute', models.BooleanField(default=False, help_text='Set when a retraction may have split this component. Union is O(α) and incremental; un-union is not expressible incrementally, so the affected component is rebuilt from its surviving claims instead. Same escape hatch as `State.needs_recompute`.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('canonical', models.ForeignKey(help_text="The component's representative — the lowest uuid among its members, itself included.", on_delete=django.db.models.deletion.CASCADE, related_name='identity_members', to='evidence.node')),
                ('node', models.OneToOneField(help_text='A node belonging to a component of two or more.', on_delete=django.db.models.deletion.CASCADE, related_name='identity', to='evidence.node')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='node_identities', to='authentikate.organization')),
            ],
            options={
                'base_manager_name': 'all_objects',
                'default_manager_name': 'all_objects',
                'indexes': [models.Index(fields=['organization', 'canonical'], name='evidence_no_organiz_3c6ee0_idx'), models.Index(fields=['organization', 'needs_recompute'], name='evidence_no_organiz_0dbf93_idx')],
            },
            managers=[
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
