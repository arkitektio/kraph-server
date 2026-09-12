"""Give the log a total order.

`docs/LOG.md` recorded the absence as a known gap: every evidence row is keyed on
a `uuid4`, so "replay the log in order" had no order to replay in, and the
projector fell back to ordering by `measured_at` — world time, which is
backfillable, not monotonic with arrival, and has no tiebreak.

The order goes on `Assertion` and nowhere else. An assertion is already the unit
of authorship, so one column orders the whole log while the rows written under one
assertion stay simultaneous, which is what they are.

A hand-made sequence rather than a `BigAutoField`, because Django permits an auto
field only as a primary key and the primary key stays a uuid deliberately — it is
the handle clients hold, and it must not carry insertion order.
"""

from django.db import migrations, models

SEQUENCE = "evidence_assertion_seq"

#: Existing rows are numbered in `recorded_at` order rather than in whatever
#: order Postgres happens to rewrite them in. `recorded_at` is storage time — the
#: closest thing the old schema has to arrival order, and the only honest
#: approximation available for claims made before the column existed.
#:
#: Offset past the sequence's current position so the unique index cannot collide
#: mid-update, then `setval` past the highest assigned value. Gaps are expected
#: and fine: a rolled-back transaction leaves one anyway. The column promises
#: monotonicity, not density.
BACKFILL = f"""
WITH ordered AS (
    SELECT id, row_number() OVER (ORDER BY recorded_at, id) AS rn
    FROM evidence_assertion
)
UPDATE evidence_assertion AS a
SET seq = ordered.rn + COALESCE((SELECT MAX(seq) FROM evidence_assertion), 0)
FROM ordered
WHERE a.id = ordered.id;

SELECT setval('{SEQUENCE}', COALESCE((SELECT MAX(seq) FROM evidence_assertion), 0) + 1, false);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0001_initial"),
    ]

    operations = [
        # Before the column, because the column's default calls it.
        migrations.RunSQL(
            sql=f"CREATE SEQUENCE IF NOT EXISTS {SEQUENCE} AS bigint START WITH 1 INCREMENT BY 1;",
            reverse_sql=f"DROP SEQUENCE IF EXISTS {SEQUENCE};",
        ),
        migrations.AddField(
            model_name="assertion",
            name="seq",
            field=models.BigIntegerField(
                unique=True,
                editable=False,
                db_default=models.Func(
                    function="nextval",
                    template=f"nextval('{SEQUENCE}')",
                    output_field=models.BigIntegerField(),
                ),
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
                    "rather than serializing the write path, which would throttle bulk ingest."
                ),
            ),
        ),
        migrations.RunSQL(sql=BACKFILL, reverse_sql=migrations.RunSQL.noop),
    ]
