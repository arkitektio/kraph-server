"""One word per concept: `Node` becomes `Instance`, `Claim` becomes `Standing`.

Three words carried two meanings each, and every reader had to infer which from
context:

- **`Node`** was this row — a claimed individual, `entity | natural_event |
  protocol_event` — *and* the GraphQL interface, which is wider (a `Structure` and a
  `Metric` implement it and neither is ever drawn), *and* an Apache AGE vertex. The
  row is an `Instance` now, which is the word the docs already used for it: "every
  observation mints its own instance". `Node` keeps only the graph-facing sense.
- **`Claim`** was this row — somebody's *position* on whether something stands — while
  every docstring in the app used "claim" for the recorded statements themselves: an
  instance, a link, a metric, a structure. The vote is a `Standing` now, and "claim"
  is free to mean what it always meant in prose.

Four renames, and three consequences that are easy to miss:

**The append-only triggers.** `0005` attached one per log table, named
`{table}_append_only`. Postgres carries a trigger through `ALTER TABLE … RENAME`,
so the guard never lapses — but the names would still say `evidence_claim` and
`evidence_node` afterwards, which is exactly the sort of stale name this migration
exists to remove. They are dropped and recreated over the new table names, reusing
`evidence_refuse_log_rewrite()` unchanged.

**The discriminator.** `Standing.target_type` stores which table its target lives
in, and one of the four values was the string `"node"`. Renaming the model without
rewriting the data would leave `CLAIM_TARGETS` and the column disagreeing, so the
fold would silently match nothing for instances — the worst possible failure here,
since "no standing found" reads as "it stands". `evidence_standing` is a log table,
so the rewrite opens with the escape `0005` provides for precisely this ("a
migration that has to rewrite history can set it too") and names itself while doing
so.

**The index name.** `claimcurrent_retracted_idx` was given explicitly by `0007`, so
it does not follow the table.
"""

from django.db import migrations, models

#: The log, under its new names. Same list as `0005`'s `LOG_TABLES` with the two
#: renamed tables substituted.
LOG_TABLES = (
    "evidence_assertion",
    "evidence_standing",
    "evidence_structure",
    "evidence_metric",
    "evidence_link",
    "evidence_instance",
)

#: The names `0005` created, which the renamed tables still carry.
OLD_TRIGGERS = (
    ("evidence_claim", "evidence_standing"),
    ("evidence_node", "evidence_instance"),
)


def _attach(name: str, table: str) -> str:
    """Create the guard trigger on `table`, named for `name`.

    The two are the same everywhere except here: a renamed table still carries a
    trigger named after what it used to be called, and reversing this migration has
    to put that state back before the table is renamed back.
    """
    return f"""
CREATE TRIGGER {name}_append_only
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION evidence_refuse_log_rewrite();
"""


def _detach(name: str, table: str) -> str:
    return f"DROP TRIGGER IF EXISTS {name}_append_only ON {table};"


def _rename_target_type(old: str, new: str) -> str:
    """Rewrite the discriminator on the log and on its projection.

    `SET LOCAL` and not a plain `SET`: the escape must not outlive the transaction
    this migration runs in, or the rest of the migration plan would execute with the
    append-only guard disabled.
    """
    return f"""
SET LOCAL kraph.allow_log_rewrite = 'on';
UPDATE evidence_standing SET target_type = '{new}' WHERE target_type = '{old}';
UPDATE evidence_currentstanding SET target_type = '{new}' WHERE target_type = '{old}';
"""


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0007_standing_is_seekable"),
    ]

    operations = [
        migrations.RenameModel(old_name="Node", new_name="Instance"),
        migrations.RenameModel(old_name="NodeIdentity", new_name="InstanceIdentity"),
        migrations.RenameModel(old_name="Claim", new_name="Standing"),
        migrations.RenameModel(old_name="ClaimCurrent", new_name="CurrentStanding"),
        migrations.RenameField(model_name="currentstanding", old_name="claim", new_name="standing"),
        migrations.RenameField(model_name="instanceidentity", old_name="node", new_name="instance"),
        # `State.entity_ref` held "a node ref, or a link ref when the statistic
        # describes an edge" — so "entity" there named neither an entity nor even a
        # node. Both of the things it can hold are claims, which is what it says now.
        migrations.RenameField(model_name="state", old_name="entity_ref", new_name="claim_ref"),
        # The one index whose name was given explicitly, by `0007`. The rest are
        # auto-named, and Django derives those names from the table — so renaming the
        # table means renaming every one of them, which is what the block below is.
        migrations.RenameIndex(
            model_name="currentstanding",
            old_name="claimcurrent_retracted_idx",
            new_name="currentstanding_retracted_idx",
        ),
        migrations.RenameIndex(
            model_name="currentstanding",
            old_name="evidence_cl_organiz_b4a1b3_idx",
            new_name="evidence_cu_organiz_173f8b_idx",
        ),
        migrations.RenameIndex(
            model_name="instance",
            old_name="evidence_no_organiz_072485_idx",
            new_name="evidence_in_organiz_737987_idx",
        ),
        migrations.RenameIndex(
            model_name="instance",
            old_name="evidence_no_organiz_54ce2f_idx",
            new_name="evidence_in_organiz_f442b4_idx",
        ),
        migrations.RenameIndex(
            model_name="instanceidentity",
            old_name="evidence_no_organiz_3c6ee0_idx",
            new_name="evidence_in_organiz_41fb3b_idx",
        ),
        migrations.RenameIndex(
            model_name="instanceidentity",
            old_name="evidence_no_organiz_0dbf93_idx",
            new_name="evidence_in_organiz_f65394_idx",
        ),
        migrations.RenameIndex(
            model_name="standing",
            old_name="evidence_cl_organiz_9ef309_idx",
            new_name="evidence_st_organiz_c2cec2_idx",
        ),
        # State-only: `related_name` is not a column, but the model state has to
        # match the models or `makemigrations --check` stays dirty forever.
        migrations.AlterField(
            model_name="standing",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="standings", to="authentikate.organization"),
        ),
        migrations.AlterField(
            model_name="standing",
            name="assertion",
            field=models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="standings", to="evidence.assertion"),
        ),
        migrations.AlterField(
            model_name="currentstanding",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="current_standings", to="authentikate.organization"),
        ),
        migrations.AlterField(
            model_name="currentstanding",
            name="standing",
            field=models.ForeignKey(
                help_text="The standing this answer was folded from — the claim that won. CASCADE because this row is a projection of that one: if it goes, so does the answer derived from it.",
                on_delete=models.deletion.CASCADE,
                related_name="+",
                to="evidence.standing",
            ),
        ),
        migrations.AlterField(
            model_name="currentstanding",
            name="stands",
            field=models.BooleanField(help_text="The folded answer. Derived from `Standing` and never authoritative — rebuild it and it must not change."),
        ),
        migrations.AlterField(
            model_name="currentstanding",
            name="target_id",
            field=models.UUIDField(help_text="The target row's primary key. A `UUIDField` where `Standing.target_id` is a `CharField`, because this column exists to be joined against those tables' primary keys and a text-to-uuid comparison would either fail or force a cast into every query that narrows by standing."),
        ),
        migrations.AlterField(
            model_name="currentstanding",
            name="target_type",
            field=models.CharField(help_text="Which table the target lives in: 'structure', 'metric' or 'link'. Never 'instance' — see the class docstring.", max_length=32),
        ),
        migrations.AlterField(
            model_name="standing",
            name="target_type",
            field=models.CharField(help_text="Which table the claim this is about lives in: 'structure', 'metric', 'link' or 'instance'.", max_length=32),
        ),
        migrations.AlterField(
            model_name="instanceidentity",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="instance_identities", to="authentikate.organization"),
        ),
        migrations.AlterField(
            model_name="instanceidentity",
            name="instance",
            field=models.OneToOneField(
                help_text="An instance belonging to a component of two or more.",
                on_delete=models.deletion.CASCADE,
                related_name="identity",
                to="evidence.instance",
            ),
        ),
        migrations.AlterField(
            model_name="instance",
            name="organization",
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="instances", to="authentikate.organization"),
        ),
        migrations.AlterField(
            model_name="instance",
            name="term",
            field=models.ForeignKey(
                help_text="The organization's word this instance was first claimed under. Which view shows it, and as what, is decided from the claims — see `projector.resolve_categories`.",
                on_delete=models.deletion.PROTECT,
                related_name="instances",
                to="evidence.term",
            ),
        ),
        migrations.AlterField(
            model_name="instance",
            name="assertion",
            field=models.ForeignKey(
                help_text="The assertion that first claimed this instance exists.",
                on_delete=models.deletion.PROTECT,
                related_name="instances",
                to="evidence.assertion",
            ),
        ),
        # `State`'s constraint and index both named the old column, and neither can be
        # renamed in place: the constraint's *name* carries "per_entity" and the
        # index's auto-name hashes the column list. Dropped and recreated.
        migrations.RemoveConstraint(model_name="state", name="unique_state_per_entity_source_kind_key_value_kind"),
        migrations.RemoveIndex(model_name="state", name="evidence_st_organiz_db1935_idx"),
        migrations.AddIndex(
            model_name="state",
            index=models.Index(fields=["organization", "claim_ref"], name="evidence_st_organiz_5a9e5e_idx"),
        ),
        migrations.AddConstraint(
            model_name="state",
            constraint=models.UniqueConstraint(fields=("organization", "claim_ref", "source_kind", "key", "value_kind"), name="unique_state_per_claim_source_kind_key_value_kind"),
        ),
        migrations.RunSQL(
            # Forward: the trigger on `evidence_standing` is still called
            # `evidence_claim_append_only`; drop it and recreate it under the table's
            # own name. Reverse puts the old name back, because the `RenameModel`
            # above reverses *after* this does.
            sql=[_detach(old, new) for old, new in OLD_TRIGGERS] + [_attach(new, new) for _, new in OLD_TRIGGERS],
            reverse_sql=[_detach(new, new) for _, new in OLD_TRIGGERS] + [_attach(old, new) for old, new in OLD_TRIGGERS],
        ),
        migrations.RunSQL(
            sql=_rename_target_type("node", "instance"),
            reverse_sql=_rename_target_type("instance", "node"),
        ),
    ]
