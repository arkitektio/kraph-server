"""Extend the append-only guard to the comment table.

A comment is a claim — a remark somebody made about a structure — so it gets the
same trigger `0005_log_is_append_only` put on the other six log tables. Editing
a comment is writing a new one; withdrawing or resolving one is a `Standing`.
The escape hatch is the same session-local `kraph.allow_log_rewrite` that
`manage.py redact` sets, and redaction of comments matters more than most: a
remark is free text and is exactly where a name that must be erased will appear.
"""

from django.db import migrations

TABLE = "evidence_comment"

ATTACH = f"""
CREATE TRIGGER {TABLE}_append_only
BEFORE UPDATE OR DELETE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION evidence_refuse_log_rewrite();
"""

DETACH = f"DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE};"


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0009_alter_standing_target_type_comment"),
    ]

    operations = [
        migrations.RunSQL(sql=ATTACH, reverse_sql=DETACH),
    ]
