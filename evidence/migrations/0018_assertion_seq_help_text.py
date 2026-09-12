"""Help text only. No SQL.

`Assertion.seq` gained the sentence pointing at `evidence/log.py` and
`changes(afterSeq:)` when RFC 0020 landed, and no migration recorded it, so
`makemigrations --check` failed on a column that never changed. Django ignores
`help_text` when deciding whether to alter a column; this operation is the
model state catching up with the code, and `tests/guards/test_migrations_are_committed.py`
is what now refuses a model change with no migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0017_a_structure_is_an_individual"),
    ]

    operations = [
        migrations.AlterField(
            model_name="assertion",
            name="seq",
            field=models.BigIntegerField(
                db_default=models.Func(function="nextval", output_field=models.BigIntegerField(), template="nextval('evidence_assertion_seq')"),
                editable=False,
                help_text=(
                    "Monotonic position in the organization-spanning log. The identity stays the uuid — "
                    "clients hold it, and a sequence would leak insertion order into an external handle — "
                    "but every fold needs an order to replay in, and until this existed there was none. "
                    "Replay ordered by `measured_at`, which is world time: backfillable, not monotonic "
                    "with arrival, and with no tiebreak. "
                    "On the **assertion** and nowhere else, because an assertion is already the unit of "
                    "authorship — a set of claims made together by one actor in one act is one assertion — "
                    "so one column orders the whole log and the rows within an act are simultaneous, which "
                    "is what they are. "
                    "Assigned at insert, not at commit, so a reader polling `seq > cursor` can skip a row "
                    "that committed late; gate the cursor on `pg_snapshot_xmin(pg_current_snapshot())` "
                    "rather than serializing the write path, which would throttle bulk ingest. "
                    "`evidence/log.py` is that gate, and `changes(afterSeq:)` the read built on it (RFC 0020)."
                ),
                unique=True,
            ),
        ),
    ]
