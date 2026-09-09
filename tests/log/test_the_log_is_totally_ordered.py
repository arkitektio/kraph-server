"""The log is totally ordered (A1).

`Assertion.seq` is assigned by the database, is monotonic, and is what the fold
orders by; `changes(afterSeq:)` reads it forward and is cut at the committed
horizon so a late-committing act is never skipped.

History: every row was keyed on a `uuid4`, so "replay the log in order" had no
order, and two claims written in one request could fold either way.
"""

from __future__ import annotations
import datetime
import pytest
from django.db import connection
from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import writer
import asyncio
import uuid
from tests.support import reads, sessions, writes


@pytest.mark.django_db(transaction=True)
def test_the_database_assigns_seq_and_no_writer_can_pass_one(organization) -> None:
    """`seq` comes from a sequence, not from application code.

    `writer.create_assertion` takes no `seq` argument and the field is
    `editable=False` with a `db_default`, so there is no path by which a caller
    chooses its own position in the log.
    """
    assertion = writer.create_assertion(organization, subject="someone", app_id="app")
    assertion.refresh_from_db()

    assert assertion.seq is not None, "The database must assign a position"
    assert isinstance(assertion.seq, int)

    field = evidence_models.Assertion._meta.get_field("seq")
    assert field.editable is False, "A writer choosing its own seq would be choosing where in history it lands"
    assert field.unique is True, "Two assertions sharing a position is the tie this column exists to remove"


@pytest.mark.django_db(transaction=True)
def test_seq_is_monotonic_across_assertions(organization) -> None:
    """Later assertions get higher positions, and none repeat."""
    written = [writer.create_assertion(organization, subject=f"s{index}", app_id="app") for index in range(25)]
    for assertion in written:
        assertion.refresh_from_db()

    seqs = [assertion.seq for assertion in written]

    assert seqs == sorted(seqs), "Arrival order and seq order must agree"
    assert len(set(seqs)) == len(seqs), "No two assertions may share a position"


@pytest.mark.django_db(transaction=True)
def test_seq_does_not_repeat_across_organizations(organization, other_organization) -> None:
    """One order spans the log, not one per tenant.

    Tenancy scopes what a fold *reads*; it does not give each tenant its own
    history. A per-organization counter would make "replay everything in order"
    unanswerable the moment two tenants existed.
    """
    here = writer.create_assertion(organization, subject="a", app_id="app")
    there = writer.create_assertion(other_organization, subject="b", app_id="app")
    here.refresh_from_db()
    there.refresh_from_db()

    assert here.seq != there.seq
    assert there.seq > here.seq, "The sequence is global and does not restart per tenant"


@pytest.mark.django_db(transaction=True)
def test_the_fold_breaks_ties_on_seq_not_on_wall_clock(organization, roi_kind) -> None:
    """Two claims at the same instant resolve deterministically, by the later assertion.

    This is the case `recorded_at` could not decide. Both claims are given the
    *same* `at`, so the fold has nothing to order them by except the tiebreak — and
    the answer must be the one asserted later, every time.
    """
    instant = datetime.datetime(2026, 3, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)

    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-total-order", assertion=minting)

    first = writer.create_assertion(organization, subject="first", app_id="app")
    writer.record_standing_for_ref(
        organization,
        target_type="structure",
        target_id=str(structure.pk),
        stands=True,
        assertion=first,
        at=instant,
    )

    second = writer.create_assertion(organization, subject="second", app_id="app")
    writer.record_standing_for_ref(
        organization,
        target_type="structure",
        target_id=str(structure.pk),
        stands=False,
        assertion=second,
        at=instant,
    )

    assert claims_module.stands(organization, "structure", str(structure.pk)) is False, "The later assertion wins a tie on `at`"

    # And the same answer read the batch way, which folds in Python over the
    # ordered queryset rather than taking `.first()`.
    folded = claims_module.stands_for(organization, "structure", [str(structure.pk)])
    assert folded[str(structure.pk)] is False


@pytest.mark.django_db(transaction=True)
def test_the_sequence_survives_a_gap(organization) -> None:
    """Gaps are expected; density is not promised.

    A rolled-back transaction consumes a sequence value and leaves a hole. Any
    reader that treats `seq` as dense — "the next one is n+1" — breaks the first
    time a write fails, so the property under test is ordering, not contiguity.
    """
    before = writer.create_assertion(organization, subject="before", app_id="app")
    before.refresh_from_db()

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT nextval('{evidence_models.ASSERTION_SEQ}')")
        burned = cursor.fetchone()[0]

    after = writer.create_assertion(organization, subject="after", app_id="app")
    after.refresh_from_db()

    assert before.seq < burned < after.seq, "The burned value is skipped, and order still holds across the hole"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_changes_reads_forward_from_a_cursor(api_schema, simple_api_context, test_graph) -> None:
    first, second, third = [await writes.assert_entity(api_schema, simple_api_context, "AIS") for _ in range(3)]
    seqs = [entry["assertion"]["seq"] for entry in (first, second, third)]

    data = await writes.execute(api_schema, simple_api_context, reads.CHANGES, {"afterSeq": seqs[0]})
    feed = data["changes"]

    assert [row["seq"] for row in feed["assertions"]] == seqs[1:], "ascending, strictly after the cursor"
    assert feed["nextSeq"] == seqs[2], "the cursor to hand back next time"
    assert feed["horizon"] >= seqs[2], "everything returned is at or below the horizon"

    caught_up = (await writes.execute(api_schema, simple_api_context, reads.CHANGES, {"afterSeq": feed["nextSeq"]}))["changes"]
    assert caught_up["assertions"] == []
    assert caught_up["nextSeq"] == feed["nextSeq"], "an empty page keeps the cursor where it was"

    limited = (await writes.execute(api_schema, simple_api_context, reads.CHANGES, {"afterSeq": seqs[0], "limit": 1}))["changes"]
    assert [row["seq"] for row in limited["assertions"]] == [seqs[1]]
    assert limited["nextSeq"] == seqs[1]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_changes_withholds_what_may_still_be_committing(api_schema, simple_api_context, test_graph) -> None:
    """The horizon: `seq` is assigned at insert, not at commit.

    A writer that has taken seq N but not committed is invisible to a reader, and
    a reader polling `seq > cursor` would move its cursor past N on seeing N+1 —
    then never see N. `changes` therefore returns only rows whose transaction
    precedes every transaction still open, and reports `horizon` so a client can
    tell "nothing new" from "something is being withheld".
    """
    organization = simple_api_context.request._organization
    before = await writes.assert_entity(api_schema, simple_api_context, "AIS")
    cursor = before["assertion"]["seq"]

    other = await asyncio.to_thread(sessions.raw_connection)
    try:
        # The other writer takes the next seq and holds its transaction open.
        def start_and_hold() -> int:
            cur = other.execute(
                "INSERT INTO evidence_assertion (id, organization_id, subject, app_id, action_args, asserted_at, recorded_at) VALUES (%s, %s, %s, %s, %s, now(), now()) RETURNING seq",
                (str(uuid.uuid4()), organization.pk, "late-committer", "test", "{}"),
            )
            return int(cur.fetchone()[0])

        held_seq = await asyncio.to_thread(start_and_hold)
        assert held_seq == cursor + 1

        # Meanwhile this connection commits the seq after it.
        after = await writes.assert_entity(api_schema, simple_api_context, "AIS")
        assert after["assertion"]["seq"] == held_seq + 1

        withheld = (await writes.execute(api_schema, simple_api_context, reads.CHANGES, {"afterSeq": cursor}))["changes"]
        assert withheld["assertions"] == [], "the committed later row must not be handed out ahead of the one still open"
        assert withheld["nextSeq"] == cursor
        assert withheld["horizon"] < held_seq

        await asyncio.to_thread(other.commit)
    finally:
        await asyncio.to_thread(other.close)

    settled = (await writes.execute(api_schema, simple_api_context, reads.CHANGES, {"afterSeq": cursor}))["changes"]
    assert [row["seq"] for row in settled["assertions"]] == [held_seq, held_seq + 1]
    assert settled["horizon"] >= held_seq + 1
