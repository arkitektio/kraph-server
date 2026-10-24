"""What the database itself refuses: the log is append-only, and a word's identity is immutable.

Hand-written, so re-add it whenever the history is regenerated: ``makemigrations`` emits
none of this. Both guards honour ``SET LOCAL kraph.allow_log_rewrite = 'on'``, the hatch
``manage.py redact`` uses, so a deliberate, named rewrite stays possible and a casual one is
refused.

- **Append-only** (RFC 0003): every log table refuses UPDATE and DELETE. A correction is a
  new claim (a ``Standing``), never an edit.
- **Identity is immutable** (RFC 0022): ``Term``, ``StructureKind`` and ``MetricKind`` are
  written in place for how a word *presents*, but every claim points at their identity
  columns, so rewriting those would re-point the whole log at a different word. Values are
  compared, not the SET list: Django's ``save()`` rewrites every column. Deletion is not
  guarded; the ``PROTECT`` FKs refuse a word that has been used.
"""

from django.db import migrations

LOG_TABLES = (
    "evidence_assertion",
    "evidence_standing",
    "evidence_structure",
    "evidence_metric",
    "evidence_link",
    "evidence_instance",
    "evidence_comment",
)

#: (table, identity columns)
VOCABULARY = (
    ("evidence_term", ("organization_id", "kind", "key")),
    ("evidence_structurekind", ("organization_id", "identifier")),
    ("evidence_metrickind", ("organization_id", "structure_kind_id", "key", "value_kind")),
)

LOG_GUARD = """
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

IDENTITY_GUARD = """
CREATE OR REPLACE FUNCTION evidence_refuse_identity_rewrite() RETURNS trigger AS $$
DECLARE
    col text;
    before jsonb := to_jsonb(OLD);
    after jsonb := to_jsonb(NEW);
BEGIN
    IF current_setting('kraph.allow_log_rewrite', true) = 'on' THEN
        RETURN NEW;
    END IF;
    FOREACH col IN ARRAY TG_ARGV LOOP
        IF (before -> col) IS DISTINCT FROM (after -> col) THEN
            RAISE EXCEPTION
                'a word''s identity is immutable: rewriting % on % would re-point every claim that names it. Declare the right word and re-classify, or set LOCAL kraph.allow_log_rewrite to on if you are redacting.',
                col, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _append_only(table: str) -> str:
    return f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION evidence_refuse_log_rewrite();"


def _immutable(table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(columns)
    args = ", ".join(f"'{column}'" for column in columns)
    return f"CREATE TRIGGER {table}_identity_immutable BEFORE UPDATE OF {cols} ON {table} FOR EACH ROW EXECUTE FUNCTION evidence_refuse_identity_rewrite({args});"


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=LOG_GUARD, reverse_sql="DROP FUNCTION IF EXISTS evidence_refuse_log_rewrite() CASCADE;"),
        *[migrations.RunSQL(sql=_append_only(table), reverse_sql=f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};") for table in LOG_TABLES],
        migrations.RunSQL(sql=IDENTITY_GUARD, reverse_sql="DROP FUNCTION IF EXISTS evidence_refuse_identity_rewrite() CASCADE;"),
        *[migrations.RunSQL(sql=_immutable(table, columns), reverse_sql=f"DROP TRIGGER IF EXISTS {table}_identity_immutable ON {table};") for table, columns in VOCABULARY],
    ]
