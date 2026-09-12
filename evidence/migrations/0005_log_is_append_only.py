"""Hold the log to append-only in the database, not in a docstring.

`evidence/writer.py` has promised "there is no update and no delete" since it was
written, and the promise was enforced by nothing. It was also false — `claim()`
issued an `UPDATE` four lines below it — until `0004` moved the cached answer into
`ClaimCurrent`. With the last writer gone, the rule can finally be made real.

**Triggers rather than `REVOKE`.** A superuser ignores table privileges entirely,
and the role the application connects as is frequently one — in the test stack it
certainly is — so a grant-based guard would be silently absent exactly where it
was most needed, and untestable besides. A trigger applies to everybody.

**UPDATE and DELETE both.** Retraction is a new `Claim`, so nothing in the write
path needs either. The escape hatch is explicit and session-local:

    SET LOCAL kraph.allow_log_rewrite = 'on';

`manage.py redact` sets it, because deliberate erasure is the one sanctioned
reason to destroy evidence, and a migration that has to rewrite history can set it
too. Both are greppable, which is the point — an escape you have to name is not
the same as no guard at all.

Deliberately **not** covered: `evidence_claimcurrent` and `evidence_state`. Those
are projections, folded from the log and rebuildable from it, and they are mutable
by design. A projection that could not be rewritten would not be a projection.
"""

from django.db import migrations

#: The tables that are the log. Everything else in the app is derived from these.
LOG_TABLES = (
    "evidence_assertion",
    "evidence_claim",
    "evidence_structure",
    "evidence_metric",
    "evidence_link",
    "evidence_node",
)

GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION evidence_refuse_log_rewrite() RETURNS trigger AS $$
BEGIN
    IF current_setting('kraph.allow_log_rewrite', true) = 'on' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    RAISE EXCEPTION
        'evidence is append-only: % on % is refused. Retract with a Claim, or set LOCAL kraph.allow_log_rewrite to on if you are redacting.',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS evidence_refuse_log_rewrite() CASCADE;"


def _attach(table: str) -> str:
    return f"""
CREATE TRIGGER {table}_append_only
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION evidence_refuse_log_rewrite();
"""


def _detach(table: str) -> str:
    return f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};"


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0004_claim_current"),
    ]

    operations = [
        migrations.RunSQL(sql=GUARD_FUNCTION, reverse_sql=DROP_FUNCTION),
        *[migrations.RunSQL(sql=_attach(table), reverse_sql=_detach(table)) for table in LOG_TABLES],
    ]
