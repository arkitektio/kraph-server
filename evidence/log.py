"""Reading the log forward: the committed horizon (RFC 0020).

`Assertion.seq` is assigned at insert, not at commit. Two writers can take seqs
N and N+1 and commit in the other order, so a reader that polls ``seq > cursor``
and moves its cursor to N+1 on seeing it has skipped N for good — it will never
ask for it again. The column's own help text names the fix: gate the feed on
``pg_snapshot_xmin(pg_current_snapshot())`` rather than serializing the write
path, which would throttle bulk ingest.

The gate is one predicate, :func:`before_every_open_transaction`: a row counts
only if the transaction that wrote it (its ``xmin``) precedes every transaction
still in progress at the moment of the read. A row that passes cannot be
followed by a lower seq still to come from an *older* transaction, because no
older transaction is open. What it withholds is anything written after the
oldest open writer started — for as long as that writer is open. A bulk ingest
that holds its transaction for ten minutes therefore delays the feed by ten
minutes, for every other writer's rows too; that is the trade the help text
chose, and :func:`horizon` is how a client sees it happening: a ``horizon``
below the newest seq it can otherwise read means rows are being withheld, not
that nothing was written.

One window the gate does not close. Postgres assigns a transaction's id lazily,
on its first write — for an assertion, inside the very ``INSERT`` that also
evaluates ``nextval`` for ``seq``, and the seq is drawn *before* the row is
written and the id assigned. Two inserts interleaving exactly there (T takes
seq N; R takes seq N+1, gets its id, commits; T then gets its id) leave R
passing the gate while T, with the lower seq, is still open. The window is the
inside of a single statement — microseconds, with no round trip in it — and
assigning the id eagerly first would only widen it to a statement boundary, so
it is documented rather than papered over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import BooleanField, Max, QuerySet
from django.db.models.expressions import RawSQL

if TYPE_CHECKING:
    from evidence import models as evidence_models

#: `age(xid)` counts transactions back from the current counter, so an older
#: transaction has a *larger* age; comparing ages is how xids are ordered across
#: the 32-bit wraparound. The snapshot's xmin is an `xid8` (epoch-qualified) and is
#: cast down to compare with the row's `xmin` system column.
_PRECEDES_EVERY_OPEN_TRANSACTION = 'age("evidence_assertion"."xmin") > age(pg_snapshot_xmin(pg_current_snapshot())::xid)'


def before_every_open_transaction(queryset: QuerySet[evidence_models.Assertion]) -> QuerySet[evidence_models.Assertion]:
    """Narrow an ``Assertion`` queryset to rows no open transaction can precede.

    The predicate reads the row's ``xmin`` system column, so it applies only to a
    queryset over ``evidence_assertion`` itself — not to a join through it.
    """
    # `output_field` is what makes the expression *conditional* in Django's eyes;
    # without it `.filter()` refuses a raw predicate outright.
    return queryset.filter(RawSQL(_PRECEDES_EVERY_OPEN_TRANSACTION, (), output_field=BooleanField()))


def horizon(queryset: QuerySet[evidence_models.Assertion]) -> int:
    """The highest seq the gate admits in ``queryset``, or 0 when it admits none.

    Every assertion at or below it that will ever be visible already is; one above
    it may still be committing.
    """
    return int(before_every_open_transaction(queryset).aggregate(top=Max("seq"))["top"] or 0)
