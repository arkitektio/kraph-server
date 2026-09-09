"""A word's identity is immutable in the database (RFC 0022).

`Term`, `StructureKind` and `MetricKind` are the only rows in this app that are
written in place, and rightly: how a word *presents* — label, description,
colour — is not evidence. Its *identity* is: `(organization, kind, key)` for a
term, `(organization, identifier)` for a structure kind,
`(organization, structure_kind, key, value_kind)` for a metric kind. Every
claim ever recorded points at one of those, so rewriting it would silently
re-point the whole log at a different word — and the only guard was a
docstring on `updateTerm`.

Same shape as `0005`: a `BEFORE UPDATE OF <identity columns>` trigger on each
table, honouring the same `SET LOCAL kraph.allow_log_rewrite = 'on'` hatch
`manage.py redact` uses, so a deliberate, named rewrite stays possible and a
casual one is refused. Deletion is not guarded here — a word nothing names may
be retired, and the `PROTECT` FKs refuse one that has been used.
"""

from django.db import migrations

#: (table, identity columns)
VOCABULARY = (
    ("evidence_term", ("organization_id", "kind", "key")),
    ("evidence_structurekind", ("organization_id", "identifier")),
    ("evidence_metrickind", ("organization_id", "structure_kind_id", "key", "value_kind")),
)

GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION evidence_refuse_identity_rewrite() RETURNS trigger AS $$
DECLARE
    col text;
    before jsonb := to_jsonb(OLD);
    after jsonb := to_jsonb(NEW);
BEGIN
    IF current_setting('kraph.allow_log_rewrite', true) = 'on' THEN
        RETURN NEW;
    END IF;
    -- Compare values, not the SET list: Django's save() rewrites every column,
    -- so an UPDATE OF trigger alone would refuse an unchanged identity.
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

DROP_FUNCTION = "DROP FUNCTION IF EXISTS evidence_refuse_identity_rewrite() CASCADE;"


def _attach(table: str, columns: tuple[str, ...]) -> str:
    return f"""
CREATE TRIGGER {table}_identity_immutable
BEFORE UPDATE OF {", ".join(columns)} ON {table}
FOR EACH ROW EXECUTE FUNCTION evidence_refuse_identity_rewrite({", ".join(repr(column) for column in columns)});
"""


def _detach(table: str) -> str:
    return f"DROP TRIGGER IF EXISTS {table}_identity_immutable ON {table};"


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0015_the_log_is_readable"),
    ]

    operations = [
        migrations.RunSQL(sql=GUARD_FUNCTION, reverse_sql=DROP_FUNCTION),
        *[migrations.RunSQL(sql=_attach(table, columns), reverse_sql=_detach(table)) for table, columns in VOCABULARY],
    ]
